#!/usr/bin/env python3
"""Crypto Trading Signal System (v4)

Runs 3 times/day via GitHub Actions cron at 06:00, 12:00, 20:00 VNT.

System (v4):
  Layer 1 – Trend Engine (3D candles, MA7/MA10/MA20) → TrendScore ±3
  Layer 2 – Execution Engine (1D candles, MA3/MA7/Vol/ATR14) → weighted probs
  3-stage scaling entries with 3x leverage
  Adaptive entry: ±2 when trend_score≥2, ±3 otherwise
  Risk: max 4 concurrent positions, 15% capital per position
  Position rate limit: no new entries when ≥4 open; tight entry when >50% deployed

Required environment variables:
  DISCORD_TRADING_WEBHOOK_URL  – Discord webhook for signal output
  FIREBASE_SERVICE_ACCOUNT     – Firebase service-account JSON (optional, for
                                 state persistence across runs)
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.discord_webhook import send_message
from utils.okx_utils import (
    OKX_INSTRUMENTS, calc_contract_size, get_instrument_map,
    OKXMetadataError,
    get_okx_position_for_coin, okx_close_position, okx_get_account,
    okx_get_positions, okx_place_order, okx_set_leverage, OKXError,
    okx_get_algo_orders, okx_amend_algo,
)
from utils.retry_utils import call_with_retry
from utils.firebase_utils import (
    get_unsent_queued_alerts, is_firebase_enabled,
    mark_alert_sent, queue_alert,
)
from trading_config import (  # centralized config
    COINS, SYMBOL_MAP, BASE, MAX_POS_PCT, ENTRY_MIN_SCORE,
    ENTRY_COOLDOWN_BARS, TP_SCHEDULE,
    FIBONACCI_COOLDOWN_MIN, SL_ROLLING_CAP, SL_ROLLING_LOCK_BARS,
    SL_ROLLING_FIB, SIDEWAY_MAX_SCORE,
    BULL_SNOWBALL_LEVELS, BULL_SNOWBALL_SIZES, BULL_INITIAL_SIZE,
    BULL_TRAIL_DISTANCE, BULL_TRAIL_ACTIVATION,
    BULL_TRAIL_CLOSE, BULL_TRAIL_COOLDOWN_BARS, BULL_NO_SL, BULL_MAX_LOSS,
    BULL_TP_SCHEDULE,
    COIN_CONFIG, SF,
    SHORT_ALLOWED,
    _coin_lev, _coin_sl_roi, _coin_trail, _coin_cap,
    get_profile,
)


try:
    import pytz
    _VNT = pytz.timezone("Asia/Ho_Chi_Minh")
    def _now_vnt() -> datetime:
        return datetime.now(_VNT)
except ImportError:
    from datetime import timezone, timedelta
    _VNT_OFFSET = timedelta(hours=7)
    _VNT_TZ = timezone(timedelta(hours=7), name="VNT")
    def _now_vnt() -> datetime:
        return datetime.now(_VNT_TZ)

# ---------------------------------------------------------------------------
# Configuration — all constants imported from trading_config.py
# ---------------------------------------------------------------------------

# Runtime-only helpers (not in trading_config)
def get_snowball_size(entry_num: int, entry_score: float) -> float:
    if entry_num == 2:
        return 0.034
    elif entry_num == 3:
        return 0.034 if entry_score >= 65 else 0.017
    return 0

def _entry_margin(coin: str, strong: bool = True) -> float:
    return 0.09 if strong else 0.07


# Times (VNT) when major economic events may cause volatility — no new entries ±2h
ECONOMIC_EVENT_WINDOWS: list[tuple[int, int]] = [
    (1, 4),   # FOMC minutes / fed speeches (~2am VNT) — wider window
    (7, 10),  # US NFP/CPI (~7:30pm ET → 7:30am VNT+1) — wider window
    (18, 21), # ECB/BOE rate decisions (~1-2pm GMT → 8-9pm VNT) — wider window
]

CANDLE_COUNT = 500          # 12h candles: need MA200(400) + ATR(28) buffer
BTC_CANDLE_COUNT = 220      # 1d candles for BTC kill-switch (unchanged)
BTC_SYMBOL = "BTCUSDT"      # BTC symbol for kill-switch and regime detection

MAX_PER_COIN_PCT = MAX_POS_PCT

# ── Risk Management ─────────────────────────────────────────────────
MAX_CONCURRENT_POSITIONS = 5     # 5 coins, 5 positions max
CAPITAL_PER_POSITION = 0.10      # 10% of total capital per position


MAX_MARGIN_PER_COIN_PCT = 0.20   # 20% margin cap (= 60% exposure at 3x)

# Correlation groups: skip entry if correlated coin already has a position
# Fibonacci cooldown: consec_losses → cooldown bars
#   2 losses → 3 bars (F4)
#   3 losses → 5 bars (F5)
#   4 losses → 8 bars (F6)
#   5 losses → 13 bars (F7)
#   ... → general formula: fib(consec_losses + 2)
def _fib_cooldown_bars(consec_losses: int, shift: int = 0) -> int:
    """Return cooldown bars using Fibonacci sequence with optional shift.

    shift=0 (standard): 2→3, 3→5, 4→8, 5→13, 6→21, ...
    shift=1:            2→5, 3→8, 4→13, 5→21, 6→34, ...
    shift=2:            2→8, 3→13, 4→21, 5→34, 6→55, ...
    General: fib(n) where n = consec_losses + 2 + shift
    """
    if consec_losses < FIBONACCI_COOLDOWN_MIN:
        return 0
    a, b = 1, 1
    for _ in range(consec_losses + 1 + shift):
        a, b = b, a + b
    return a

# ── 3SL Rolling Fibonacci Lock (separated per direction) ──────────────
# When 3 consecutive SLs in same direction → lock that direction for 8 bars
# Fibonacci progression: 3→8, 4→13, 5→21, 6→34 bars
# Combined with Sideway<3 filter to avoid choppy markets

def compute_adx(candles: list[dict], period: int = 14) -> float:
    """Compute Average Directional Index (ADX) from OHLC candles.
    
    ADX measures trend strength (not direction).
    ADX < 25: weak/choppy trend → skip entry
    ADX >= 25: strong trend → allow entry
    """
    period = int(period)
    if len(candles) < period + 1:
        return 50.0  # default to strong trend if insufficient data
    
    # Calculate True Range, +DM, -DM
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []
    
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_high = candles[i-1]["high"]
        prev_low = candles[i-1]["low"]
        prev_close = candles[i-1]["close"]
        
        # True Range
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
        
        # Directional Movement
        up_move = high - prev_high
        down_move = prev_low - low
        
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    
    # Smooth with Wilder's method
    atr = sum(tr_list[:period])
    plus_dm_sum = sum(plus_dm_list[:period])
    minus_dm_sum = sum(minus_dm_list[:period])
    
    dx_list = []
    
    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        plus_dm_sum = plus_dm_sum - (plus_dm_sum / period) + plus_dm_list[i]
        minus_dm_sum = minus_dm_sum - (minus_dm_sum / period) + minus_dm_list[i]
        
        if atr == 0:
            continue
        
        plus_di = 100 * plus_dm_sum / atr
        minus_di = 100 * minus_dm_sum / atr
        
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx = 0
        else:
            dx = 100 * abs(plus_di - minus_di) / di_sum
        
        dx_list.append(dx)
    
    if not dx_list:
        return 50.0
    
    # Calculate ADX as average of DX
    adx = sum(dx_list[-period:]) / min(period, len(dx_list))
    return adx


def compute_sideway_score(candles: list[dict], sf: float = 1.0) -> int:
    """Compute sideway score (0-4) based on MA convergence, slope, volume, and range.
    
    Score interpretation:
      0-1: Trending market
      2-3: Sideway / consolidation
      4:   Strong accumulation (very tight range, low volume)
    
    Components:
      1. MA spread: (abs(MA3-MA20) + abs(MA7-MA20) + abs(MA10-MA20)) / MA20 < 0.05
      2. MA20 slope: abs((MA20_now - MA20_prev_5bars) / MA20_prev_5bars) < 0.01
      3. Volume ratio: volume_now / volume_ma20 < 0.8
      4. Price range: (high20 - low20) / low20 < 0.15
    """
    if len(candles) < int(20 * sf) + 5:
        return 0  # Insufficient data, assume trending
    
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    volumes = [c['volume'] for c in candles]
    
    # MA calculations (scaled by sf)
    ma3 = sma(closes, int(3 * sf))
    ma7 = sma(closes, int(7 * sf))
    ma10 = sma(closes, int(10 * sf))
    ma20 = sma(closes, int(20 * sf))
    
    if not ma3 or not ma7 or not ma10 or not ma20:
        return 0
    if ma3[-1] is None or ma7[-1] is None or ma10[-1] is None or ma20[-1] is None:
        return 0
    
    score = 0
    
    # 1. MA spread
    if ma20[-1] > 0:
        ma_spread = (abs(ma3[-1] - ma20[-1]) + abs(ma7[-1] - ma20[-1]) + abs(ma10[-1] - ma20[-1])) / ma20[-1]
        if ma_spread < 0.05:
            score += 1
    
    # 2. MA20 slope (current vs 5 bars ago)
    idx_prev = int(5 * sf)
    if len(ma20) > idx_prev and ma20[-1 - idx_prev] is not None and ma20[-1 - idx_prev] > 0:
        slope20 = (ma20[-1] - ma20[-1 - idx_prev]) / ma20[-1 - idx_prev]
        if abs(slope20) < 0.01:
            score += 1
    
    # 3. Volume ratio
    vol_ma20 = sma(volumes, int(20 * sf))
    if vol_ma20 and vol_ma20[-1] is not None and vol_ma20[-1] > 0:
        vol_ratio = volumes[-1] / vol_ma20[-1]
        if vol_ratio < 0.8:
            score += 1
    
    # 4. Price range (20-bar high-low range)
    period = int(20 * sf)
    high20 = max(highs[-period:]) if len(highs) >= period else highs[-1]
    low20 = min(lows[-period:]) if len(lows) >= period else lows[-1]
    if low20 > 0:
        range_pct = (high20 - low20) / low20
        if range_pct < 0.15:
            score += 1
    
    return score

# Trend engine MA periods on 36h candles (aggregated 3×12h)
TREND_MA_FAST = 7
TREND_MA_MID = 14
TREND_MA_SLOW = 28

# Execution engine MA periods on 12h (scaled 1.5× from 1D baseline: MA12, MA25, MA20)
EXEC_MA_FAST = 18
EXEC_MA_MID = 37
EXEC_MA_SLOW = 30

# ── Sideway & Staged Reversal Exit ──────────────────────────────────
# Gradual exit schedule: (sideway_bars, additional_exit_pct)
TRAIL_ATR_PROFIT_MILESTONES = [  # (PnL%, atr_mult)
    (5.0, 1.5),
    (10.0, 1.0),
    (20.0, 0.75),
]


BTC_FLASH_CRASH_PCT = -5.0

FIRESTORE_COLLECTION = "crypto_trading_states"

# ── Per-coin Profiles (v7) ─────────────────────────────────────────────
# Entry quality filters:
#   use_ma200_filter:     block long if price < MA200
#   use_pullback_filter:  block entry if >3% away from MA7
#   use_volume_expan:     require last volume > 5d avg
#   min_entry_score:      0-100 quality gate (0=disabled)
# ATR trailing:
#   trail_atr_mult:        ATR multiplier for trailing distance
#   use_profit_locking:    tighten trail at 5/10/20% PnL milestones
# Snowball:
#   snowball_pnl_min:      min PnL% for snowball add (0.005 = 0.5%)
#   snowball_fast_min:     if score >= this, snowball even at 0% PnL
DEFAULT_PROFILE = {
    "leverage": 2.5,
    "trend_min_long": 2,        # only strong long (WEAK_BULLISH+)
    "trend_min_long_tight": 2,
    "trend_max_short": -2,      # only strong short (WEAK_BEARISH-)
    "vol_min": 0.3,
    "rsi_max_long": 90,
    "rsi_min_short": 10,
    "max_loss_pct": 0.07,
    "trailing_pct": 0.80,
    "initial_stop_pct": 0.80,
    "hard_stop_pct": 0.75,
    # v7 entry quality (score-based, no hard gates)
    "use_ma200_filter": False,
    "use_pullback_filter": False,
    "use_volume_expan": False,
    "min_entry_score": 50,        # stricter signal quality
    # v7 ATR trailing (disabled — use percentage trail for stability)
    "trail_atr_mult": 0,
    "use_profit_locking": False,
    # v7 snowball (conservative — only on proven winners)
    "snowball_pnl_min": 0.10,     # 10% PnL — effectively disabled, protects value
    # v7 short (tighter risk, smaller size)
    "short_max_loss_pct": 0.07,
    "short_trailing_pct": 0.82,
    "short_size_mult": 0.5,       # ½ size of long
    # v7 re-entry
    "reentry_cooldown_bars": 5,
}

COIN_PROFILES: dict[str, dict] = {
    "ETH": {
        "max_loss_pct": 0.07,
        "short_max_loss_pct": 0.07,
        "position_size_base": 0.18,
        "trend_min_long": 2,
        "trend_max_short": -2,
        "rsi_min_short": 45,
        "rsi_max_long": 65,
        "short_min_entry_score": 70,
    },
    "BNB": {
        "position_size_base": 0.18,
        "trend_min_long": 2,
        "trend_max_short": -3,
        "rsi_min_short": 45,
        "short_min_entry_score": 70,
    },
    "TRX": {
        "max_loss_pct": 0.07,
        "short_max_loss_pct": 0.07,
        "short_trailing_pct": 0.78,
        "position_size_base": 0.18,
        "trend_min_long": 2,
        "trend_max_short": -2,
        "rsi_min_short": 45,
        "short_min_entry_score": 70,
    },
}


def get_coin_profile(coin: str) -> dict:
    profile = dict(DEFAULT_PROFILE)
    if coin in COIN_PROFILES:
        profile.update(COIN_PROFILES[coin])
    return profile


# ---------------------------------------------------------------------------
# Binance API
# ---------------------------------------------------------------------------

def _parse_binance_klines(data: list) -> list[dict]:
    return [
        {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in data
    ]

def _parse_okx_klines(data: list) -> list[dict]:
    candles = list(reversed(data))
    return [
        {"open_time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in candles
    ]

def _fetch_binance(symbol: str, interval: str = "1d", host: str = "api.binance.com",
                   limit: int = CANDLE_COUNT) -> list[dict] | None:
    try:
        resp = requests.get(
            f"https://{host}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        return _parse_binance_klines(resp.json())
    except Exception as e:
        print(f"  [{host}] {symbol} failed: {e}")
        return None

def _fetch_okx(symbol: str, interval: str = "1D", limit: int = CANDLE_COUNT) -> list[dict] | None:
    okx_map = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT", "BNBUSDT": "BNB-USDT",
               "SOLUSDT": "SOL-USDT", "ARBUSDT": "ARB-USDT", "LINKUSDT": "LINK-USDT",
               "PAXGUSDT": "PAXG-USDT", "ADAUSDT": "ADA-USDT"}
    inst_id = okx_map.get(symbol)
    if not inst_id:
        return None
    try:
        resp = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": inst_id, "bar": interval, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "0":
            return None
        return _parse_okx_klines(body["data"])
    except Exception as e:
        print(f"  [OKX] {symbol} failed: {e}")
        return None

COINGECKO_DAYS = {"1d": 30, "3d": 90}
OKX_INTERVAL_MAP = {"1d": "1D", "3d": "3D"}

def _aggregate_daily_to_3d(daily: list[dict]) -> list[dict]:
    result = []
    for i in range(0, len(daily), 3):
        chunk = daily[i:i+3]
        if len(chunk) < 3:
            continue
        result.append({
            "open_time": chunk[0]["open_time"],
            "open": chunk[0]["open"],
            "high": max(c["high"] for c in chunk),
            "low": min(c["low"] for c in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(c["volume"] for c in chunk),
        })
    return result

def _parse_coingecko_klines(coin_id: str, symbol: str, interval: str = "1d") -> list[dict] | None:
    """CoinGecko OHLC has no volume; default volume to 0."""
    days = COINGECKO_DAYS.get(interval, 30)
    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": days},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        candles = [
            {"open_time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": 0.0}
            for k in data
        ]
        if interval == "3d":
            candles = _aggregate_daily_to_3d(candles)
        return candles[-CANDLE_COUNT:]
    except Exception as e:
        print(f"  [CoinGecko] {symbol} failed: {e}")
        return None

COINGECKO_IDS = {
    "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana", "ARBUSDT": "arbitrum", "LINKUSDT": "chainlink",
    "PAXGUSDT": "pax-gold", "ADAUSDT": "cardano"}

_SOURCE_LIST: list[tuple[str, str | None]] = [
    ("OKX", None),
    ("Binance US", "api.binance.us"),
    ("Binance GCP", "api-gcp.binance.com"),
]
_ACTIVE_SOURCE_IDX = 0

def _build_source_fns(symbol: str, interval: str = "1d", limit: int = CANDLE_COUNT) -> list[tuple[str, callable]]:
    fns: list[tuple[str, callable]] = []
    okx_iv = OKX_INTERVAL_MAP.get(interval, interval)
    fns.append(("OKX", lambda s=symbol, iv=okx_iv, l=limit: _fetch_okx(s, iv, l)))
    cg_id = COINGECKO_IDS.get(symbol)
    if cg_id:
        fns.append(("CoinGecko", lambda s=symbol, c=cg_id, iv=interval: _parse_coingecko_klines(c, s, iv)))
    for name, host in _SOURCE_LIST:
        if name == "OKX":
            continue
        elif host:
            fns.append((name, lambda s=symbol, iv=interval, h=host, l=limit: _fetch_binance(s, iv, h, l)))
        else:
            fns.append((name, lambda s=symbol, iv=interval, l=limit: _fetch_binance(s, iv, limit=l)))
    return fns

def _try_source(
    sources: list[tuple[str, callable]], start: int, symbol: str,
) -> tuple[list[dict], int, str]:
    last_err = ""
    for i in range(start, len(sources)):
        name, fn = sources[i]
        time.sleep(0.5)
        result = fn()
        if result:
            return result, i, ""
        last_err = f"[{name}] {symbol} failed"
    for i in range(0, start):
        name, fn = sources[i]
        time.sleep(0.5)
        result = fn()
        if result:
            return result, i, ""
        last_err = f"[{name}] {symbol} failed"
    return None, start, last_err

def fetch_klines(symbol: str, interval: str = "1d", limit: int = CANDLE_COUNT) -> list[dict[str, float | int]]:
    """Fetch OHLCV klines, trying sources with adaptive fallback."""
    global _ACTIVE_SOURCE_IDX
    sources = _build_source_fns(symbol, interval, limit)
    result, idx, err = _try_source(sources, _ACTIVE_SOURCE_IDX, symbol)
    if result:
        _ACTIVE_SOURCE_IDX = idx
        return result
    raise RuntimeError(f"Cannot fetch klines for {symbol}: {err}")




# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------



def sma(values: list[float], period: int) -> list[float | None]:
    period = int(period)
    result: list[float | None] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1 : i + 1]) / period)
    return result


def compute_atr(candles: list[dict], period: int = 14) -> float:
    period = int(period)
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period


def compute_rsi(closes: list[float], period: int = 14) -> float:
    period = int(period)
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(-diff if diff < 0 else 0.0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    # Wilder's smoothing for subsequent values
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# Trend Engine (3D)
# ---------------------------------------------------------------------------

def _approx_equal(a: float, b: float, threshold: float = 0.005) -> bool:
    """True if |a-b|/max(|a|,|b|) < threshold."""
    denom = max(abs(a), abs(b))
    if denom == 0:
        return True
    return abs(a - b) / denom < threshold


def evaluate_trend_3d(ma7: float, ma10: float, ma20: float) -> tuple[str, int]:
    """Classify trend from 3D MAs. Returns (label, trend_score).

    Scores:
        3 = BULLISH       (MA7 > MA10 > MA20)         — strong uptrend
        2 = WEAK_BULLISH  (MA7 > MA10 ≈ MA20)         — uptrend flattening
        1 = EARLY_BULL    (MA7 > MA10 but MA10 < MA20) — early reversal up
        0 = SIDEWAY       (all MA clustered)
       -1 = EARLY_BEAR    (MA7 < MA10 but MA10 > MA20) — early reversal down
       -2 = WEAK_BEARISH  (MA7 < MA10 ≈ MA20)
       -3 = BEARISH       (MA7 < MA10 < MA20)
    """
    ma_max = max(ma7, ma10, ma20)
    ma_min = min(ma7, ma10, ma20)
    spread = (ma_max - ma_min) / ma_min * 100 if ma_min > 0 else 0

    if spread < 0.5:
        return ("SIDEWAY", 0)

    if ma7 > ma10 > ma20:
        return ("BULLISH", 3)

    if ma7 > ma10 and _approx_equal(ma10, ma20):
        return ("WEAK_BULLISH", 2)

    if ma7 > ma10 and ma10 < ma20:
        return ("EARLY_BULL", 1)

    if ma7 < ma10 and _approx_equal(ma10, ma20):
        return ("WEAK_BEARISH", -2)

    if ma7 < ma10 < ma20:
        return ("BEARISH", -3)

    if ma7 < ma10 and ma10 > ma20:
        return ("EARLY_BEAR", -1)

    return ("SIDEWAY", 0)


def trend_strength(score: int) -> float:
    return {3: 1.0, 2: 0.7, 1: 0.35, 0: 0.0, -1: -0.35, -2: -0.7, -3: -1.0}.get(score, 0.0)


# ---------------------------------------------------------------------------
# Execution Engine (1D)
# ---------------------------------------------------------------------------

def compute_volume_score(volume: float, vol_ma20: float) -> float:
    if vol_ma20 <= 0:
        return 0.2
    ratio = volume / vol_ma20
    if ratio >= 2.0:
        return 1.0
    if ratio >= 1.5:
        return 0.8
    if ratio >= 1.2:
        return 0.6
    if ratio >= 1.0:
        return 0.4
    return 0.2



# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Entry system (v7) — multi-factor quality scoring
# ---------------------------------------------------------------------------

def _entry_score_v7_long(
    trend_score: int,
    close: float,
    ma7_1d: float,
    ma10_1d: float,
    ma20_1d: float,
    ma200_1d: float | None,
    trend_ma_fast_1d: float | None,
    trend_ma_slow_1d: float,
    volume_score: float,
    last_volume: float,
    vol_5d_avg: float,
    rsi_1d: float,
) -> float:
    """Composite entry quality score 0-100. Higher = stronger signal.

    Designed to give partial credit for every condition so the score degrades
    gracefully instead of zeroing out. Only truly bad setups fall below 25.
    """
    sc = 0.0

    # Trend strength (40 pts) — dominant signal, largest factor
    sc += {3: 40, 2: 28, 1: 14, 0: 6}.get(trend_score, 0)

    # MA alignment: fast > slow (12 pts)
    if trend_ma_fast_1d and trend_ma_fast_1d > trend_ma_slow_1d:
        sc += 12
    elif trend_ma_fast_1d:
        sc += 4

    # MA200 direction (12 pts)
    if ma200_1d and close > ma200_1d:
        sc += 12
    elif ma200_1d and close > ma200_1d * 0.92:
        sc += 7
    elif ma200_1d:
        sc += 2
    else:
        sc += 6

    # Pullback proximity (16 pts)
    if ma7_1d > 0:
        dist = abs(close - ma7_1d) / ma7_1d
        if dist <= 0.02:   sc += 16
        elif dist <= 0.04: sc += 12
        elif dist <= 0.06: sc += 8
        elif dist <= 0.10: sc += 4
        else:              sc += 1

    # Volume composite (12 pts)
    if vol_5d_avg > 0 and last_volume > vol_5d_avg:
        sc += 7
    elif vol_5d_avg > 0 and last_volume > vol_5d_avg * 0.7:
        sc += 3
    elif vol_5d_avg > 0:
        sc += 1
    sc += min(volume_score, 1.0) * 5

    # RSI neutral zone (8 pts)
    if 40 <= rsi_1d <= 55:
        sc += 8
    elif 35 <= rsi_1d <= 60:
        sc += 5
    elif rsi_1d <= 70:    sc += 2

    return round(sc, 2)


def _entry_score_v7_short(
    trend_score: int,
    close: float,
    ma7_1d: float,
    ma10_1d: float,
    ma20_1d: float,
    ma200_1d: float | None,
    trend_ma_fast_1d: float | None,
    trend_ma_slow_1d: float,
    volume_score: float,
    last_volume: float,
    vol_5d_avg: float,
    rsi_1d: float,
    candles_12h: list[dict] | None = None,
) -> float:
    """Composite short entry quality score 0-100. Higher = stronger short signal.

    Mirrors _entry_score_v7_long for bearish conditions with short-specific
    enhancements: lower-high pattern detection and overhead resistance scoring.
    """
    sc = 0.0

    # Trend strength (40 pts) — bearish trend dominant signal
    sc += {-3: 40, -2: 28, -1: 14, 0: 6}.get(trend_score, 0)

    # MA alignment: fast < slow = bearish (12 pts)
    if trend_ma_fast_1d and trend_ma_fast_1d < trend_ma_slow_1d:
        sc += 12
    elif trend_ma_fast_1d:
        sc += 4

    # MA200 overhead resistance (12 pts) — price below MA200 = strong bearish
    if ma200_1d and close < ma200_1d:
        sc += 12
    elif ma200_1d and close < ma200_1d * 1.08:
        sc += 7
    elif ma200_1d:
        sc += 2
    else:
        sc += 6

    # Pullback proximity to MA7 from below (16 pts) — bounce rejection
    if ma7_1d > 0:
        dist = abs(close - ma7_1d) / ma7_1d
        if dist <= 0.02:   sc += 16
        elif dist <= 0.04: sc += 12
        elif dist <= 0.06: sc += 8
        elif dist <= 0.10: sc += 4
        else:              sc += 1

    # Volume composite (12 pts) — selling pressure confirmation
    if vol_5d_avg > 0 and last_volume > vol_5d_avg:
        sc += 7
    elif vol_5d_avg > 0 and last_volume > vol_5d_avg * 0.7:
        sc += 3
    elif vol_5d_avg > 0:
        sc += 1
    sc += min(volume_score, 1.0) * 5

    # RSI neutral-bearish zone (8 pts) — not oversold, room to fall
    if 45 <= rsi_1d <= 60:
        sc += 8
    elif 40 <= rsi_1d <= 65:
        sc += 5
    elif rsi_1d >= 30:    sc += 2

    return round(sc, 2)


# ---------------------------------------------------------------------------
# Entry system (v6) — RSI pullback within trend
# ---------------------------------------------------------------------------

def compute_entry_v6_long(
    trend_score: int,
    rsi_1d: float,
    close: float,
    ma20_1d: float,
    trend_ma_slow_1d: float,
    trend_ma_fast_1d: float | None,
    volume_score: float,
    trend_min: int = 0,
    vol_min: float = 0.3,
    rsi_max: float = 55,
    # ── v7 enhanced params ──
    ma7_1d: float | None = None,
    ma200_1d: float | None = None,
    last_volume: float = 0,
    vol_5d_avg: float = 0,
    use_ma200_filter: bool = False,
    use_pullback_filter: bool = False,
    use_volume_expan: bool = False,
    min_entry_score: float = 0,
) -> bool:
    """Entry signal for LONG: uptrend + price above MA20 + RSI not overbought.

    v7: optional MA200 gate, pullback-to-MA7, volume expansion, and quality score.
    """
    if trend_score < trend_min:
        return False
    if rsi_1d > rsi_max:
        return False
    if trend_ma_fast_1d is not None and trend_ma_fast_1d < trend_ma_slow_1d:
        return False
    if close < ma20_1d:
        return False
    if close < trend_ma_slow_1d:
        return False
    if volume_score < vol_min:
        return False

    # ── v7: MA200 direction gate ──
    if use_ma200_filter and ma200_1d is not None and close < ma200_1d:
        return False

    # ── v7: Pullback gate (enter within 3% of MA7) ──
    if use_pullback_filter and ma7_1d and ma7_1d > 0:
        if abs(close - ma7_1d) / ma7_1d > 0.03:
            return False

    # ── v7: Volume expansion gate ──
    if use_volume_expan and vol_5d_avg > 0 and last_volume < vol_5d_avg:
        return False

    # ── v7: Entry quality score gate ──
    if min_entry_score > 0 and ma7_1d:
        sc = _entry_score_v7_long(
            trend_score, close, ma7_1d, ma20_1d, ma20_1d, ma200_1d,
            trend_ma_fast_1d, trend_ma_slow_1d, volume_score,
            last_volume, vol_5d_avg, rsi_1d,
        )
        if sc < min_entry_score:
            return False

    return True


def compute_entry_v6_short(
    trend_score: int,
    rsi_1d: float,
    close: float,
    ma20_1d: float,
    trend_ma_slow_1d: float,
    trend_ma_fast_1d: float | None,
    volume_score: float,
    trend_max: int = -3,
    vol_min: float = 0.3,
    rsi_min: float = 45,
    ma7_1d: float | None = None,
    ma10_1d: float | None = None,
    ma200_1d: float | None = None,
    last_volume: float = 0,
    vol_5d_avg: float = 0,
    use_ma200_filter: bool = False,
    use_pullback_filter: bool = False,
    use_volume_expan: bool = False,
    min_entry_score: float = 0,
    candles_12h: list[dict] | None = None,
) -> bool:
    """Entry signal for SHORT: bear trend + price below MA20 + RSI not oversold.

    v7: optional MA200 gate, pullback-to-MA7, volume expansion, and quality score.
    """
    if trend_score > trend_max:
        return False
    if rsi_1d < rsi_min:
        return False
    if trend_ma_fast_1d is not None and trend_ma_fast_1d > trend_ma_slow_1d:
        return False
    if close > ma20_1d:
        return False
    if close > trend_ma_slow_1d:
        return False
    if volume_score < vol_min:
        return False

    if use_ma200_filter and ma200_1d is not None and close > ma200_1d:
        return False

    if use_pullback_filter and ma7_1d and ma7_1d > 0:
        if abs(close - ma7_1d) / ma7_1d > 0.03:
            return False

    if use_volume_expan and vol_5d_avg > 0 and last_volume < vol_5d_avg:
        return False

    if min_entry_score > 0 and ma7_1d:
        sc = _entry_score_v7_short(
            trend_score, close, ma7_1d, ma10_1d or ma20_1d, ma20_1d, ma200_1d,
            trend_ma_fast_1d, trend_ma_slow_1d, volume_score,
            last_volume, vol_5d_avg, rsi_1d, candles_12h,
        )
        if sc < min_entry_score:
            return False

    return True



def resolve_action_v6(
    trend_score: int,
    entry_long: bool,
    entry_short: bool,
    prev_pos_state: str,
    current_price: float | None = None,
    last_entry_price: float | None = None,
    leverage: float = 3.0,
    deployed_margin_pct: float = 0.0,
    snowball_pnl_min: float = 0.03,
) -> tuple[str, str]:
    """State machine — snowball on winning positions.

    - FLAT → ENTRY_1 on signal
    - ENTRY_N → ENTRY_N+1 if PnL from LAST entry > snowball_pnl_min (3% price move)
    - Max 2 snowball adds
    """
    if prev_pos_state == "FLAT":
        if entry_long:
            return ("LONG_ENTRY_1", "OPEN_LONG_ENTRY_1")
        if entry_short:
            return ("SHORT_ENTRY_1", "OPEN_SHORT_ENTRY_1")
        return ("FLAT", "NO_TRADE")


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def check_kill_switch(btc_candles: list[dict]) -> bool:
    if len(btc_candles) < 2:
        return False

    prev_close = btc_candles[-2]["close"]
    curr_close = btc_candles[-1]["close"]
    change_pct = (curr_close - prev_close) / prev_close * 100

    if change_pct <= BTC_FLASH_CRASH_PCT:
        return True

    volumes = [c["volume"] for c in btc_candles]
    vol_ma20 = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0

    if change_pct <= -3.0 and vol_ma20 > 0:
        vol_ratio = btc_candles[-1]["volume"] / vol_ma20
        if vol_ratio > 5.0:
            return True

    return False


# ---------------------------------------------------------------------------
# Firestore state persistence
# ---------------------------------------------------------------------------

def _get_db():
    if not is_firebase_enabled():
        return None
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        sa = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
        cred = credentials.Certificate(sa)
        firebase_admin.initialize_app(cred)
    return firestore.client()


def load_state(coin: str) -> dict:
    """Load saved position state from Firestore."""
    db = _get_db()
    if db is None:
        return {"position_state": "FLAT", "last_action": "",
                "entry_price": None, "remaining_size": 1.0}
    try:
        doc = call_with_retry(
            lambda: db.collection(FIRESTORE_COLLECTION).document(coin).get(),
            resource_name=f"Firestore load {coin} state",
        )
        if doc.exists:
            return doc.to_dict()
    except Exception as exc:
        print(f"[crypto_trading] Warning: could not load state for {coin}: {exc}",
              file=sys.stderr)
    return {"position_state": "FLAT", "last_action": ""}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _signal_icon(result: dict) -> str:
    act = result["action"]
    if act in ("EXIT_LONG", "EXIT_SHORT", "KILL_SWITCH"):
        return "❗❗❗"
    if act in ("REDUCE_LONG", "REDUCE_SHORT",
               "OVER_EXTEND_LONG", "OVER_EXTEND_SHORT"):
        return "🟡"
    if "TAKE_PROFIT" in act:
        return "💰"
    if "LONG" in act:
        return "💚"
    if "SHORT" in act:
        return "🔴"
    return "🟡"


def compute_next_rules(position_state: str) -> list[str]:
    rules: list[str] = []
    if position_state == "FLAT":
        rules.append("OPEN_LONG if TrendScore >= +2 and RSI_1D < 45 near MA20")
        rules.append("OPEN_SHORT if TrendScore <= -2 and RSI_1D > 55 near MA20")
        return rules
    if position_state.startswith("LONG"):
        rules.append("Trailing stop active | EXIT if trend reversal (MA7 < MA20)")
        rules.append("EXIT if TrendScore < 0")
    elif position_state.startswith("SHORT"):
        rules.append("Trailing stop active | EXIT if trend reversal (MA7 > MA20)")
        rules.append("EXIT if TrendScore > 0")
    return rules


def _action_text(result: dict) -> str:
    a = result["action"]
    z = result.get("entry_zone", {})
    price = z.get("optimal_entry") or z.get("current_price", "?")

    if a == "KILL_SWITCH": return "Emergency exit (kill switch)"
    if a == "NO_TRADE": return "No action \u2013 wait for setup"
    if a == "HOLD": return "Hold current position"
    if a == "EXIT_LONG": return "Exit all LONG position"
    if a == "EXIT_SHORT": return "Exit all SHORT position"
    if a == "REDUCE_LONG": return "Reduce 50% LONG position"
    if a == "REDUCE_SHORT": return "Reduce 50% SHORT position"
    if a == "OPEN_LONG_ENTRY_1": return f"Open LONG Entry 1 at ${price}"
    if a == "OPEN_SHORT_ENTRY_1": return f"Open SHORT Entry 1 at ${price}"
    if a == "ADD_LONG_ENTRY_2": return f"Add LONG Entry 2 at ${price}"
    if a == "ADD_SHORT_ENTRY_2": return f"Add SHORT Entry 2 at ${price}"
    if a == "ADD_LONG_ENTRY_3": return f"Add LONG Entry 3 at ${price}"
    if a == "ADD_SHORT_ENTRY_3": return f"Add SHORT Entry 3 at ${price}"

    if a == "TAKE_PROFIT_1_LONG": return "TP1: reduce 30% LONG"
    if a == "TAKE_PROFIT_1_SHORT": return "TP1: reduce 30% SHORT"
    if a == "TAKE_PROFIT_2_LONG": return "TP2: reduce 30% LONG"
    if a == "TAKE_PROFIT_2_SHORT": return "TP2: reduce 30% SHORT"
    if a == "OVER_EXTEND_LONG": return "Over-extension: reduce 25% LONG"
    if a == "OVER_EXTEND_SHORT": return "Over-extension: reduce 25% SHORT"

    return a


# ---------------------------------------------------------------------------
# Per-coin analysis pipeline
# ---------------------------------------------------------------------------

def analyse_coin(
    coin: str,
    candles_12h: list[dict],
    kill_switch_active: bool,
    active_count: int = 0,
    max_positions: int = MAX_CONCURRENT_POSITIONS,
    in_event_window: bool = False,
) -> dict:
    ts = _now_vnt().isoformat()
    profile = get_coin_profile(coin)

    # Per-coin regime detection (not BTC-based)
    # Each coin has its own bull/bear regime based on MA50 vs MA120 (12h raw)
    closes_12h_temp = [c["close"] for c in candles_12h]
    ma50_temp_all = sma(closes_12h_temp, 50)
    ma120_temp_all = sma(closes_12h_temp, 120)
    ma50_temp = ma50_temp_all[-1] if ma50_temp_all[-1] is not None else closes_12h_temp[-1]
    ma120_temp = ma120_temp_all[-1] if ma120_temp_all[-1] is not None else closes_12h_temp[-1]
    
    cfg = COIN_CONFIG.get(coin, COIN_CONFIG["ETH"])
    _coin_bull = ma50_temp > ma120_temp
    buf = cfg.get("ma_buffer", 0)
    if buf:
        _coin_bull = ma50_temp > ma120_temp * (1 + buf)
    _bear_mode = not _coin_bull

    # Aggregate 2×12h → 24h candles for trend engine
    candles_24h = []
    for i in range(0, len(candles_12h) - 1, 2):
        b = candles_12h[i:i + 2]
        candles_24h.append({
            "open_time": b[0]["open_time"], "open": b[0]["open"],
            "high": max(d["high"] for d in b),
            "low": min(d["low"] for d in b),
            "close": b[-1]["close"],
            "volume": sum(d["volume"] for d in b),
        })

    # --- Trend Engine (24h) ---
    closes_24h = [c["close"] for c in candles_24h]

    ma_f_24h_all = sma(closes_24h, TREND_MA_FAST)
    ma_m_24h_all = sma(closes_24h, TREND_MA_MID)
    ma_s_24h_all = sma(closes_24h, TREND_MA_SLOW)

    ma_f_24h = ma_f_24h_all[-1] if ma_f_24h_all[-1] is not None else closes_24h[-1]
    ma_m_24h = ma_m_24h_all[-1] if ma_m_24h_all[-1] is not None else closes_24h[-1]
    ma_s_24h = ma_s_24h_all[-1] if ma_s_24h_all[-1] is not None else closes_24h[-1]

    trend_label, trend_score = evaluate_trend_3d(ma_f_24h, ma_m_24h, ma_s_24h)
    ts_val = trend_strength(trend_score)

    # 24h RSI for exit system
    rsi_24h = compute_rsi(closes_24h, 14)

    # --- Execution Engine (12h) ---
    closes_12h = [c["close"] for c in candles_12h]
    highs_12h = [c["high"] for c in candles_12h]
    lows_12h = [c["low"] for c in candles_12h]
    volumes_12h = [c["volume"] for c in candles_12h]

    # MA periods: SF-scaled for 12h equivalents
    ma3_12h_all = sma(closes_12h, 3 * SF)
    ma5_12h_all = sma(closes_12h, 5 * SF)
    ma7_12h_all = sma(closes_12h, 7 * SF)
    ma10_12h_all = sma(closes_12h, 10 * SF)
    vol_ma20_12h_all = sma(volumes_12h, 20 * SF)

    ma3_12h = ma3_12h_all[-1] if ma3_12h_all[-1] is not None else closes_12h[-1]
    ma5_12h = ma5_12h_all[-1] if ma5_12h_all[-1] is not None else closes_12h[-1]
    ma7_12h = ma7_12h_all[-1] if ma7_12h_all[-1] is not None else closes_12h[-1]
    ma10_12h = ma10_12h_all[-1] if ma10_12h_all[-1] is not None else closes_12h[-1]
    vol_ma20_12h = vol_ma20_12h_all[-1] if vol_ma20_12h_all[-1] is not None else volumes_12h[-1]

    last_close = closes_12h[-1]
    last_low = lows_12h[-1]
    last_high = highs_12h[-1]
    last_volume = volumes_12h[-1]

    # v7 indicators
    rsi_12h = compute_rsi(closes_12h, 14 * SF)
    ma20_12h_all = sma(closes_12h, 20 * SF)
    ma50_12h_all = sma(closes_12h, 50 * SF)
    ma20_12h = ma20_12h_all[-1] if ma20_12h_all[-1] is not None else last_close
    ma50_12h = ma50_12h_all[-1] if ma50_12h_all[-1] is not None else last_close
    exec_f = (sma(closes_12h, EXEC_MA_FAST)[-1] or None)
    exec_m = (sma(closes_12h, EXEC_MA_MID)[-1] or ma50_12h)
    exec_s = (sma(closes_12h, EXEC_MA_SLOW)[-1] or ma50_12h)
    ma200_12h_all = sma(closes_12h, 200 * SF)
    ma200_12h = ma200_12h_all[-1] if ma200_12h_all[-1] is not None else None
    recent_10d_low = min(lows_12h[-int(10 * SF):]) if len(lows_12h) >= 10 * SF else last_close * 0.95
    recent_10d_high = max(highs_12h[-int(10 * SF):]) if len(highs_12h) >= 10 * SF else last_close * 1.05

    atr_12h = compute_atr(candles_12h, 14 * SF)
    _atr_period = int(14 * SF)
    atrs_12h = [compute_atr(candles_12h[:i + 1], _atr_period) for i in range(_atr_period, len(candles_12h))]
    atr_ma20_12h_all = sma(atrs_12h, 20 * SF)
    atr_ma20_12h = atr_ma20_12h_all[-1] if atr_ma20_12h_all[-1] is not None else atr_12h

    volume_score = compute_volume_score(last_volume, vol_ma20_12h)

    # v7: volume 5d average for expansion filter
    vol_5d_avg = sum(volumes_12h[-int(5 * SF):]) / int(5 * SF) if len(volumes_12h) >= int(5 * SF) else last_volume

    # v6 entry signals (per-coin profile)
    entry_long = compute_entry_v6_long(
        trend_score, rsi_12h, last_close, exec_s, exec_m, exec_f, volume_score,
        trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
        rsi_max=profile.get("rsi_max_long", 55),
        # v7 enhanced
        ma7_1d=ma7_12h, ma200_1d=ma200_12h,
        last_volume=last_volume, vol_5d_avg=vol_5d_avg,
        use_ma200_filter=profile.get("use_ma200_filter", False),
        use_pullback_filter=profile.get("use_pullback_filter", False),
        use_volume_expan=profile.get("use_volume_expan", False),
        min_entry_score=profile.get("min_entry_score", 0),
    )
    entry_short = (
        compute_entry_v6_short(
            trend_score, rsi_12h, last_close, exec_s, exec_m, exec_f, volume_score,
            trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
            rsi_min=profile.get("rsi_min_short", 45),
        ) if coin in SHORT_ALLOWED else False
    )

    # ── v9 Isolated Entry Engine ──────────────────────────────────────
    prev = load_state(coin)
    entries: list[dict] = prev.get("entries", [])
    coin_lev = _coin_lev(coin)
    sl_roi = _coin_sl_roi(coin)
    trail_rate = _coin_trail(coin)
    cd_bars = ENTRY_COOLDOWN_BARS.get(coin, 0)
    last_entry_ts = prev.get("last_entry_ts", 0)
    consec_l = prev.get("consec_losses_long", 0)
    consec_s = prev.get("consec_losses_short", 0)
    cd_l_until = prev.get("cooldown_long_until", "")
    cd_s_until = prev.get("cooldown_short_until", "")
    # 3SL Rolling lock (separated per direction)
    rolling_sl_long = prev.get("rolling_sl_long", 0)
    rolling_sl_short = prev.get("rolling_sl_short", 0)
    rolling_lock_until_long = prev.get("rolling_lock_until_long", "")
    rolling_lock_until_short = prev.get("rolling_lock_until_short", "")

    if kill_switch_active:
        db2 = _get_db()
        if db2:
            try:
                db2.collection(FIRESTORE_COLLECTION).document(coin).set({
                    "entries": [], "position_state": "FLAT", "timestamp": ts,
                })
            except Exception: pass
        return {
            "coin": coin, "trend": trend_label, "trend_score": trend_score,
            "entry2_prob": 0.0, "entry3_prob": 0.0,
            "position_state": "FLAT", "action": "KILL_SWITCH",
            "leverage": coin_lev, "entry_zone": {"current_price": last_close},
            "volume_score": volume_score, "reaction_score": 0.0,
            "atr_score": 0.0, "break_score": 0.0,
            "next_rules": ["Kill switch active"],
            "timestamp": ts, "pnl_pct": 0.0, "remaining_size": 0.0,
        }

    new_entries = []
    exit_reasons = []
    total_pnl = 0.0
    entry_action = "HOLD"
    now_ts = int(datetime.fromisoformat(ts).timestamp()) if ts else 0

    tot_cap = BASE * _coin_cap(coin)

    for ent in entries:
        ep = ent.get("entry_price", 0)
        mp = ent.get("margin_pct", 0.07)
        is_sh = ent.get("is_short", False)
        tp_s = ent.get("tp_stage", 0)
        rem = ent.get("remaining_size", 1.0)
        hi = ent.get("highest_since_entry", ep)
        tstop = ent.get("trailing_stop")

        if ep <= 0:
            continue

        if not is_sh:
            pnl_pct_entry = (last_close - ep) / ep * 100
        else:
            pnl_pct_entry = (ep - last_close) / ep * 100
        ent_lev = ent.get("lev", coin_lev)
        roi = pnl_pct_entry * mp * tot_cap * ent_lev / BASE

        if not is_sh and last_close > hi:
            hi = last_close
        if is_sh and last_close < hi:
            hi = last_close
        ent["highest_since_entry"] = hi

        removed = False
        ent_is_bull_long = ent_lev > 2.5 and not is_sh  # bull long: classified by entry leverage

        # ── BULL mode: staggered TP + trailing (matches backtest) ──
        if ent_is_bull_long and BULL_NO_SL:
            if roi <= -BULL_MAX_LOSS * 100:
                total_pnl += roi * rem / 100
                exit_reasons.append(f"Bull Max Loss: ROI {roi:.1f}%")
                removed = True
            elif not removed:
                tp_s = ent.get("tp_stage", 0)
                if tp_s < len(BULL_TP_SCHEDULE):
                    trg, cf_pct = BULL_TP_SCHEDULE[tp_s]
                    if roi >= trg:
                        cf = cf_pct * rem
                        total_pnl += roi * cf / 100
                        rem -= cf; ent["remaining_size"] = rem
                        ent["tp_stage"] = tp_s + 1
                        exit_reasons.append(f"Bull TP: ROI {roi:.1f}%")
                        if rem <= 0.001: removed = True
                if tp_s >= len(BULL_TP_SCHEDULE) and not removed:
                    pnl_from_entry = (last_close - ep) / ep
                    trail_cd_until = ent.get("trail_cooldown_until", 0)
                    in_trail_cd = isinstance(trail_cd_until, str) or trail_cd_until > now_ts
                    if pnl_from_entry >= BULL_TRAIL_ACTIVATION and not in_trail_cd:
                        tstop = max(ent.get("trailing_stop") or last_close * (1 - BULL_TRAIL_DISTANCE), hi * (1 - BULL_TRAIL_DISTANCE))
                        ent["trailing_stop"] = tstop
                        if last_close <= tstop:
                            cf = BULL_TRAIL_CLOSE * rem
                            total_pnl += roi * cf / 100
                            rem -= cf; ent["remaining_size"] = rem
                            exit_reasons.append(f"Bull Trail: closed {BULL_TRAIL_CLOSE*100:.0f}%")
                            ent["trailing_stop"] = last_close * (1 - BULL_TRAIL_DISTANCE)
                            ent["trail_cooldown_until"] = (_now_vnt() + timedelta(hours=BULL_TRAIL_COOLDOWN_BARS * 12)).isoformat()
                            if rem <= 0.001: removed = True
                # Regime change exit for bull longs
                if not removed and not _coin_bull:
                    total_pnl += roi * rem / 100
                    exit_reasons.append("Bull regime exit")
                    removed = True

        # ── BEAR mode: standard SL + TP + trail ──
        else:
            # Stop loss (ROI-based, uses entry-specific SL)
            ent_sl = ent.get("sl_roi", sl_roi)
            if roi <= -ent_sl:
                total_pnl += roi * rem / 100
                exit_reasons.append(f"SL: ROI {roi:.1f}% <= -{ent_sl}%")
                removed = True

            # Partial TP
            elif tp_s < len(TP_SCHEDULE):
                target_roi, close_pct = TP_SCHEDULE[tp_s]
                if roi >= target_roi:
                    cf = close_pct * rem
                    total_pnl += roi * cf / 100
                    rem -= cf
                    ent["remaining_size"] = rem
                    ent["tp_stage"] = tp_s + 1
                    exit_reasons.append(f"TP{tp_s + 1}: ROI {roi:.1f}%")
                    if ent["tp_stage"] >= len(TP_SCHEDULE):
                        ent["trailing_stop"] = last_close * (1 - trail_rate) if not is_sh else last_close * (1 + trail_rate)

            # Trailing stop (after all TPs)
            if tp_s >= len(TP_SCHEDULE) and not removed:
                if tstop is None:
                    tstop = last_close * (1 - trail_rate) if not is_sh else last_close * (1 + trail_rate)
                if not is_sh:
                    tstop = max(tstop, hi * (1 - trail_rate))
                else:
                    tstop = min(tstop, hi * (1 + trail_rate))
                ent["trailing_stop"] = tstop
                if (not is_sh and last_close <= tstop) or (is_sh and last_close >= tstop):
                    total_pnl += roi * rem / 100
                    exit_reasons.append(f"Trail: {last_close:.2f} <= {tstop:.2f}")
                    removed = True

        # Trend reversal exit (BEAR mode + shorts + bull longs as safety)
        if is_sh and not removed and trend_score >= 2:
            total_pnl += roi * rem / 100
            exit_reasons.append(f"Short trend reversal: score {trend_score:+d}, ROI {roi:.1f}%")
            removed = True

        # Trend reversal exit: close longs when trend turns bearish (BEAR mode only)
        if not is_sh and not removed and not ent_is_bull_long and trend_score <= -2:
            total_pnl += roi * rem / 100
            exit_reasons.append(f"Long trend reversal: score {trend_score:+d}, ROI {roi:.1f}%")
            removed = True

        if removed:
            if roi < 0:
                # Direction-specific cooldown (shift=0: 2→3, 3→5, 4→8, 5→13)
                if is_sh:
                    consec_s += 1
                    cd_bars_fib = _fib_cooldown_bars(consec_s, 0)
                    if cd_bars_fib > 0:
                        cd_s_until = (_now_vnt() + timedelta(hours=cd_bars_fib * 12)).isoformat()
                else:
                    consec_l += 1
                    cd_bars_fib = _fib_cooldown_bars(consec_l, 0)
                    if cd_bars_fib > 0:
                        cd_l_until = (_now_vnt() + timedelta(hours=cd_bars_fib * 12)).isoformat()
                
                # 3SL Rolling Fibonacci Lock (separated per direction)
                if is_sh:
                    rolling_sl_short += 1
                    if rolling_sl_short >= SL_ROLLING_CAP:
                        lock_bars = SL_ROLLING_LOCK_BARS
                        if SL_ROLLING_FIB:
                            extra = rolling_sl_short - SL_ROLLING_CAP
                            lock_bars = _fib_cooldown_bars(SL_ROLLING_CAP + extra, 0)
                        rolling_lock_until_short = (_now_vnt() + timedelta(hours=lock_bars * 12)).isoformat()
                else:
                    rolling_sl_long += 1
                    if rolling_sl_long >= SL_ROLLING_CAP:
                        lock_bars = SL_ROLLING_LOCK_BARS
                        if SL_ROLLING_FIB:
                            extra = rolling_sl_long - SL_ROLLING_CAP
                            lock_bars = _fib_cooldown_bars(SL_ROLLING_CAP + extra, 0)
                        rolling_lock_until_long = (_now_vnt() + timedelta(hours=lock_bars * 12)).isoformat()
            else:
                # Win resets all counters
                if is_sh:
                    consec_s = 0
                    rolling_sl_short = 0
                else:
                    consec_l = 0
                    rolling_sl_long = 0

        if not removed:
            new_entries.append(ent)

    entries = new_entries

    # Check for new entry — direction-specific cooldown
    deployed = sum(e.get("margin_pct", 0) for e in entries)
    max_margin_pct = MAX_PER_COIN_PCT  # flat cap
    # Adjust cap for leverage to maintain risk parity
    profile_for_cap = get_profile(coin, _coin_bull)
    max_margin_pct = MAX_PER_COIN_PCT / profile_for_cap["lev"] * profile_for_cap["pos_mult"]
    can_enter_base = deployed < max_margin_pct

    # Direction-specific Fibonacci cooldown: LONG cooldown blocks LONG only, SHORT blocks SHORT only
    can_enter_long = can_enter_base
    if can_enter_long and cd_l_until:
        try:
            if datetime.fromisoformat(cd_l_until) > _now_vnt():
                can_enter_long = False
        except Exception: pass

    can_enter_short = can_enter_base
    if can_enter_short and cd_s_until:
        try:
            if datetime.fromisoformat(cd_s_until) > _now_vnt():
                can_enter_short = False
        except Exception: pass
    
    # 3SL Rolling Fibonacci Lock (separated per direction)
    if can_enter_long and rolling_lock_until_long:
        try:
            if datetime.fromisoformat(rolling_lock_until_long) > _now_vnt():
                can_enter_long = False
        except Exception: pass
    
    if can_enter_short and rolling_lock_until_short:
        try:
            if datetime.fromisoformat(rolling_lock_until_short) > _now_vnt():
                can_enter_short = False
        except Exception: pass
    
    # Sideway filter: skip entry if sideway_score > SIDEWAY_MAX_SCORE
    if can_enter_long or can_enter_short:
        sideway_score = compute_sideway_score(candles_12h, SF)
        if sideway_score > SIDEWAY_MAX_SCORE:
            can_enter_long = False
            can_enter_short = False
        adx_val = compute_adx(candles_12h, int(14*SF))
        if adx_val < cfg["adx_min"]:
            can_enter_long = False
            can_enter_short = False
    
    # TRX: go to cash in bear (no short, no entry)
    if coin == "TRX" and not _coin_bull and not cfg["bear_short"]:
        can_enter_long = False
        can_enter_short = False

    if can_enter_long or can_enter_short:
        el = compute_entry_v6_long(
            trend_score, rsi_12h, last_close, exec_s, exec_m, exec_f, volume_score,
            trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
            rsi_max=profile.get("rsi_max_long", 90),
            ma7_1d=ma7_12h, ma200_1d=ma200_12h,
            last_volume=last_volume, vol_5d_avg=vol_5d_avg,
            use_ma200_filter=False, use_pullback_filter=False,
            use_volume_expan=False, min_entry_score=cfg["entry_score"],
        ) if can_enter_long else False
        es = compute_entry_v6_short(
            trend_score, rsi_12h, last_close, exec_s, exec_m, exec_f, volume_score,
            trend_max=profile.get("trend_max_short", -2), vol_min=profile["vol_min"],
            rsi_min=profile.get("rsi_min_short", 10),
            ma7_1d=ma7_12h, ma10_1d=ma10_12h, ma200_1d=ma200_12h,
            last_volume=last_volume, vol_5d_avg=vol_5d_avg,
            use_ma200_filter=False, use_pullback_filter=False,
            use_volume_expan=False,
            min_entry_score=profile.get("short_min_entry_score", ENTRY_MIN_SCORE),
            candles_12h=candles_12h,
        ) if (coin in SHORT_ALLOWED and can_enter_short) else False

        has_active_longs = any(not e.get("is_short", False) for e in entries)
        has_active_shorts = any(e.get("is_short", False) for e in entries)

        # ── BULL Snowball: add to existing bull long ──
        snowball_added = False
        if _coin_bull and el and has_active_longs and not has_active_shorts:
            sc_snow = _entry_score_v7_long(
                trend_score, last_close, ma7_12h, ma10_12h, exec_s, ma200_12h,
                exec_f, exec_m, volume_score, last_volume, vol_5d_avg, rsi_12h,
            )
            if sc_snow >= cfg["snowball_min_score"]:
                for ent in entries:
                    if ent.get("is_short", False): continue
                    ent_ep = ent.get("entry_price", 0)
                    if ent_ep <= 0: continue
                    pnl_from_last = (last_close - ent_ep) / ent_ep
                    sb_stage = ent.get("snowball_stage", 0)
                    if sb_stage < len(BULL_SNOWBALL_LEVELS):
                        if pnl_from_last >= BULL_SNOWBALL_LEVELS[sb_stage]:
                            add_mp = BULL_SNOWBALL_SIZES[sb_stage + 1] if sb_stage + 1 < len(BULL_SNOWBALL_SIZES) else BULL_INITIAL_SIZE
                            profile = get_profile(coin, _coin_bull)
                            if deployed + add_mp <= max_margin_pct + 0.001:
                                entries.append({
                                    "entry_price": last_close,
                                    "margin_pct": add_mp,
                                    "is_short": False,
                                    "tp_stage": 0,
                                    "remaining_size": 1.0,
                                    "highest_since_entry": last_close,
                                    "trailing_stop": None,
                                    "lev": profile["lev"],
                                    "sl_roi": profile["sl"],
                                    "snowball_stage": sb_stage + 1,
                                    "is_snowball": True,
                                })
                                entry_action = "ADD_LONG_SNOWBALL"
                                last_entry_ts = now_ts
                                snowball_added = True
                            break

        ps_, act = resolve_action_v6(trend_score, el, es, "FLAT")
        if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
            is_sh = act.startswith("OPEN_SHORT")
            # Skip new entry if snowball already added (bull mode)
            if _coin_bull and not is_sh and snowball_added:
                pass
            elif (is_sh and has_active_longs) or (not is_sh and has_active_shorts):
                pass
            else:
                if is_sh:
                    sc = _entry_score_v7_short(
                        trend_score, last_close, ma7_12h, ma10_12h, exec_s, ma200_12h,
                        exec_f, exec_m, volume_score, last_volume, vol_5d_avg, rsi_12h,
                        candles_12h,
                    )
                else:
                    sc = _entry_score_v7_long(
                        trend_score, last_close, ma7_12h, ma10_12h, exec_s, ma200_12h,
                        exec_f, exec_m, volume_score, last_volume, vol_5d_avg, rsi_12h,
                    )
                strong = sc >= cfg["entry_score"]
                
                # Get HYBRID profile based on market regime
                profile = get_profile(coin, _coin_bull)
                
                # Apply profile parameters
                if _coin_bull and not is_sh:
                    mp = BULL_INITIAL_SIZE  # fixed snowball entry size
                    profile_lev = 3.5  # BULL leverage
                    profile_sl = 12  # not used (no SL in bull)
                else:
                    mp = profile["initial_exposure"] * profile["pos_mult"]
                    if strong: mp *= 1.0
                    else: mp *= 0.7
                    profile_lev = profile["lev"]
                    profile_sl = 12 if coin == "TRX" else profile["sl"]  # TRX wider SL
                
                if deployed + mp <= max_margin_pct + 0.001:
                    entries.append({
                        "entry_price": last_close,
                        "margin_pct": mp,
                        "is_short": is_sh,
                        "tp_stage": 0,
                        "remaining_size": 1.0,
                        "highest_since_entry": last_close,
                        "trailing_stop": None,
                        "lev": profile_lev,
                        "sl_roi": profile_sl,
                    })
                    entry_action = "OPEN_LONG_ENTRY_1" if not is_sh else "OPEN_SHORT_ENTRY_1"
                    last_entry_ts = now_ts

    # Determine overall action
    if exit_reasons:
        has_long = any(not e.get("is_short") for e in entries)
        has_short = any(e.get("is_short") for e in entries)
        if has_long and has_short:
            action = "EXIT_ALL"
        elif has_short:
            action = "EXIT_SHORT"
        else:
            action = "EXIT_LONG"
        pos_state = "FLAT"
        next_rules = exit_reasons
        remaining_size = 0.0
    elif entry_action not in ("HOLD",):
        action = entry_action
        pos_state = "LONG_ENTRY_1" if "LONG" in entry_action else "SHORT_ENTRY_1"
        next_rules = compute_next_rules(pos_state)
        remaining_size = sum(e.get("margin_pct", 0.07) for e in entries)
    else:
        if entries:
            action = "HOLD"
            pos_state = "LONG_ENTRY_1" if not entries[0].get("is_short") else "SHORT_ENTRY_1"
            next_rules = [f"{len(entries)} active entries, deployed={deployed*100:.0f}%"]
        else:
            action = "NO_TRADE"
            pos_state = "FLAT"
            next_rules = ["Waiting for strong signal (score >= 65)"]
        remaining_size = sum(e.get("remaining_size", 0) for e in entries)

    output = {
        "coin": coin, "trend": trend_label, "trend_score": trend_score,
        "regime": "BULL" if _coin_bull else "BEAR",  # Per-coin regime
        "entry2_prob": 0.0, "entry3_prob": 0.0,
        "position_state": pos_state, "action": action,
        "leverage": coin_lev, "entry_zone": {"current_price": last_close},
        "volume_score": volume_score, "reaction_score": 0.0,
        "atr_score": 0.0, "break_score": 0.0,
        "next_rules": next_rules, "timestamp": ts,
        "pnl_pct": round(total_pnl, 2), "remaining_size": remaining_size,
    }

    # Save state with entries list
    db2 = _get_db()
    if db2:
        try:
            db2.collection(FIRESTORE_COLLECTION).document(coin).set({
                "entries": entries,
                "position_state": pos_state,
                "timestamp": ts,
                "last_entry_ts": last_entry_ts,
                "consec_losses_long": consec_l,
                "consec_losses_short": consec_s,
                "cooldown_long_until": cd_l_until,
                "cooldown_short_until": cd_s_until,
                # 3SL Rolling lock (separated per direction)
                "rolling_sl_long": rolling_sl_long,
                "rolling_sl_short": rolling_sl_short,
                "rolling_lock_until_long": rolling_lock_until_long,
                "rolling_lock_until_short": rolling_lock_until_short,
            })
        except Exception as exc:
            print(f"[crypto_trading] Warning: could not save state for {coin}: {exc}", file=sys.stderr)

    return output


# ---------------------------------------------------------------------------
# OKX order execution helpers
# ---------------------------------------------------------------------------

_OKX_SETUP_DONE = False


def _ensure_okx_setup(instrument_map: dict) -> None:
    global _OKX_SETUP_DONE
    if _OKX_SETUP_DONE:
        return
    for coin in COINS:
        inst_id = OKX_INSTRUMENTS.get(coin)
        if inst_id and inst_id in instrument_map:
            profile = get_coin_profile(coin)
            okx_set_leverage(inst_id, profile["leverage"])
    _OKX_SETUP_DONE = True


def _exec_action_on_okx(
    result: dict,
    instrument_map: dict,
    skipped_instruments: dict,
    positions: list,
    equity_usd: float,
) -> dict:
    """Execute a single action on OKX. Returns execution result dict."""
    coin = result["coin"]
    action = result["action"]
    inst_id = OKX_INSTRUMENTS.get(coin)
    if not inst_id:
        return {"coin": coin, "status": "skip", "detail": "no instrument"}
    if inst_id in skipped_instruments:
        detail = f"cannot trade {inst_id}: {skipped_instruments[inst_id]}"
        print(f"  [OKX] {coin} SKIP: {detail}", file=sys.stderr)
        return {"coin": coin, "action": action, "status": "skip", "detail": detail}

    exec_status = {"coin": coin, "action": action, "status": "none", "detail": ""}
    lev = result.get("leverage", 2.5)
    profile = get_coin_profile(coin)

    try:
        if action in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
            pos_side = "long" if action == "OPEN_LONG_ENTRY_1" else "short"
            sz, _, pos_val = calc_contract_size(coin, equity_usd, CAPITAL_PER_POSITION, lev, instrument_map)
            side = "buy" if pos_side == "long" else "sell"
            entry_px = result.get("entry_zone", {}).get("current_price")
            sl_px = None
            if entry_px and entry_px > 0 and profile["max_loss_pct"] > 0:
                sl_factor = 1 - profile["max_loss_pct"] / lev if pos_side == "long" else 1 + profile["max_loss_pct"] / lev
                sl_px = f"{entry_px * sl_factor:.2f}"
            resp = okx_place_order(inst_id, "cross", side, sz, sl_trigger_px=sl_px)
            exec_status.update({"status": "open", "detail": f"{pos_side} market {sz}ct SL@{sl_px}" if sl_px else f"{pos_side} market {sz}ct"})
            print(f"  [OKX] {coin} OPEN {pos_side} {sz}ct{' SL@'+sl_px if sl_px else ''}")

        elif action in ("ADD_LONG_ENTRY_2", "ADD_SHORT_ENTRY_2",
                        "ADD_LONG_ENTRY_3", "ADD_SHORT_ENTRY_3"):
            pos_side = "long" if "LONG" in action else "short"
            add_pct = 0.10
            sz, _, pos_val = calc_contract_size(coin, equity_usd, add_pct, lev, instrument_map)
            side = "buy" if pos_side == "long" else "sell"
            resp = okx_place_order(inst_id, "cross", side, sz)
            exec_status.update({"status": "add", "detail": f"add {pos_side} {sz}ct", "sz": sz})
            print(f"  [OKX] {coin} ADD {pos_side} {sz}ct market")
            # Amend stoploss based on avg entry price (6% max loss rule)
            try:
                time.sleep(1)  # wait for position update
                positions = okx_get_positions("SWAP")
                pos = next((p for p in positions if p.get("instId") == inst_id), None)
                if pos:
                    avg_px = float(pos.get("avgPx", 0))
                    if avg_px > 0:
                        factor = 1 - profile["max_loss_pct"] / lev if pos_side == "long" else 1 + profile["max_loss_pct"] / lev
                        new_sl = f"{avg_px * factor:.2f}"
                        algos = okx_get_algo_orders(inst_id, "conditional")
                        algo_id = algos[0]["algoId"] if algos else None
                        if algo_id:
                            okx_amend_algo(inst_id, algo_id, new_sl)
                            print(f"  [OKX] {coin} stoploss amended to ${new_sl} (avgPx=${avg_px:.2f})", file=sys.stderr)
            except Exception as e:
                print(f"  [OKX] {coin} amend stoploss failed: {e}", file=sys.stderr)

        elif action in ("EXIT_LONG", "EXIT_SHORT", "REDUCE_LONG", "REDUCE_SHORT"):
            pos_side = "long" if "LONG" in action else "short"
            if action.startswith("EXIT"):
                resp = okx_close_position(inst_id)
                exec_status["status"] = "exit"
                exec_status["detail"] = f"close {pos_side}"
                print(f"  [OKX] {coin} EXIT {pos_side}")
            else:
                # REDUCE — sell 50% via market
                pos = get_okx_position_for_coin(positions, coin)
                if pos and float(pos.get("pos", 0)) > 0:
                    sz = str(int(float(pos["pos"]) * 0.5))
                    if int(sz) > 0:
                        side = "sell" if pos_side == "long" else "buy"
                        resp = okx_place_order(inst_id, "cross", side, sz)
                        exec_status["status"] = "reduce"
                        exec_status["detail"] = f"reduce 50% {pos_side} ({sz}ct)"
                        print(f"  [OKX] {coin} REDUCE {pos_side} {sz}ct")

        elif action in ("TAKE_PROFIT_1_LONG", "TAKE_PROFIT_1_SHORT",
                        "TAKE_PROFIT_2_LONG", "TAKE_PROFIT_2_SHORT",
                        "OVER_EXTEND_LONG", "OVER_EXTEND_SHORT"):
            pos_side = "long" if "LONG" in action else "short"
            reduce_pct = 0.3 if "TAKE_PROFIT" in action else 0.25
            pos = get_okx_position_for_coin(positions, coin)
            if pos and float(pos.get("pos", 0)) > 0:
                sz = str(max(1, int(float(pos["pos"]) * reduce_pct)))
                if int(sz) > 0:
                    kind = "TP" if "TAKE_PROFIT" in action else "OE"
                    side = "sell" if pos_side == "long" else "buy"
                    resp = okx_place_order(inst_id, "cross", side, sz)
                    exec_status["status"] = "reduce"
                    exec_status["detail"] = f"{kind} reduce {pos_side} {sz}ct"
                    print(f"  [OKX] {coin} {kind} {pos_side} {sz}ct")

    except OKXMetadataError as exc:
        exec_status["status"] = "skip"
        exec_status["detail"] = str(exc)
        print(f"  [OKX] {coin} SKIP: {exc}", file=sys.stderr)
    except OKXError as exc:
        exec_status["status"] = "error"
        exec_status["detail"] = str(exc)
        print(f"  [OKX] {coin} ERROR: {exc}", file=sys.stderr)

    return exec_status


def execute_trading_actions(results: list, instrument_map: dict, skipped_instruments: dict) -> list:
    """Execute all non-trivial actions on OKX. Returns execution log."""
    try:
        account = okx_get_account()
        equity_usd = float(account.get("data", [{}])[0].get("totalEq", 0))
        positions = okx_get_positions("SWAP")
    except OKXError as exc:
        print(f"[crypto_trading] OKX connection failed: {exc}", file=sys.stderr)
        return [{"coin": "all", "status": "error", "detail": str(exc)}]

    _ensure_okx_setup(instrument_map)
    print(f"[crypto_trading] Equity: ${equity_usd:,.2f} | Open positions: {len(positions)}")

    exec_log = []
    for r in results:
        if r["action"] not in ("NO_TRADE", "HOLD"):
            log = _exec_action_on_okx(r, instrument_map, skipped_instruments, positions, equity_usd)
            exec_log.append(log)
    return exec_log


# ---------------------------------------------------------------------------
# Portfolio summary
# ---------------------------------------------------------------------------

def _format_pnl(pnl: str) -> str:
    val = float(pnl)
    return f"{val:+.2f}" if abs(val) < 1000 else f"{val:+.0f}"


def build_portfolio_summary(now_vnt: datetime, positions: list, account_info: dict) -> str | None:
    """Build a portfolio overview message."""
    try:
        eq_data = account_info.get("data", [{}])[0]
        total_eq = float(eq_data.get("totalEq", 0))
    except (IndexError, ValueError):
        return None

    ts = now_vnt.strftime("%d/%m/%Y %I:%M %p (VNT)")
    lines = [f"**Portfolio Summary** — {ts}", ""]

    # Overall
    try:
        u_pnl = float(eq_data.get("uTime", "0"))
    except ValueError:
        u_pnl = 0
    lines.append(f"Total Equity: **${total_eq:,.2f}**")
    lines.append("")

    # Positions
    coin_positions = {}
    for p in positions:
        inst = p.get("instId", "")
        for coin, inst_id in OKX_INSTRUMENTS.items():
            if inst == inst_id:
                coin_positions[coin] = p
                break

    if coin_positions:
        lines.append("**Open Positions:**")
        for coin, p in sorted(coin_positions.items()):
            pos = float(p.get("pos", 0))
            if pos == 0:
                continue
            side = "LONG" if p.get("posSide") == "long" else "SHORT"
            margin = float(p.get("margin", 0))
            upl = float(p.get("upl", 0))
            lev = float(p.get("lever", 1))
            pnl_pct = (upl / margin * 100) if margin > 0 else 0
            notional = float(p.get("notionalUsd", 0))
            lines.append(
                f"**{coin}** {side} | "
                f"Notional: ${notional:,.0f} | "
                f"Lever: {lev:.1f}x | "
                f"Margin: ${margin:,.2f} | "
                f"PnL: {_format_pnl(upl)} USD ({pnl_pct:+.2f}%)"
            )
        lines.append("")

    lines.append("⋆｡°✩ — ⋆｡°✩ — ⋆｡°✩")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Notification builders
# ---------------------------------------------------------------------------

def _format_exec_for_notif(exec_log: list) -> str:
    if not exec_log:
        return ""
    lines = []
    for e in exec_log:
        status = e["status"]
        coin = e["coin"]
        detail = e.get("detail", "")
        if status == "open":
            lines.append(f"## OPEN {coin}: {detail}")
        elif status == "add":
            lines.append(f"## ADD {coin}: {detail}")
        elif status == "exit":
            lines.append(f"## EXIT {coin}: {detail}")
        elif status == "reduce":
            lines.append(f"## REDUCE {coin}: {detail}")
        elif status == "error":
            lines.append(f"## ERROR {coin}: {detail}")
        elif status == "skip":
            lines.append(f"## SKIP {coin}: {detail}")
    return "\n".join(lines)


def _build_metadata_alerts(skipped_instruments: dict) -> Dict[str, str]:
    alerts: Dict[str, str] = {}
    tracked_instruments = {
        inst_id: coin for coin, inst_id in OKX_INSTRUMENTS.items() if coin in COINS
    }
    for inst_id, reason in skipped_instruments.items():
        coin = tracked_instruments.get(inst_id)
        if not coin:
            continue
        alert = f"## SKIP {coin}: cannot trade {inst_id} because {reason}"
        print(f"[crypto_trading] {alert}", file=sys.stderr)
        alerts[coin] = alert
    return alerts


def build_action_message(
    results: list, exec_log: list, kill_switch: bool, now_vnt: datetime,
) -> str:
    ks_flag = " 🚨 KILL SWITCH" if kill_switch else ""
    ts = now_vnt.strftime("%d/%m/%Y %I:%M %p (VNT)")
    lines = [f"**Crypto Trading**{ks_flag}", ts, ""]

    exec_text = _format_exec_for_notif(exec_log)
    if exec_text:
        lines.append("### Orders Executed")
        lines.append(exec_text)
        lines.append("")

    # Also show analysis summary for context
    has_signal = False
    for r in results:
        if r["action"] not in ("NO_TRADE", "HOLD"):
            has_signal = True
            icon = _signal_icon(r)
            lines.append(f"{icon} **{r['coin']}** | Score {r['trend_score']:+d} | {r['position_state']}")
            lines.append(f"    -> {_action_text(r)}")
    if not has_signal:
        lines.append("No action needed.")
    lines.append("")
    lines.append("⋆｡°✩ — ⋆｡°✩ — ⋆｡°✩")
    return "\n".join(lines)


def build_no_action_message(now_vnt: datetime) -> str:
    ts = now_vnt.strftime("%d/%m/%Y %I:%M %p (VNT)")
    return (
        f"**Crypto Trading**\n{ts}\n\n"
        f"No action for all coin.\n\n"
        f"⋆｡°✩ — ⋆｡°✩ — ⋆｡°✩"
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    webhook_url = os.environ.get("DISCORD_TRADING_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_TRADING_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(1)

    now_vnt = _now_vnt()
    print(f"[crypto_trading] Starting at {now_vnt.strftime('%Y-%m-%d %H:%M %Z')}")

    okx_enabled = all(os.environ.get(k) for k in
                      ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"])
    print(f"[crypto_trading] OKX mode: {'EXECUTION' if okx_enabled else 'SIGNAL-ONLY'}")

    # Instrument map for contract size calculations
    instrument_map, skipped_instruments = get_instrument_map() if okx_enabled else ({}, {})
    metadata_alerts = _build_metadata_alerts(skipped_instruments) if okx_enabled else {}

    # Kill-switch check (BTC default 1d)
    print("[crypto_trading] Fetching BTC data for kill-switch\u2026")
    try:
        btc_candles = fetch_klines(BTC_SYMBOL, limit=BTC_CANDLE_COUNT)
    except requests.RequestException as exc:
        print(f"[crypto_trading] Fatal: cannot fetch BTC data: {exc}",
              file=sys.stderr)
        sys.exit(1)

    kill_switch = check_kill_switch(btc_candles)
    if kill_switch:
        print("[crypto_trading] KILL SWITCH ACTIVE \u2013 market stress detected!")
    else:
        print("[crypto_trading] Kill switch not triggered.")

    # BTC regime filter (MA50 vs MA200 on daily)
    _btc_closes = [c["close"] for c in btc_candles]
    _btc_ma50 = (sma(_btc_closes, 50)[-1] or _btc_closes[-1])
    _btc_ma200 = (sma(_btc_closes, 200)[-1] or _btc_closes[-1])
    _btc_bull = _btc_ma50 > _btc_ma200
    print(f"[crypto_trading] BTC regime: {'BULL' if _btc_bull else 'BEAR'} "
          f"(MA50={_btc_ma50:.0f} MA200={_btc_ma200:.0f})")

    # Time filter: avoid economic events
    _current_hour = now_vnt.hour
    _in_event_window = any(
        start <= _current_hour <= end
        for start, end in ECONOMIC_EVENT_WINDOWS
    )
    if _in_event_window:
        print(f"[crypto_trading] In economic event window ({_current_hour}h VNT) "
              f"\u2013 skipping new entries")

    # Count active positions (from Firestore)
    _active_positions = sum(
        1 for c in COINS
        if load_state(c).get("position_state", "FLAT") != "FLAT"
    )
    print(f"[crypto_trading] Active positions: {_active_positions}/{MAX_CONCURRENT_POSITIONS}")

    # Analyse each coin
    results: list[dict[str, Any]] = []
    for coin in COINS:
        symbol = SYMBOL_MAP[coin]
        print(f"[crypto_trading] Fetching {symbol} (12h)\u2026")
        try:
            candles_12h = fetch_klines(symbol, "12h")
        except requests.RequestException as exc:
            print(f"[crypto_trading] Warning: cannot fetch {symbol}: {exc}",
                  file=sys.stderr)
            continue

        print(f"[crypto_trading] Analysing {coin}\u2026")
        result = analyse_coin(
            coin, candles_12h, kill_switch,
            active_count=_active_positions,
            in_event_window=_in_event_window,
        )
        results.append(result)
        
        # Get regime from result (added in analyse_coin)
        coin_regime = result.get('regime', 'UNKNOWN')
        
        print(
            f"  {coin}: regime={coin_regime} "
            f"trend={result['trend']} "
            f"TrendScore={result['trend_score']:+d} "
            f"state={result['position_state']} "
            f"action={result['action']}"
        )

    # Decide notification timing
    all_wait = all(r['action'] == 'NO_TRADE' for r in results)
    scheduled_hours = {10, 15, 21}
    is_scheduled = now_vnt.hour in scheduled_hours

    if all_wait and not is_scheduled and not metadata_alerts:
        print("[crypto_trading] No action needed \u2013 done.")
        return

    # Execute on OKX
    exec_log: list = []
    if okx_enabled:
        exec_log = execute_trading_actions(results, instrument_map, skipped_instruments)

    vnt_hour = now_vnt.hour + now_vnt.minute / 60.0
    is_silent = vnt_hour >= 22.5 or vnt_hour < 5.5

    # Build notification message
    if all_wait:
        message = build_no_action_message(now_vnt)
    else:
        message = build_action_message(results, exec_log, kill_switch, now_vnt)

    exec_skip_coins = {e["coin"] for e in exec_log if e.get("status") == "skip"}
    extra_metadata_alerts = [text for coin, text in metadata_alerts.items() if coin not in exec_skip_coins]
    if extra_metadata_alerts:
        message = f"{message}\n\n### Instrument Warnings\n" + "\n".join(extra_metadata_alerts)

    has_error = any(e.get("status") == "error" for e in exec_log)
    has_skip = any(e.get("status") == "skip" for e in exec_log) or bool(extra_metadata_alerts)
    force_send = has_error or has_skip  # safety alerts bypass silent hours

    if is_silent and not force_send:
        if not all_wait:
            print("[crypto_trading] Silent hours \u2013 queuing notification.")
            queue_alert({"text": message}, now_vnt.isoformat())
        else:
            print("[crypto_trading] Silent hours \u2013 skipped.")
    else:
        print("[crypto_trading] Sending to Discord\u2026")
        send_message(webhook_url, message, force=force_send)

    # Flush queue at 6AM VNT (only once, within first 30 min)
    if 6.0 <= vnt_hour < 6.5:
        queued = get_unsent_queued_alerts()
        if queued:
            print(f"[crypto_trading] Flushing {len(queued)} queued notification(s)\u2026")
            for item in queued:
                text = item.get("alert", {}).get("text", "")
                if text:
                    send_message(webhook_url, text)
                mark_alert_sent(item["_doc_id"])
            print(f"[crypto_trading] Flushed {len(queued)} message(s).")

    # Portfolio summary at 6AM / 1PM / 8PM VNT
    if okx_enabled and now_vnt.hour in {6, 13, 20}:
        print("[crypto_trading] Fetching portfolio summary\u2026")
        try:
            account = okx_get_account()
            positions = okx_get_positions("SWAP")
            summary = build_portfolio_summary(now_vnt, positions, account)
            if summary:
                send_message(webhook_url, summary)
        except OKXError as exc:
            print(f"[crypto_trading] Portfolio summary failed: {exc}", file=sys.stderr)

    print("[crypto_trading] Done.")


def run() -> None:
    try:
        main()
    except Exception as exc:
        webhook_url = os.environ.get("DISCORD_TRADING_WEBHOOK_URL")
        if webhook_url:
            send_message(webhook_url, f"Cannot run due to {exc}")
        raise


if __name__ == "__main__":
    run()
