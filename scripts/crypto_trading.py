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
from typing import Any

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.discord_webhook import send_message
from utils.okx_utils import (
    OKX_INSTRUMENTS, calc_contract_size, get_instrument_map,
    get_okx_position_for_coin, okx_close_position, okx_get_account,
    okx_get_positions, okx_place_order, okx_set_leverage, OKXError,
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

COINS = ["ETH", "BNB", "DOGE", "PAXG", "TRX"]
SYMBOL_MAP: dict[str, str] = {coin: f"{coin}USDT" for coin in COINS}
SHORT_ALLOWED = {"ETH", "PAXG"}
BTC_SYMBOL = "BTCUSDT"

# Times (VNT) when major economic events may cause volatility — no new entries ±2h
ECONOMIC_EVENT_WINDOWS: list[tuple[int, int]] = [
    (1, 3),   # FOMC minutes / fed speeches (~2am VNT)
    (7, 9),   # US non-farm payroll / CPI (~7:30pm ET → 7:30am VNT+1)
    (18, 20), # ECB / BOE rate decisions (~1-2pm GMT → 8-9pm VNT)
]

CANDLE_COUNT = 30
BTC_CANDLE_COUNT = 220  # enough for MA200 + buffer

# ── Risk Management ─────────────────────────────────────────────────
MAX_CONCURRENT_POSITIONS = 4     # max positions open at the same time
CAPITAL_PER_POSITION = 0.10      # 10% of total capital per position (2.5x → 25% exposure)
CAPITAL_USAGE_HIGH_WATERMARK = 0.75  # total position capital ≤ 75% of total capital
POSITION_RATE_TIGHT_THRESHOLD = 0.55  # when >55% deployed, tighten entry

# Position sizing decay per position tier
POSITION_SIZES = [0.10, 0.10, 0.10]  # pos 1→3: 10% each

# Correlation groups: skip entry if correlated coin already has a position
CORRELATION_GROUPS: dict[str, list[str]] = {
    "ETH": ["MATIC"],
    "MATIC": ["ETH"],
}

# Loss streak
LOSS_STREAK_BREAKER = 3      # consecutive losses → reduce size 50%
LOSS_STREAK_REDUCE = 0.5     # size multiplier
SHORT_COOLDOWN_LOSSES = 2    # consecutive short losses → pause short on this coin
SHORT_COOLDOWN_DAYS = 20     # pause duration
LONG_COOLDOWN_LOSSES = 2     # consecutive long losses → pause long on this coin
LONG_COOLDOWN_DAYS = 20      # pause duration

# Short trend filter MA pair (fast MA vs slow MA)
# MA20/MA50 → short if MA20 < MA50 (bear); MA15/MA35, MA20/MA40
SHORT_TREND_FAST = 20        # fast MA period for trend filter (both long & short)
SHORT_TREND_SLOW = 40        # slow MA period (also used as price filter)

# Volatility filter
VOLATILITY_ATR_MULTIPLIER = 2.0  # skip entry if ATR > 2× ATR_MA20

# v6 trailing stop
V6_TRAILING_PCT = 0.85       # trail 15% from high (tighter once in profit)
V6_INITIAL_STOP_PCT = 0.85   # initial trailing stop at 85% of entry (15% price trail)
V6_HARD_STOP_PCT = 0.78      # hard cap: 22% price move = 5.5% of total capital @ 10% alloc × 2.5x
V6_MAX_LOSS_PCT = 0.08       # max loss per trade: -8% PnL → exit immediately

LEVERAGE = 2.5
MAX_MARGIN_PER_COIN = 0.15
STAGE_MARGIN = 0.05

BTC_FLASH_CRASH_PCT = -5.0

FIRESTORE_COLLECTION = "crypto_trading_states"


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
               "PAXGUSDT": "PAXG-USDT"}
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
    "PAXGUSDT": "pax-gold"}

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
    result: list[float | None] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1 : i + 1]) / period)
    return result


def compute_atr(candles: list[dict], period: int = 14) -> float:
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
    if len(closes) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
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
    """Classify trend from 3D MAs. Returns (label, trend_score)."""
    ma_max = max(ma7, ma10, ma20)
    ma_min = min(ma7, ma10, ma20)
    spread = (ma_max - ma_min) / ma_min * 100 if ma_min > 0 else 0

    if spread < 0.5:
        return ("SIDEWAY", 0)

    if ma7 > ma10 > ma20:
        return ("BULLISH", 3)

    if ma7 > ma10 and _approx_equal(ma10, ma20):
        return ("WEAK_BULLISH", 2)

    if ma7 < ma10 and _approx_equal(ma10, ma20):
        return ("WEAK_BEARISH", -2)

    if ma7 < ma10 < ma20:
        return ("BEARISH", -3)

    return ("SIDEWAY", 0)


def trend_strength(score: int) -> float:
    return {3: 1.0, 2: 0.7, 0: 0.0, -2: -0.7, -3: -1.0}.get(score, 0.0)


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
) -> tuple[str, float, str, float | None, float | None]:
    """Exit logic v6: trailing stop + trend reversal.

    Returns (exit_action, reduce_pct, reason, new_trailing_stop, new_highest).
    """
    if position_state == "FLAT" or entry_price is None or entry_price <= 0:
        return ("HOLD", 0.0, "", trailing_stop, highest_since_entry)

    is_long = position_state.startswith("LONG")
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if is_long else ((entry_price - current_price) / entry_price * 100)

    # Best price since entry: highest for long, lowest for short
    best_price = max(highest_since_entry or entry_price, current_price) if is_long \
                 else min(highest_since_entry or entry_price, current_price)
    new_stop = trailing_stop

    # Initialise trailing stop if not set (first bar after entry)
    if new_stop is None:
        new_stop = round(entry_price * (V6_INITIAL_STOP_PCT if is_long else (2 - V6_INITIAL_STOP_PCT)), 2)

    # Update trailing stop as price moves favorably
    if is_long:
        if best_price > (highest_since_entry or entry_price):
            trail_buffer = best_price * V6_TRAILING_PCT
            if trail_buffer > new_stop:
                new_stop = round(trail_buffer, 2)
    else:
        if best_price < (highest_since_entry or entry_price):
            trail_buffer = best_price * (2 - V6_TRAILING_PCT)
            if trail_buffer < new_stop:
                new_stop = round(trail_buffer, 2)

    # 0. Max loss stop: -8% PnL → exit immediately
    if pnl_pct <= -V6_MAX_LOSS_PCT * 100:
        return ("EXIT_ALL", 1.0, f"Max loss -{V6_MAX_LOSS_PCT*100:.0f}% stop at ${current_price:.2f}",
                new_stop, best_price)

    # 1. Combined stop: whichever is tighter triggers first
    #    Hard stop = 7% of total capital cap (28% price move)
    #    Dynamic trail = 15% from best price, tightens as price moves favorably
    hard_stop_level = round(entry_price * (V6_HARD_STOP_PCT if is_long else (2 - V6_HARD_STOP_PCT)), 2)
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

    # 3. Emergency exit: trend completely gone
    if is_long and ts_val < -0.3:
        return ("EXIT_ALL", 1.0, f"Score collapse: {ts_val:.1f} < -0.3",
                new_stop, best_price)
    if not is_long and ts_val > 0.3:
        return ("EXIT_ALL", 1.0, f"Score collapse: {ts_val:.1f} > +0.3",
                new_stop, best_price)

    return ("HOLD", 0.0, "", new_stop, best_price)


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
) -> bool:
    """Entry signal for LONG: trend_ma_fast > trend_ma_slow (uptrend) + price above MA20."""
    if trend_score < 1:
        return False
    if trend_ma_fast_1d is not None and trend_ma_fast_1d < trend_ma_slow_1d:
        return False
    if close < ma20_1d:
        return False
    if close < trend_ma_slow_1d:
        return False
    if volume_score < 0.4:
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
) -> bool:
    """Entry signal for SHORT: bear trend (trend_ma_fast < trend_ma_slow 1D) + price below MA20/trend_ma_slow."""
    if trend_score > -3:
        return False
    if trend_ma_fast_1d is not None and trend_ma_fast_1d > trend_ma_slow_1d:
        return False
    if close > ma20_1d:
        return False
    if close > trend_ma_slow_1d:
        return False
    if volume_score < 0.4:
        return False
    return True


def resolve_action_v6(
    trend_score: int,
    entry_long: bool,
    entry_short: bool,
    prev_pos_state: str,
) -> tuple[str, str]:
    """State machine v6 — single position, no pyramiding."""
    if prev_pos_state == "FLAT":
        if entry_long:
            return ("LONG_ENTRY_1", "OPEN_LONG_ENTRY_1")
        if entry_short:
            return ("SHORT_ENTRY_1", "OPEN_SHORT_ENTRY_1")
        return ("FLAT", "NO_TRADE")
    return (prev_pos_state, "HOLD")


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
    short_cooldown_until: str = "",
    long_loss_streak: int = 0,
    long_cooldown_until: str = "",
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
        if short_cooldown_until:
            data["short_cooldown_until"] = short_cooldown_until
        if long_loss_streak:
            data["long_loss_streak"] = long_loss_streak
        if long_cooldown_until:
            data["long_cooldown_until"] = long_cooldown_until
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
    candles_3d: list[dict],
    candles_1d: list[dict],
    kill_switch_active: bool,
    active_count: int = 0,
    max_positions: int = MAX_CONCURRENT_POSITIONS,
    btc_bull: bool = True,
    in_event_window: bool = False,
) -> dict:
    ts = _now_vnt().isoformat()

    # --- Trend Engine (3D) ---
    closes_3d = [c["close"] for c in candles_3d]

    ma3_3d_all = sma(closes_3d, 3)
    ma7_3d_all = sma(closes_3d, 7)
    ma10_3d_all = sma(closes_3d, 10)
    ma20_3d_all = sma(closes_3d, 20)

    ma3_3d = ma3_3d_all[-1] if ma3_3d_all[-1] is not None else closes_3d[-1]
    ma7_3d = ma7_3d_all[-1] if ma7_3d_all[-1] is not None else closes_3d[-1]
    ma10_3d = ma10_3d_all[-1] if ma10_3d_all[-1] is not None else closes_3d[-1]
    ma20_3d = ma20_3d_all[-1] if ma20_3d_all[-1] is not None else closes_3d[-1]

    trend_label, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
    ts_val = trend_strength(trend_score)

    # 3D RSI for exit system
    rsi_3d = compute_rsi(closes_3d, 14)

    # --- Execution Engine (1D) ---
    closes_1d = [c["close"] for c in candles_1d]
    highs_1d = [c["high"] for c in candles_1d]
    lows_1d = [c["low"] for c in candles_1d]
    volumes_1d = [c["volume"] for c in candles_1d]

    ma3_1d_all = sma(closes_1d, 3)
    ma5_1d_all = sma(closes_1d, 5)
    ma7_1d_all = sma(closes_1d, 7)
    ma10_1d_all = sma(closes_1d, 10)
    vol_ma20_1d_all = sma(volumes_1d, 20)

    ma3_1d = ma3_1d_all[-1] if ma3_1d_all[-1] is not None else closes_1d[-1]
    ma5_1d = ma5_1d_all[-1] if ma5_1d_all[-1] is not None else closes_1d[-1]
    ma7_1d = ma7_1d_all[-1] if ma7_1d_all[-1] is not None else closes_1d[-1]
    ma10_1d = ma10_1d_all[-1] if ma10_1d_all[-1] is not None else closes_1d[-1]
    vol_ma20_1d = vol_ma20_1d_all[-1] if vol_ma20_1d_all[-1] is not None else volumes_1d[-1]

    last_close = closes_1d[-1]
    last_low = lows_1d[-1]
    last_high = highs_1d[-1]
    last_volume = volumes_1d[-1]

    # v6 indicators
    rsi_1d = compute_rsi(closes_1d, 14)
    ma20_1d_all = sma(closes_1d, 20)
    ma50_1d_all = sma(closes_1d, 50)
    ma20_1d = ma20_1d_all[-1] if ma20_1d_all[-1] is not None else last_close
    ma50_1d_all = sma(closes_1d, 50)
    ma50_1d = ma50_1d_all[-1] if ma50_1d_all[-1] is not None else last_close
    trend_ma_fast_1d = (sma(closes_1d, SHORT_TREND_FAST)[-1] or None)
    trend_ma_slow_1d = sma(closes_1d, SHORT_TREND_SLOW)[-1] or ma50_1d
    ma200_1d_all = sma(closes_1d, 200)
    ma200_1d = ma200_1d_all[-1] if ma200_1d_all[-1] is not None else None
    recent_10d_low = min(lows_1d[-10:]) if len(lows_1d) >= 10 else last_close * 0.95
    recent_10d_high = max(highs_1d[-10:]) if len(highs_1d) >= 10 else last_close * 1.05

    atr_1d = compute_atr(candles_1d, 14)
    atrs_1d = [compute_atr(candles_1d[:i+1], 14) for i in range(13, len(candles_1d))]
    atr_ma20_1d_all = sma(atrs_1d, 20)
    atr_ma20_1d = atr_ma20_1d_all[-1] if atr_ma20_1d_all[-1] is not None else atr_1d

    volume_score = compute_volume_score(last_volume, vol_ma20_1d)

    # v6 entry signals
    entry_long = compute_entry_v6_long(
        trend_score, rsi_1d, last_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
    )
    entry_short = (
        compute_entry_v6_short(
            trend_score, rsi_1d, last_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
        ) if coin in SHORT_ALLOWED else False
    )

    # Load previous state
    prev = load_state(coin)
    prev_pos_state = prev.get("position_state", "FLAT")
    entry_price = prev.get("entry_price")
    remaining_size = prev.get("remaining_size", 1.0)
    trailing_stop = prev.get("trailing_stop")
    highest_since_entry = prev.get("highest_since_entry")

    # Kill-switch override
    if kill_switch_active:
        save_state(coin, "FLAT", "KILL_SWITCH", trend_score,
                   0.0, 0.0, ts, entry_price=last_close, remaining_size=0.0)
        return {
            "coin": coin,
            "trend": trend_label,
            "trend_score": trend_score,
            "entry2_prob": 0.0,
            "entry3_prob": 0.0,
            "position_state": "FLAT",
            "action": "KILL_SWITCH",
            "leverage": LEVERAGE,
            "entry_zone": {"current_price": last_close},
            "volume_score": volume_score,
            "reaction_score": 0.0,
            "atr_score": 0.0,
            "break_score": 0.0,
            "next_rules": ["Wait for market to stabilise"],
            "timestamp": ts,
            "pnl_pct": 0.0,
            "remaining_size": 0.0,
        }

    pnl_pct = 0.0
    _loss_streak = prev.get("loss_streak", 0)
    _short_loss_streak = prev.get("short_loss_streak", 0)
    _short_cooldown_until = prev.get("short_cooldown_until", "")
    _long_loss_streak = prev.get("long_loss_streak", 0)
    _long_cooldown_until = prev.get("long_cooldown_until", "")

    if prev_pos_state == "FLAT":
        # ── Filter chain ─────────────────────────────────────────────
        _skip_reason = None

        # 1. Max positions
        if active_count >= max_positions:
            _skip_reason = f"Max positions ({max_positions})"

        # 2. Volatility filter
        if not _skip_reason and atr_1d > atr_ma20_1d * VOLATILITY_ATR_MULTIPLIER:
            _skip_reason = f"ATR {atr_1d:.2f} > {VOLATILITY_ATR_MULTIPLIER}× ATR_MA20({atr_ma20_1d:.2f})"

        # 3. Time filter
        if not _skip_reason and in_event_window:
            _skip_reason = "Economic event window"

        # 4. Correlation filter
        if not _skip_reason:
            for _corr_coin in CORRELATION_GROUPS.get(coin, []):
                if load_state(_corr_coin).get("position_state", "FLAT") != "FLAT":
                    _skip_reason = f"{_corr_coin} already in position (correlated)"
                    break

        if _skip_reason:
            pos_state, action = "FLAT", "NO_TRADE"
            entry_price = prev.get("entry_price")
            remaining_size = prev.get("remaining_size", 1.0)
        else:
            # BTC regime filter: in bear, only SHORT (no LONG)
            if not btc_bull and trend_score > 0:
                pos_state, action = "FLAT", "NO_TRADE"
            else:
                entry_long = compute_entry_v6_long(
                    trend_score, rsi_1d, last_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
                )
                entry_short = (
                    compute_entry_v6_short(
                        trend_score, rsi_1d, last_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
                    ) if coin in SHORT_ALLOWED else False
                )
                # Direction-specific cooldowns
                if entry_short and _short_cooldown_until:
                    _cd_dt = datetime.fromisoformat(_short_cooldown_until)
                    if _cd_dt > _now_vnt():
                        entry_short = False
                if entry_long and _long_cooldown_until:
                    _cd_dt = datetime.fromisoformat(_long_cooldown_until)
                    if _cd_dt > _now_vnt():
                        entry_long = False
                pos_state, action = resolve_action_v6(
                    trend_score, entry_long, entry_short, prev_pos_state,
                )

            if action in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                entry_price = last_close
                remaining_size = 1.0
                trailing_stop = None
                highest_since_entry = None

            # Loss streak breaker
            if action.startswith("OPEN_") and _loss_streak >= LOSS_STREAK_BREAKER:
                remaining_size *= LOSS_STREAK_REDUCE
        next_rules = compute_next_rules(pos_state)

    else:
        # Exit evaluation for active positions
        is_long = prev_pos_state.startswith("LONG")
        if entry_price and entry_price > 0:
            pnl_pct = ((last_close - entry_price) / entry_price * 100
                       ) if is_long else ((entry_price - last_close) / entry_price * 100)
        else:
            pnl_pct = 0.0

        exit_action, reduce_pct, exit_reason, new_trailing_stop, new_highest = evaluate_exit_v6(
            prev_pos_state, entry_price, last_close, remaining_size,
            ma7_3d, ma20_3d, trend_score, ts_val, rsi_3d,
            recent_10d_low, recent_10d_high,
            trailing_stop, highest_since_entry,
        )
        trailing_stop = new_trailing_stop
        highest_since_entry = new_highest

        if exit_action == "HOLD":
            pos_state, action = prev_pos_state, "HOLD"
            next_rules = compute_next_rules(pos_state)
        else:
            next_rules = [exit_reason]
            if exit_action == "EXIT_ALL":
                _loss_streak = 0 if pnl_pct > 0 else _loss_streak + 1
                if is_long:
                    if pnl_pct > 0:
                        _long_loss_streak = 0
                        _long_cooldown_until = ""
                    else:
                        _long_loss_streak += 1
                        if _long_loss_streak >= LONG_COOLDOWN_LOSSES:
                            _cooldown_dt = _now_vnt()
                            _cooldown_dt = _cooldown_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                            from datetime import timedelta
                            _cooldown_dt += timedelta(days=LONG_COOLDOWN_DAYS)
                            _long_cooldown_until = _cooldown_dt.isoformat()
                else:  # short position closed
                    if pnl_pct > 0:
                        _short_loss_streak = 0
                        _short_cooldown_until = ""
                    else:
                        _short_loss_streak += 1
                        if _short_loss_streak >= SHORT_COOLDOWN_LOSSES:
                            _cooldown_dt = _now_vnt()
                            _cooldown_dt = _cooldown_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                            from datetime import timedelta
                            _cooldown_dt += timedelta(days=SHORT_COOLDOWN_DAYS)
                            _short_cooldown_until = _cooldown_dt.isoformat()
                pos_state = "FLAT"
                remaining_size = 0.0
                action = "EXIT_LONG" if is_long else "EXIT_SHORT"

            if remaining_size < 0.01 and pos_state != "FLAT":
                pos_state = "FLAT"
                remaining_size = 0.0
                action = "EXIT_LONG" if is_long else "EXIT_SHORT"

    output = {
        "coin": coin,
        "trend": trend_label,
        "trend_score": trend_score,
        "entry2_prob": 0.0,
        "entry3_prob": 0.0,
        "position_state": pos_state,
        "action": action,
        "leverage": LEVERAGE,
        "entry_zone": {"current_price": last_close},
        "volume_score": volume_score,
        "reaction_score": 0.0,
        "atr_score": 0.0,
        "break_score": 0.0,
        "next_rules": next_rules,
        "timestamp": ts,
        "pnl_pct": round(pnl_pct, 2),
        "remaining_size": remaining_size,
    }

    save_state(
        coin, pos_state, action, trend_score,
        output["entry2_prob"], output["entry3_prob"], ts,
        entry_price=entry_price, remaining_size=remaining_size,
        loss_streak=_loss_streak,
        trailing_stop=trailing_stop, highest_since_entry=highest_since_entry,
        short_loss_streak=_short_loss_streak,
        short_cooldown_until=_short_cooldown_until,
        long_loss_streak=_long_loss_streak,
        long_cooldown_until=_long_cooldown_until,
    )

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
        if inst_id:
            okx_set_leverage(inst_id, LEVERAGE)
    _OKX_SETUP_DONE = True


def _exec_action_on_okx(
    result: dict,
    instrument_map: dict,
    positions: list,
    equity_usd: float,
) -> dict:
    """Execute a single action on OKX. Returns execution result dict."""
    coin = result["coin"]
    action = result["action"]
    inst_id = OKX_INSTRUMENTS.get(coin)
    if not inst_id:
        return {"coin": coin, "status": "skip", "detail": "no instrument"}

    exec_status = {"coin": coin, "action": action, "status": "none", "detail": ""}

    try:
        if action in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
            pos_side = "long" if action == "OPEN_LONG_ENTRY_1" else "short"
            sz, _, pos_val = calc_contract_size(coin, equity_usd, CAPITAL_PER_POSITION, LEVERAGE, instrument_map)
            px = result.get("entry_zone", {}).get("optimal_entry")
            if not px:
                exec_status["detail"] = "no limit price"
                return exec_status
            px_str = str(px)
            side = "buy" if pos_side == "long" else "sell"
            resp = okx_place_order(inst_id, "cross", side, sz, px_str)
            exec_status.update({"status": "open", "detail": f"{pos_side} limit {sz}ct @ ${px_str}", "sz": sz, "px": px_str})
            print(f"  [OKX] {coin} OPEN {pos_side} {sz}ct @ {px_str}")

        elif action in ("ADD_LONG_ENTRY_2", "ADD_SHORT_ENTRY_2",
                        "ADD_LONG_ENTRY_3", "ADD_SHORT_ENTRY_3"):
            pos_side = "long" if "LONG" in action else "short"
            add_pct = 0.10  # additional 10% of equity
            sz, _, pos_val = calc_contract_size(coin, equity_usd, add_pct, LEVERAGE, instrument_map)
            px = result.get("entry_zone", {}).get("optimal_entry")
            if not px:
                exec_status["detail"] = "no limit price"
                return exec_status
            px_str = str(px)
            side = "buy" if pos_side == "long" else "sell"
            resp = okx_place_order(inst_id, "cross", side, sz, px_str)
            exec_status.update({"status": "add", "detail": f"add {pos_side} {sz}ct @ ${px_str}", "sz": sz, "px": px_str})
            print(f"  [OKX] {coin} ADD {pos_side} {sz}ct @ {px_str}")

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

    except OKXError as exc:
        exec_status["status"] = "error"
        exec_status["detail"] = str(exc)
        print(f"  [OKX] {coin} ERROR: {exc}", file=sys.stderr)

    return exec_status


def execute_trading_actions(results: list, instrument_map: dict) -> list:
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
            log = _exec_action_on_okx(r, instrument_map, positions, equity_usd)
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
            pass
    return "\n".join(lines)


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
    instrument_map = get_instrument_map() if okx_enabled else {}

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
        print(f"[crypto_trading] Fetching {symbol} (3D + 1D)\u2026")
        try:
            candles_3d = fetch_klines(symbol, "3d")
            candles_1d = fetch_klines(symbol, "1d")
        except requests.RequestException as exc:
            print(f"[crypto_trading] Warning: cannot fetch {symbol}: {exc}",
                  file=sys.stderr)
            continue

        print(f"[crypto_trading] Analysing {coin}\u2026")
        result = analyse_coin(
            coin, candles_3d, candles_1d, kill_switch,
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
    scheduled_hours = {5, 10, 15, 21}
    is_scheduled = now_vnt.hour in scheduled_hours

    if all_wait and not is_scheduled:
        print("[crypto_trading] No action needed \u2013 done.")
        return

    # Execute on OKX
    exec_log: list = []
    if okx_enabled:
        exec_log = execute_trading_actions(results, instrument_map)

    vnt_hour = now_vnt.hour + now_vnt.minute / 60.0
    is_silent = vnt_hour >= 22.5 or vnt_hour < 5.5

    # Build notification message
    if all_wait:
        message = build_no_action_message(now_vnt)
    else:
        message = build_action_message(results, exec_log, kill_switch, now_vnt)

    has_error = any(e.get("status") == "error" for e in exec_log)
    force_send = has_error  # errors bypass silent hours

    if is_silent and not force_send:
        if not all_wait:
            print("[crypto_trading] Silent hours \u2013 queuing notification.")
            queue_alert({"text": message}, now_vnt.isoformat())
        else:
            print("[crypto_trading] Silent hours \u2013 skipped.")
    else:
        print("[crypto_trading] Sending to Discord\u2026")
        send_message(webhook_url, message)

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
