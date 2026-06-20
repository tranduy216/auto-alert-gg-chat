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
from datetime import datetime
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
# Configuration
# ---------------------------------------------------------------------------

COINS = ["ETH", "BNB", "TRX"]
SYMBOL_MAP: dict[str, str] = {coin: f"{coin}USDT" for coin in COINS}
SHORT_ALLOWED: set[str] = {"ETH", "TRX"}

# ── v9 Capital & Risk ────────────────────────────────────────────────
BASE_CAPITAL = 10000
TOTAL_CAPITAL_MULT = 2.8  # baseline multiplier (per-coin overrides below)
MAX_PER_COIN_PCT = 0.65
LOW_DD_COINS = {"ETH"}
ENTRY_MIN_SCORE = 65

def _coin_lev(coin: str) -> float:
    if coin == "ETH": return 2.5
    if coin == "BNB": return 3.5
    if coin == "TRX": return 3.5
    return 3.0

def _coin_sl_roi(coin: str) -> float:
    if coin in LOW_DD_COINS: return 10.0
    return 12.0

def _coin_trail(coin: str) -> float:
    if coin in LOW_DD_COINS: return 0.04  # ETH trail
    if coin == "TRX": return 0.065
    return 0.065

def _entry_margin(coin: str, strong: bool = True) -> float:
    return 0.09 if strong else 0.07

TP_SCHEDULE = [(8.0, 0.10), (15.0, 0.15), (25.0, 0.20), (40.0, 0.25)]

def _coin_cap(coin: str) -> float:
    """Per-coin capital multiplier override."""
    if coin == "ETH": return 2.5
    if coin == "BNB": return 2.8
    if coin == "TRX": return 2.5
    return TOTAL_CAPITAL_MULT

# ── Bear-mode risk reduction ─────────────────────────────────────────
# When BTC regime is bear (MA50 < MA200), reduce risk:
#   - All coins: leverage 2.0
#   - ETH: position multiplier 90%, SL 8%
#   - BNB/TRX: position multiplier 75%, SL 8%/10%
BEAR_LEV = 2.0

def _coin_lev_bear(coin: str) -> float:
    return BEAR_LEV

def _coin_sl_bear(coin: str) -> float:
    if coin == "ETH": return 8.0
    if coin == "BNB": return 10.0
    if coin == "TRX": return 8.0
    return 10.0

def _coin_pos_mult_bear(coin: str) -> float:
    if coin == "ETH": return 0.90
    return 0.75  # BNB, TRX, others
ENTRY_COOLDOWN_BARS = {"ETH": 0, "BNB": 0, "TRX": 5}

# Times (VNT) when major economic events may cause volatility — no new entries ±2h
ECONOMIC_EVENT_WINDOWS: list[tuple[int, int]] = [
    (1, 4),   # FOMC minutes / fed speeches (~2am VNT) — wider window
    (7, 10),  # US NFP/CPI (~7:30pm ET → 7:30am VNT+1) — wider window
    (18, 21), # ECB/BOE rate decisions (~1-2pm GMT → 8-9pm VNT) — wider window
]

CANDLE_COUNT = 500          # 12h candles: need MA200(400) + ATR(28) buffer
BTC_CANDLE_COUNT = 220      # 1d candles for BTC kill-switch (unchanged)
BTC_SYMBOL = "BTCUSDT"      # BTC symbol for kill-switch and regime detection

SF = 2.0                     # scale factor: 12h → 24h equivalent (AGGR=2)

# ── Risk Management ─────────────────────────────────────────────────
MAX_CONCURRENT_POSITIONS = 5     # 5 coins, 5 positions max
CAPITAL_PER_POSITION = 0.10      # 10% of total capital per position
CAPITAL_USAGE_HIGH_WATERMARK = 0.70  # total position capital ≤ 70% of total capital
POSITION_RATE_TIGHT_THRESHOLD = 0.50  # when >50% deployed, tighten entry

# Position sizing decay per position tier
POSITION_SIZES = [0.10, 0.10, 0.10]
POSITION_SIZE_BASE = 0.034      # base entry: 3.4%
POSITION_SIZE_SNOWBALL = 0.034  # snowball add: 3.4%
MAX_SNOWBALL_ENTRIES = 2
SNOWBALL_PNL_THRESHOLD = 0.10   # effectively disabled


def get_allocation_multiplier(entry_score: float, bull_regime: bool = True) -> float:
    """Dynamic allocation: scale position size by signal quality + market regime.

    Entry score → capital multiplier:
      Score ≥ 80: 2.0x = 20% capital → 60% exposure
      Score ≥ 65: 1.5x = 15% capital → 45% exposure
      Score ≥ 50: 1.0x = 10% capital → 30% exposure (standard)
      Score ≥ 35: 0.75x = 7.5% capital
      Score  < 35: 0.5x = 5% capital → 15% exposure

    Bear regime: halve all allocations (↓ 50% exposure).
    """
    if entry_score >= 80: mul = 2.0
    elif entry_score >= 65: mul = 1.5
    elif entry_score >= 50: mul = 1.0
    elif entry_score >= 35: mul = 0.75
    else: mul = 0.5

    if not bull_regime:
        mul *= 0.5  # halve in bear

    return mul


def get_position_size(trend_score: int, coin: str = "") -> float:
    """Dynamic position sizing: scale by trend quality and per-coin allocation.
    
    Per-coin POSITION_SIZE_BASE multipliers:
    BTC/ETH: 1.0 (base, DD thấp)
    BNB/TRX: 0.67 (DD cao)
    """
    scale = {3: 1.5, 2: 1.0, 1: 0.5}.get(trend_score, 0.3)
    base = POSITION_SIZE_BASE
    if coin:
        profile = get_coin_profile(coin)
        base = profile.get("position_size_base", POSITION_SIZE_BASE)
    return round(base * scale, 4)


def get_trailing_multiplier(trend_score: int) -> float:
    """Scale trailing stop looseness by trend quality.

    TS3 (confirmed trend): keep tight trail
    TS1 (early trend):     wider trail → give room to develop
    """
    # Lower trailing_pct = tighter trail
    if trend_score >= 3:  return 1.0   # use default trailing_pct
    elif trend_score >= 2: return 0.95  # slightly wider
    elif trend_score >= 1: return 0.88  # wider for TS1
    else: return 0.85                     # widest for probe entries


def get_snowball_size(entry_num: int, entry_score: float) -> float:
    """Snowball sizing rules:
    Entry 2: same as entry 1
    Entry 3: ½ of entry 1 if moderate (score < 65), full if strong (score ≥ 65)
    """
    if entry_num == 2:
        return POSITION_SIZE_SNOWBALL  # same as base
    elif entry_num == 3:
        if entry_score >= 65:
            return POSITION_SIZE_SNOWBALL  # strong signal → full size
        else:
            return round(POSITION_SIZE_SNOWBALL * 0.5, 4)  # moderate → half
    return 0
MAX_MARGIN_PER_COIN_PCT = 0.20   # 20% margin cap (= 60% exposure at 3x)

# Correlation groups: skip entry if correlated coin already has a position
CORRELATION_GROUPS: dict[str, list[str]] = {
    "ETH": ["BNB"],
    "BNB": ["ETH"],
}

# Loss streak — Fibonacci cooldown per-coin
LOSS_STREAK_BREAKER = 3      # consecutive losses → reduce size 50%
LOSS_STREAK_REDUCE = 0.5     # size multiplier
# Fibonacci cooldown: consec_losses → cooldown bars
#   2 losses → 3 bars (F4)
#   3 losses → 5 bars (F5)
#   4 losses → 8 bars (F6)
#   5 losses → 13 bars (F7)
#   ... → general formula: fib(consec_losses + 2)
FIBONACCI_COOLDOWN_MIN = 2   # minimum consecutive losses to trigger cooldown
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
SIDEWAY_EXIT_SCHEDULE = [(4, 0.10), (6, 0.10), (8, 0.10), (10, 0.10)]
SIDEWAY_EXIT_BASE_STRONG = 0.10   # price > MA20 → exit 10%
SIDEWAY_EXIT_BASE_WEAK = 0.15     # price < MA20 → exit 15%
SIDEWAY_EXIT_OVERBOUGHT = 0.25    # RSI > 60 → exit 25%
SIDEWAY_RSI_OVERBOUGHT = 60
SIDEWAY_RSI_OVERSOLD = 40
SIDEWAY_ATR_DROP_PCT = 0.30       # ATR must drop >30% vs 20-bar avg
SIDEWAY_PRICE_RANGE = 0.05        # ±5% oscillation range
REVERSAL_STAGE_EXIT_PCT = 0.50    # exit 50% of remaining on each reversal
MAX_REVERSAL_STAGES = 5           # stage 5 = exit all
REVERSAL_RSI_MAX = 50             # RSI must be < 50 for reversal
REVERSAL_VOL_MULT = 1.2           # volume > 1.2× 5-bar avg for reversal
PULLBACK_RECOVERY_PCT = 0.05      # price recovery >5% cancels reversal tracking
SIDEWAY_EXTEND_TRAIL_REDUCE = 0.35  # tighten trailing by 35% after 5+ sideway bars
SIDEWAY_EXTEND_THRESHOLD = 5      # sideway >5 bars = extended

# Volatility filter
VOLATILITY_ATR_MULTIPLIER = 2.0  # skip entry if ATR > 2× ATR_MA20

# v7 trailing stop — ATR-based adaptive
TRAIL_ATR_BASE_MULT = 2.0        # distance from high: 2x ATR14
TRAIL_ATR_TIGHT_MULT = 1.5       # tighten when PnL >= 5%
TRAIL_ATR_LOCK_MULT = 1.0        # lock profits when PnL >= 10%
TRAIL_ATR_RUN_MULT = 0.75        # runner mode when PnL >= 20%
TRAIL_ATR_PROFIT_MILESTONES = [  # (PnL%, atr_mult)
    (5.0, 1.5),
    (10.0, 1.0),
    (20.0, 0.75),
]

LEVERAGE = 2.5
MAX_MARGIN_PER_COIN = 0.15
STAGE_MARGIN = 0.05

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

def _smart_round(v: float) -> float:
    if v == 0.0:
        return 0.0
    abs_v = abs(v)
    if abs_v >= 1000:
        return round(v, 1)
    if abs_v >= 10:
        return round(v, 2)
    if abs_v >= 0.1:
        return round(v, 4)
    if abs_v >= 0.001:
        return round(v, 6)
    return round(v, 8)


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


def compute_reaction_score_long(close: float, low: float, ma3: float) -> float:
    if close <= ma3 or ma3 <= 0:
        return 0.0
    diff_ratio = abs(low - ma3) / ma3
    if diff_ratio < 0.005:
        return 1.0
    if diff_ratio < 0.01:
        return 0.5
    return 0.0


def compute_reaction_score_short(close: float, high: float, ma3: float) -> float:
    if close >= ma3 or ma3 <= 0:
        return 0.0
    diff_ratio = abs(high - ma3) / ma3
    if diff_ratio < 0.005:
        return 1.0
    if diff_ratio < 0.01:
        return 0.5
    return 0.0


def compute_resistance(candles: list[dict], ma7: float, ma10: float) -> float:
    recent_high = max(c["high"] for c in candles[-10:])
    return max(ma7, ma10, recent_high)


def compute_support(candles: list[dict], ma7: float, ma10: float) -> float:
    recent_low = min(c["low"] for c in candles[-10:])
    return min(ma7, ma10, recent_low)


def compute_break_score_long(close: float, resistance: float, atr: float) -> float:
    return 1.0 if close > resistance + 0.3 * atr else 0.0


def compute_break_score_short(close: float, support: float, atr: float) -> float:
    return 1.0 if close < support - 0.3 * atr else 0.0


def compute_atr_score(atr: float, price: float) -> float:
    if price <= 0:
        return 0.3
    ratio = atr / price * 100
    if 0.5 <= ratio <= 1.5:
        return 1.0
    if 1.5 < ratio <= 3.0:
        return 0.7
    if ratio > 3.0:
        return 0.4
    return 0.3


def compute_entry1_signal_long(close: float, ma7: float, volume_score: float) -> bool:
    near_ma7 = close >= ma7 * 0.97 and close <= ma7 * 1.03
    return near_ma7 and volume_score >= 0.4


def compute_entry1_signal_short(close: float, ma7: float, volume_score: float) -> bool:
    near_ma7 = close <= ma7 * 1.03 and close >= ma7 * 0.97
    return near_ma7 and volume_score >= 0.4


def compute_entry_zone_v4(
    candles_1d: list[dict],
    trend_score: int,
    ma7: float,
    ma10: float,
    atr: float,
) -> dict:
    current_price = candles_1d[-1]["close"]
    recent_low = min(c["low"] for c in candles_1d[-10:])
    recent_high = max(c["high"] for c in candles_1d[-10:])

    if trend_score >= 2:
        support = min(ma10, recent_low)
        upper_bound = min(current_price * 1.01, ma7)
        return {
            "current_price": _smart_round(current_price),
            "support": _smart_round(support),
            "optimal_entry": _smart_round(max(support, ma10 * 0.99)),
            "upper_bound": _smart_round(upper_bound),
            "atr": _smart_round(atr),
        }
    if trend_score <= -2:
        resistance = max(ma10, recent_high)
        lower_bound = max(current_price * 0.99, ma7)
        return {
            "current_price": _smart_round(current_price),
            "resistance": _smart_round(resistance),
            "optimal_entry": _smart_round(min(resistance, ma10 * 1.01)),
            "lower_bound": _smart_round(lower_bound),
            "atr": _smart_round(atr),
        }
    return {
        "current_price": _smart_round(current_price),
        "near_support": _smart_round(min(ma10, recent_low)),
        "near_resistance": _smart_round(max(ma10, recent_high)),
        "atr": _smart_round(atr),
    }


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def resolve_action_v4(
    trend_score: int,
    entry1_long: bool,
    entry1_short: bool,
    p_long_entry2: float,
    p_short_entry2: float,
    p_long_entry3: float,
    p_short_entry3: float,
    prev_pos_state: str,
    entry_threshold: int = 2,
) -> tuple[str, str]:
    """Return (position_state, action)."""

    if prev_pos_state == "FLAT":
        if trend_score >= entry_threshold and entry1_long:
            return ("LONG_ENTRY_1", "OPEN_LONG_ENTRY_1")
        if trend_score <= -entry_threshold and entry1_short:
            return ("SHORT_ENTRY_1", "OPEN_SHORT_ENTRY_1")
        return ("FLAT", "NO_TRADE")

    if prev_pos_state == "LONG_ENTRY_1":
        if p_long_entry2 >= 0.80:
            return ("LONG_ENTRY_2", "ADD_LONG_ENTRY_2")
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        if trend_score < 0:
            return ("FLAT", "REDUCE_LONG")
        return ("LONG_ENTRY_1", "HOLD")

    if prev_pos_state == "LONG_ENTRY_2":
        if p_long_entry3 >= 0.85:
            return ("LONG_ENTRY_3", "ADD_LONG_ENTRY_3")
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        return ("LONG_ENTRY_2", "HOLD")

    if prev_pos_state == "LONG_ENTRY_3":
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        return ("LONG_ENTRY_3", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_1":
        if p_short_entry2 >= 0.80:
            return ("SHORT_ENTRY_2", "ADD_SHORT_ENTRY_2")
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        if trend_score > 0:
            return ("FLAT", "REDUCE_SHORT")
        return ("SHORT_ENTRY_1", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_2":
        if p_short_entry3 >= 0.85:
            return ("SHORT_ENTRY_3", "ADD_SHORT_ENTRY_3")
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        return ("SHORT_ENTRY_2", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_3":
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        return ("SHORT_ENTRY_3", "HOLD")

    return ("FLAT", "NO_TRADE")


# ---------------------------------------------------------------------------
# Exit system (v5)
# ---------------------------------------------------------------------------

def evaluate_exit_v5(
    position_state: str,
    entry_price: float | None,
    current_price: float,
    remaining_size: float,
    ma3: float,
    ma7: float,
    ma10: float,
    ma20: float,
    rsi: float,
    trend_score: int,
    ts_val: float,
) -> tuple[str, float, str]:
    """Evaluate exit conditions. Returns (exit_action, reduce_pct, reason).

    exit_action: HOLD | EXIT_ALL | TAKE_PROFIT_1 | TAKE_PROFIT_2 | OVER_EXTEND
    """
    if position_state == "FLAT":
        return ("HOLD", 0.0, "")

    is_long = position_state.startswith("LONG")

    if entry_price is None or entry_price <= 0:
        return ("HOLD", 0.0, "")

    pnl_pct = ((current_price - entry_price) / entry_price *
               100) if is_long else ((entry_price - current_price) / entry_price * 100)

    # 1. Hard Stop Loss (wider)
    if pnl_pct <= -8.0:
        return ("EXIT_ALL", 1.0,
                f"Stop loss hit at {pnl_pct:.1f}% (limit -8.0%)")

    # 2. Emergency Exit — major trend fail
    if is_long:
        if ma7 < ma20 and ts_val < -0.3:
            return ("EXIT_ALL", 1.0,
                    f"Emergency exit: MA7<MA20 & Score {ts_val:.1f} < -0.3")
    else:
        if ma7 > ma20 and ts_val > 0.3:
            return ("EXIT_ALL", 1.0,
                    f"Emergency exit: MA7>MA20 & Score {ts_val:.1f} > 0.3")

    # 3. Trend Exit — MA7<MA20 on 3D = major trend reversal
    if is_long:
        if ma7 < ma20:
            return ("EXIT_ALL", 1.0,
                    f"Trend exit: MA7 ({ma7:.2f}) < MA20 ({ma20:.2f})")
    else:
        if ma7 > ma20:
            return ("EXIT_ALL", 1.0,
                    f"Trend exit: MA7 ({ma7:.2f}) > MA20 ({ma20:.2f})")

    # 4. Score Exit (more tolerant)
    if is_long:
        if ts_val < 0.1:
            return ("EXIT_ALL", 1.0,
                    f"Score exit: {ts_val:.1f} < +0.1")
    else:
        if ts_val > -0.1:
            return ("EXIT_ALL", 1.0,
                    f"Score exit: {ts_val:.1f} > -0.1")

    # 6. Take Profit (closer targets)
    if pnl_pct >= 18:
        cut = remaining_size * 0.3
        return ("TAKE_PROFIT_2", cut,
                f"TP2: +{pnl_pct:.1f}% >= 18% \u2013 reduce {cut/remaining_size*100:.0f}%")
    if pnl_pct >= 10:
        cut = remaining_size * 0.3
        return ("TAKE_PROFIT_1", cut,
                f"TP1: +{pnl_pct:.1f}% >= 10% \u2013 reduce {cut/remaining_size*100:.0f}%")

    # 7. Over-Extension Exit
    if is_long:
        if current_price > ma20 * 1.25 or rsi > 80:
            cut = remaining_size * 0.25
            return ("OVER_EXTEND", cut,
                    f"Over-extended: Price>MA20x1.25 or RSI>{rsi:.0f}>80 \u2013 reduce {cut/remaining_size*100:.0f}%")
    else:
        if current_price < ma20 * 0.75 or rsi < 20:
            cut = remaining_size * 0.25
            return ("OVER_EXTEND", cut,
                    f"Over-extended: Price<MA20x0.75 or RSI<{rsi:.0f}<20 \u2013 reduce {cut/remaining_size*100:.0f}%")

    return ("HOLD", 0.0, "")


# ---------------------------------------------------------------------------
# Exit system (v6) — trailing stop + trend reversal
# ---------------------------------------------------------------------------

def evaluate_exit_v6(
    position_state: str,
    entry_price: float | None,
    current_price: float,
    remaining_size: float,
    ma7_3d: float,
    ma20_3d: float,
    trend_score: int,
    ts_val: float,
    rsi_3d: float,
    recent_10d_low: float,
    recent_10d_high: float,
    trailing_stop: float | None,
    highest_since_entry: float | None,
    max_loss_pct: float = 0.06,
    trailing_pct: float = 0.80,
    initial_stop_pct: float = 0.80,
    hard_stop_pct: float = 0.75,
    # ── v7 ATR-based trailing ──
    atr_1d: float = 0,
    trail_atr_mult: float = 0,
    use_profit_locking: bool = False,
) -> tuple[str, float, str, float | None, float | None]:
    """Exit logic v6/v7: trailing stop + trend reversal.

    v7: optionally uses ATR-based trailing with profit-locking milestones.

    Returns (exit_action, reduce_pct, reason, new_trailing_stop, new_highest).
    """
    if position_state == "FLAT" or entry_price is None or entry_price <= 0:
        return ("HOLD", 0.0, "", trailing_stop, highest_since_entry)

    is_long = position_state.startswith("LONG")
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if is_long else ((entry_price - current_price) / entry_price * 100)

    best_price = max(highest_since_entry or entry_price, current_price) if is_long \
                 else min(highest_since_entry or entry_price, current_price)
    new_stop = trailing_stop

    # ── Determine trail distance ──
    if trail_atr_mult > 0 and atr_1d > 0:
        # ATR-based trail (v7)
        _mult = trail_atr_mult
        if use_profit_locking and pnl_pct > 0:
            for milestone, tighter_mult in TRAIL_ATR_PROFIT_MILESTONES:
                if pnl_pct >= milestone:
                    _mult = tighter_mult
                else:
                    break
        _trail_dist = _mult * atr_1d
        _use_atr = True
    else:
        _use_atr = False
        _trail_dist = 0

    # Initialise trailing stop if not set (first bar after entry)
    if new_stop is None:
        if _use_atr:
            new_stop = round(entry_price - _trail_dist, 2) if is_long else round(entry_price + _trail_dist, 2)
        else:
            new_stop = round(entry_price * (initial_stop_pct if is_long else (2 - initial_stop_pct)), 2)

    # Update trailing stop as price moves favorably
    if is_long and best_price > (highest_since_entry or entry_price):
        if _use_atr:
            trail_level = round(best_price - _trail_dist, 2)
            if trail_level > (new_stop or 0):
                new_stop = trail_level
        else:
            trail_buffer = best_price * trailing_pct
            if trail_buffer > new_stop:
                new_stop = round(trail_buffer, 2)
    elif not is_long and best_price < (highest_since_entry or entry_price):
        if _use_atr:
            trail_level = round(best_price + _trail_dist, 2)
            if trail_level < (new_stop or 999999):
                new_stop = trail_level
        else:
            trail_buffer = best_price * (2 - trailing_pct)
            if trail_buffer < new_stop:
                new_stop = round(trail_buffer, 2)

    # 0. Max loss stop: exit immediately
    if pnl_pct <= -max_loss_pct * 100:
        return ("EXIT_ALL", 1.0, f"Max loss -{max_loss_pct*100:.0f}% stop at ${current_price:.2f}",
                new_stop, best_price)

    # 1. Combined stop: whichever is tighter triggers first
    if _use_atr:
        if is_long:
            if current_price <= (new_stop or 0):
                return ("EXIT_ALL", 1.0, f"Trailing stop at ${new_stop:.2f} (ATR {_mult:.1f}x)",
                        new_stop, best_price)
        else:
            if current_price >= (new_stop or 999999):
                return ("EXIT_ALL", 1.0, f"Trailing stop at ${new_stop:.2f} (ATR {_mult:.1f}x)",
                        new_stop, best_price)
    else:
        hard_stop_level = round(entry_price * (hard_stop_pct if is_long else (2 - hard_stop_pct)), 2)
        if is_long:
            effective_stop = max(new_stop or 0, hard_stop_level)
            if current_price <= effective_stop:
                trigger = "Hard stop" if effective_stop == hard_stop_level else "Trailing stop"
                return ("EXIT_ALL", 1.0, f"{trigger} at ${effective_stop:.2f}",
                        new_stop, best_price)
        else:
            effective_stop = min(new_stop or 999999, hard_stop_level)
            if current_price >= effective_stop:
                trigger = "Hard stop" if effective_stop == hard_stop_level else "Trailing stop"
                return ("EXIT_ALL", 1.0, f"{trigger} at ${effective_stop:.2f}",
                        new_stop, best_price)

    # 2. Trend reversal exit (3D chart)
    if is_long and ma7_3d < ma20_3d:
        return ("EXIT_ALL", 1.0,
                f"Trend reversal: MA7 ({ma7_3d:.2f}) < MA20 ({ma20_3d:.2f})",
                new_stop, best_price)
    if not is_long and ma7_3d > ma20_3d:
        return ("EXIT_ALL", 1.0,
                f"Trend reversal: MA7 ({ma7_3d:.2f}) > MA20 ({ma20_3d:.2f})",
                new_stop, best_price)

    # 3. Trend collapse: exit 25% first, wait 5 bars, exit rest if still collapsed
    if is_long and ts_val < -0.3:
        return ("EXIT_COLLAPSE_25", 0.25, f"Score collapse: {ts_val:.1f} < -0.3",
                new_stop, best_price)
    if not is_long and ts_val > 0.3:
        return ("EXIT_COLLAPSE_25", 0.25, f"Score collapse: {ts_val:.1f} > +0.3",
                new_stop, best_price)

    return ("HOLD", 0.0, "", new_stop, best_price)


# ---------------------------------------------------------------------------
# Sideway detection & staged reversal exit
# ---------------------------------------------------------------------------

def _detect_sideway(candles_12h: list[dict], atr_ma20: float, atr_current: float) -> tuple[bool, int, float, float]:
    """Detect if recent candles are in sideway mode.

    Returns (is_sideway, sideway_bars, high, low).
    """
    first_threshold = SIDEWAY_EXIT_SCHEDULE[0][0]
    lookback = min(first_threshold + 8, len(candles_12h) - 1)
    if lookback < first_threshold:
        return (False, 0, 0, 0)

    segment = candles_12h[-lookback:]
    highs = [c["high"] for c in segment]
    lows = [c["low"] for c in segment]
    seg_high = max(highs)
    seg_low = min(lows)
    mid = (seg_high + seg_low) / 2
    range_pct = (seg_high - seg_low) / mid if mid > 0 else 0

    atr_dropped = atr_current < atr_ma20 * (1 - SIDEWAY_ATR_DROP_PCT)
    is_sideway = range_pct <= SIDEWAY_PRICE_RANGE * 2 and atr_dropped

    if not is_sideway:
        return (False, 0, 0, 0)

    count = 0
    for c in reversed(segment):
        if abs(c["close"] - mid) / mid <= SIDEWAY_PRICE_RANGE:
            count += 1
        else:
            break
    return (count >= first_threshold, count, seg_high, seg_low)


def _check_reversal(ts_val: float, close: float, exec_s_ma: float, rsi_val: float,
                     vol_current: float, vol_5d_avg: float, is_long: bool = True) -> bool:
    """True reversal: price breaks MA20 + RSI confirmation + volume increasing."""
    vol_ok = vol_5d_avg <= 0 or vol_current >= vol_5d_avg * REVERSAL_VOL_MULT
    if is_long:
        if close >= exec_s_ma: return False
        if rsi_val >= REVERSAL_RSI_MAX: return False
    else:
        if close <= exec_s_ma: return False
        if rsi_val <= 100 - REVERSAL_RSI_MAX: return False
    if not vol_ok: return False
    return True


def evaluate_sideway_exit(
    sideway_phase: str,
    sideway_bars: int,
    sideway_milestone: int,
    reversal_count: int,
    rev_low: float,
    close: float,
    high: float,
    low: float,
    ts_val: float,
    rsi: float,
    exec_s_ma: float,
    vol_current: float,
    vol_5d_avg: float,
    candles_12h: list[dict],
    atr_ma20: float,
    atr_current: float,
    trailing_pct: float,
    is_long: bool = True,
) -> dict:
    """Graduated sideway exit + RSI/MA conditions + staged reversal.

    Schedule: 4b≈10-25%, 6b=+10%, 8b=+10%, 10b=+10%.
    First exit depends on RSI/MA: oversold→skip, overbought→25%, <MA20→15%, >MA20→10%.
    """
    result = {
        "action": "HOLD", "reduce_pct": 0.0, "reason": "",
        "new_trailing_pct": trailing_pct,
        "sideway_phase": sideway_phase, "sideway_bars": sideway_bars,
        "sideway_milestone": sideway_milestone,
        "reversal_count": reversal_count, "rev_low": rev_low,
    }

    is_sideway, sw_bars, sw_high, sw_low = _detect_sideway(candles_12h, atr_ma20, atr_current)

    # ── Phase: NONE/COUNTING → enter sideway with RSI/MA-gated first exit ──
    if sideway_phase in ("none", "", None, "counting"):
        if is_sideway and sw_bars >= SIDEWAY_EXIT_SCHEDULE[0][0]:
            first_pct = _get_first_sideway_exit_pct(rsi, close, exec_s_ma)
            if first_pct > 0:
                result["sideway_phase"] = "exited"
                result["sideway_bars"] = sw_bars
                result["sideway_milestone"] = SIDEWAY_EXIT_SCHEDULE[0][0]
                result["reversal_count"] = 0
                result["rev_low"] = close
                result["action"] = "EXIT_SIDEWAY"
                result["reduce_pct"] = first_pct
                result["reason"] = f"Sideway {sw_bars}b (ATR↓, RSI={rsi:.0f}) — exit {first_pct*100:.0f}%"
            else:
                result["sideway_phase"] = "counting_skip"
                result["sideway_bars"] = sw_bars
        elif is_sideway:
            result["sideway_phase"] = "counting"
            result["sideway_bars"] = sw_bars
        return result

    # ── Phase: counting_skip → first exit skipped at 4b, try next milestones ──
    if sideway_phase == "counting_skip":
        for threshold, add_pct in SIDEWAY_EXIT_SCHEDULE:
            if sw_bars >= threshold and sideway_milestone < threshold:
                result["sideway_phase"] = "exited"
                result["sideway_bars"] = sw_bars
                result["sideway_milestone"] = threshold
                result["reversal_count"] = 0
                result["rev_low"] = close
                result["action"] = "EXIT_SIDEWAY"
                result["reduce_pct"] = add_pct
                result["reason"] = f"Sideway {sw_bars}b (was oversold at 4b) — exit +{add_pct*100:.0f}%"
                return result
        if not is_sideway:
            result["sideway_phase"] = "none"
        return result

    # ── Graduated exit: check next milestones (6b, 8b, 10b) ──
    if sideway_phase in ("exited", "reversal") and is_sideway:
        for threshold, add_pct in SIDEWAY_EXIT_SCHEDULE:
            if sw_bars >= threshold and sideway_milestone < threshold:
                result["sideway_bars"] = sw_bars
                result["sideway_milestone"] = threshold
                result["action"] = "EXIT_SIDEWAY"
                result["reduce_pct"] = add_pct
                result["reason"] = f"Sideway extended to {sw_bars}b — exit +{add_pct*100:.0f}%"
                return result

    # ── Sideway >5 bars: tighten trailing 35% ──
    if sideway_phase in ("exited", "reversal") and is_sideway and sw_bars > SIDEWAY_EXTEND_THRESHOLD:
        result["new_trailing_pct"] = trailing_pct + (1.0 - trailing_pct) * SIDEWAY_EXTEND_TRAIL_REDUCE
        result["sideway_bars"] = sw_bars

    # ── Sideway breakout against position → exit all ──
    if sideway_phase in ("exited", "reversal") and is_sideway:
        if (is_long and close < sw_low) or (not is_long and close > sw_high):
            result["action"] = "EXIT_ALL"
            result["reduce_pct"] = 1.0
            result["reason"] = "Sideway breakout against position — exit all"
            result["sideway_phase"] = "none"
            return result

    # ── Sideway breakout in favor → resume normal ──
    if sideway_phase in ("exited", "reversal") and \
       ((is_long and close > sw_high) or (not is_long and close < sw_low)) and not is_sideway:
        result["sideway_phase"] = "none"
        result["sideway_bars"] = 0
        result["sideway_milestone"] = 0
        result["reversal_count"] = 0
        result["reason"] = "Sideway breakout in favor — resume normal"
        return result

    # ── Reversal signals (after sideway exit) ──
    if sideway_phase in ("exited", "reversal"):
        is_reversal = _check_reversal(ts_val, close, exec_s_ma, rsi, vol_current, vol_5d_avg, is_long)
        if is_reversal:
            result["reversal_count"] = reversal_count + 1
            result["rev_low"] = min(rev_low, close) if rev_low > 0 else close
            result["sideway_phase"] = "reversal"
            if result["reversal_count"] >= MAX_REVERSAL_STAGES:
                result["action"] = "EXIT_ALL"
                result["reduce_pct"] = 1.0
                result["reason"] = f"Reversal #{result['reversal_count']} — exit all"
                result["sideway_phase"] = "none"
            else:
                result["action"] = "EXIT_REVERSAL"
                result["reduce_pct"] = REVERSAL_STAGE_EXIT_PCT
                result["reason"] = f"Reversal #{result['reversal_count']}: MA20 break + RSI confirmation"
        elif rev_low > 0 and close > rev_low * (1 + PULLBACK_RECOVERY_PCT):
            result["sideway_phase"] = "none"
            result["sideway_bars"] = 0
            result["sideway_milestone"] = 0
            result["reversal_count"] = 0
            result["reason"] = "Recovered >5% from reversal low — resume normal"

    return result


def _get_first_sideway_exit_pct(rsi: float, close: float, exec_s_ma: float) -> float:
    if rsi < SIDEWAY_RSI_OVERSOLD:
        return 0.0
    if rsi > SIDEWAY_RSI_OVERBOUGHT:
        return SIDEWAY_EXIT_OVERBOUGHT
    if close < exec_s_ma:
        return SIDEWAY_EXIT_BASE_WEAK
    return SIDEWAY_EXIT_BASE_STRONG


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


_V6_NEXT_STATE = {
    "LONG_ENTRY_1": ("LONG_ENTRY_2", "ADD_LONG_ENTRY_2"),
    "LONG_ENTRY_2": ("LONG_ENTRY_3", "ADD_LONG_ENTRY_3"),
    "LONG_ENTRY_3": ("LONG_ENTRY_4", "ADD_LONG_ENTRY_4"),
    "LONG_ENTRY_4": ("LONG_ENTRY_5", "ADD_LONG_ENTRY_5"),
    "LONG_ENTRY_5": ("LONG_ENTRY_5", "HOLD"),
    "SHORT_ENTRY_1": ("SHORT_ENTRY_2", "ADD_SHORT_ENTRY_2"),
    "SHORT_ENTRY_2": ("SHORT_ENTRY_3", "ADD_SHORT_ENTRY_3"),
    "SHORT_ENTRY_3": ("SHORT_ENTRY_4", "ADD_SHORT_ENTRY_4"),
    "SHORT_ENTRY_4": ("SHORT_ENTRY_5", "ADD_SHORT_ENTRY_5"),
    "SHORT_ENTRY_5": ("SHORT_ENTRY_5", "HOLD"),
}

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

    is_long = prev_pos_state.startswith("LONG")

    # PnL from LAST entry price (not original)
    pnl_from_last = 0.0
    if current_price and last_entry_price and last_entry_price > 0:
        pnl_from_last = ((current_price - last_entry_price) / last_entry_price * 100) if is_long \
                        else ((last_entry_price - current_price) / last_entry_price * 100)
    threshold = snowball_pnl_min * 100  # e.g., 3% → 3
    if pnl_from_last < threshold:
        return (prev_pos_state, "HOLD")

    # Size: get_snowball_size handles the sizing rules
    entry_num = int(prev_pos_state.split("_")[-1]) + 1  # next entry number
    if entry_num - 1 >= MAX_SNOWBALL_ENTRIES:
        return (prev_pos_state, "HOLD")

    # Cap check
    next_margin = deployed_margin_pct + POSITION_SIZE_SNOWBALL  # approximate
    if next_margin > MAX_MARGIN_PER_COIN_PCT:
        return (prev_pos_state, "HOLD")

    return _V6_NEXT_STATE.get(prev_pos_state, (prev_pos_state, "HOLD"))


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


def save_state(
    coin: str,
    position_state: str,
    action: str,
    trend_score: int,
    entry2_prob: float,
    entry3_prob: float,
    timestamp: str,
    entry_price: float | None = None,
    remaining_size: float | None = None,
    loss_streak: int = 0,
    trailing_stop: float | None = None,
    highest_since_entry: float | None = None,
    short_loss_streak: int = 0,
    long_loss_streak: int = 0,
    collapse_bar_count: int = 0,
    sideway_phase: str = "",
    sideway_bars: int = 0,
    sideway_milestone: int = 0,
    reversal_count: int = 0,
    rev_low: float = 0.0,
) -> None:
    """Persist position state to Firestore."""
    db = _get_db()
    if db is None:
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(coin)
        data: dict = {
            "position_state": position_state,
            "action": action,
            "last_action": action,
            "trend_score": trend_score,
            "entry2_prob": round(entry2_prob, 2),
            "entry3_prob": round(entry3_prob, 2),
            "timestamp": timestamp,
        }
        if entry_price is not None:
            data["entry_price"] = round(entry_price, 2)
        if remaining_size is not None:
            data["remaining_size"] = round(remaining_size, 4)
        if loss_streak:
            data["loss_streak"] = loss_streak
        if trailing_stop is not None:
            data["trailing_stop"] = trailing_stop
        if highest_since_entry is not None:
            data["highest_since_entry"] = highest_since_entry
        if short_loss_streak:
            data["short_loss_streak"] = short_loss_streak
        if long_loss_streak:
            data["long_loss_streak"] = long_loss_streak
        if collapse_bar_count:
            data["collapse_bar_count"] = collapse_bar_count
        if sideway_phase:
            data["sideway_phase"] = sideway_phase
        if sideway_bars:
            data["sideway_bars"] = sideway_bars
        if sideway_milestone:
            data["sideway_milestone"] = sideway_milestone
        if reversal_count:
            data["reversal_count"] = reversal_count
        if rev_low:
            data["rev_low"] = rev_low
        call_with_retry(
            lambda: doc_ref.set(data),
            resource_name=f"Firestore save {coin} state",
        )
    except Exception as exc:
        print(f"[crypto_trading] Warning: could not save state for {coin}: {exc}",
              file=sys.stderr)


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


def _optimal_text(result: dict) -> str:
    z = result.get("entry_zone", {})
    trend_score = result["trend_score"]
    if trend_score >= 2 or trend_score <= -2:
        return f"${z.get('optimal_entry', '?')}"
    return "-"


def _zone_text(result: dict) -> str:
    z = result.get("entry_zone", {})
    trend_score = result["trend_score"]
    if trend_score >= 2:
        return f"${z.get('support', '?')} \u2013 ${z.get('upper_bound', '?')} (ATR: ${z.get('atr', '?')})"
    if trend_score <= -2:
        return f"${z.get('lower_bound', '?')} \u2013 ${z.get('resistance', '?')} (ATR: ${z.get('atr', '?')})"
    return f"Sup ${z.get('near_support', '?')} \u2013 Res ${z.get('near_resistance', '?')}"


def prob_label(p: float) -> str:
    if p < 0.50:
        return "No action"
    if p < 0.70:
        return "Watch"
    if p < 0.85:
        return "Execute"
    return "High conv."


def format_detail(result: dict) -> str:
    icon = _signal_icon(result)
    position = result["position_state"]
    action = _action_text(result)
    optimal = _optimal_text(result)
    zone = _zone_text(result)
    ts = result["trend_score"]
    heading = f"## {icon} {result['coin']}" if icon else f"## {result['coin']}"
    ts_str = f"{ts:+d}" if ts != 0 else "0"
    lines = [heading, f"STAGE: {position}. TrendScore: {ts_str}"]
    lines.append(f"ACTION: {action}")
    lines.append(f"OPTIMAL: {optimal}. ZONE: {zone}")
    pnl = result.get("pnl_pct", 0)
    rem = result.get("remaining_size", 1.0)
    if position != "FLAT" and rem > 0:
        lines.append(f"PNL: {pnl:+.1f}% | Remaining: {rem*100:.0f}%")
    e2p = result.get("entry2_prob", 0)
    e3p = result.get("entry3_prob", 0)
    lines.append(f"E2 Prob: {e2p*100:.0f}% ({prob_label(e2p)}) | "
                 f"E3 Prob: {e3p*100:.0f}% ({prob_label(e3p)})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-coin analysis pipeline
# ---------------------------------------------------------------------------

def analyse_coin(
    coin: str,
    candles_12h: list[dict],
    kill_switch_active: bool,
    active_count: int = 0,
    max_positions: int = MAX_CONCURRENT_POSITIONS,
    btc_bull: bool = True,
    in_event_window: bool = False,
) -> dict:
    ts = _now_vnt().isoformat()
    profile = get_coin_profile(coin)

    # BTC regime filter: bear → smaller positions, stricter entries
    _bear_mode = not btc_bull

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
    vol_5d_avg = sum(volumes_12h[-int(6 * SF):-1]) / (5 * SF) if len(volumes_12h) >= 6 * SF else last_volume

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

    tot_cap = BASE_CAPITAL * _coin_cap(coin)

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
        roi = pnl_pct_entry * mp * tot_cap * coin_lev / BASE_CAPITAL

        if not is_sh and last_close > hi:
            hi = last_close
        if is_sh and last_close < hi:
            hi = last_close
        ent["highest_since_entry"] = hi

        removed = False

        # Stop loss (ROI-based)
        if roi <= -sl_roi:
            total_pnl += roi * rem / 100
            exit_reasons.append(f"SL: ROI {roi:.1f}% <= -{sl_roi}%")
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

        # Trend reversal exit: close shorts when trend turns bullish
        if is_sh and not removed and trend_score >= 2:
            total_pnl += roi * rem / 100
            exit_reasons.append(f"Short trend reversal: score {trend_score:+d}, ROI {roi:.1f}%")
            removed = True

        # Trend reversal exit: close longs when trend turns bearish
        if not is_sh and not removed and trend_score <= -2:
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
                        from datetime import timedelta
                        cd_s_until = (_now_vnt() + timedelta(hours=cd_bars_fib * 12)).isoformat()
                else:
                    consec_l += 1
                    cd_bars_fib = _fib_cooldown_bars(consec_l, 0)
                    if cd_bars_fib > 0:
                        from datetime import timedelta
                        cd_l_until = (_now_vnt() + timedelta(hours=cd_bars_fib * 12)).isoformat()
            else:
                if is_sh: consec_s = 0
                else: consec_l = 0

        if not removed:
            new_entries.append(ent)

    entries = new_entries

    # Check for new entry — direction-specific cooldown
    deployed = sum(e.get("margin_pct", 0) for e in entries)
    max_margin = tot_cap * MAX_PER_COIN_PCT
    can_enter_base = (deployed * tot_cap) < max_margin

    # Cooldown between entries (flat cd_bars)
    if can_enter_base and cd_bars > 0 and last_entry_ts > 0:
        bar_sec = 12 * 3600
        bars_passed = (now_ts - last_entry_ts) / bar_sec if now_ts > last_entry_ts else 999
        if bars_passed < cd_bars:
            can_enter_base = False

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

    if can_enter_long or can_enter_short:
        el = compute_entry_v6_long(
            trend_score, rsi_12h, last_close, exec_s, exec_m, exec_f, volume_score,
            trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
            rsi_max=profile.get("rsi_max_long", 90),
            ma7_1d=ma7_12h, ma200_1d=ma200_12h,
            last_volume=last_volume, vol_5d_avg=vol_5d_avg,
            use_ma200_filter=False, use_pullback_filter=False,
            use_volume_expan=False, min_entry_score=ENTRY_MIN_SCORE,
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

        ps_, act = resolve_action_v6(trend_score, el, es, "FLAT")
        if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
            is_sh = act.startswith("OPEN_SHORT")
            has_active_longs = any(not e.get("is_short", False) for e in entries)
            has_active_shorts = any(e.get("is_short", False) for e in entries)
            if (is_sh and has_active_longs) or (not is_sh and has_active_shorts):
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
                strong = sc >= ENTRY_MIN_SCORE
                mp = _entry_margin(coin, strong)
                # Bear-mode: apply per-coin position multiplier instead of flat halve
                if _bear_mode:
                    mp *= _coin_pos_mult_bear(coin)
                # Bear-mode: also reduce leverage and SL for this entry
                bear_lev = _coin_lev_bear(coin) if _bear_mode else coin_lev
                bear_sl = _coin_sl_bear(coin) if _bear_mode else sl_roi
                if deployed + mp <= max_margin / tot_cap + 0.001:
                    entries.append({
                        "entry_price": last_close,
                        "margin_pct": mp,
                        "is_short": is_sh,
                        "tp_stage": 0,
                        "remaining_size": 1.0,
                        "highest_since_entry": last_close,
                        "trailing_stop": None,
                        "lev": bear_lev,
                        "sl_roi": bear_sl,
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
            btc_bull=_btc_bull,
            in_event_window=_in_event_window,
        )
        results.append(result)
        print(
            f"  {coin}: trend={result['trend']} "
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
