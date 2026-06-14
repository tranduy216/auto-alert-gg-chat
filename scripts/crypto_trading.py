#!/usr/bin/env python3
"""Crypto Trading Signal System

Runs 3 times/day via GitHub Actions cron at 06:00, 12:00, 20:00 VNT.

System (v3):
  Layer 1 – Trend Engine (MA7, MA10, MA20)  → BULLISH / BEARISH / SIDEWAY
  Layer 2 – Execution Engine (MA3, Volume)   → E_SCORE
  3-stage scaling entries with 3x leverage
  Hard capital cap: max 15 % margin per coin

Required environment variables:
  DISCORD_BREAKING_WEBHOOK_URL  – Discord webhook for signal output
  FIREBASE_SERVICE_ACCOUNT     – Firebase service-account JSON (optional, for
                                 state persistence across runs)
"""

import json
import os
import sys
from datetime import datetime
from typing import Any

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.discord_webhook import send_message
from utils.retry_utils import call_with_retry
from utils.firebase_utils import is_firebase_enabled

try:
    import pytz
    _VNT = pytz.timezone("Asia/Ho_Chi_Minh")
    def _now_vnt() -> datetime:
        return datetime.now(_VNT)
except ImportError:
    from datetime import timezone, timedelta
    _VNT_OFFSET = timedelta(hours=7)
    def _now_vnt() -> datetime:
        return datetime.now(timezone.utc) + _VNT_OFFSET

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COINS = ["BTC", "ETH", "BNB", "SOL", "ARB", "LINK"]
SYMBOL_MAP: dict[str, str] = {coin: f"{coin}USDT" for coin in COINS}
BTC_SYMBOL = "BTCUSDT"

TIMEFRAME = "1h"
CANDLE_COUNT = 30

LEVERAGE = 3
MAX_MARGIN_PER_COIN = 0.15
STAGE_MARGIN = 0.05

E_WEIGHT_TREND = 0.7
E_WEIGHT_MOMENTUM = 0.3

STRONG_LONG_THRESHOLD = 3.5
WEAK_LONG_MIN = 2.0
STRONG_SHORT_THRESHOLD = -3.5
WEAK_SHORT_MAX = -2.0

LONG_STOP_ADD = 1.0
LONG_REDUCE = 0.0
LONG_EXIT = -2.0
SHORT_STOP_ADD = -1.0
SHORT_REDUCE = 0.0
SHORT_EXIT = 2.0

BTC_FLASH_CRASH_PCT = -5.0

FIRESTORE_COLLECTION = "crypto_trading_states"


# ---------------------------------------------------------------------------
# Binance API
# ---------------------------------------------------------------------------

def fetch_klines(symbol: str) -> list[dict[str, float | int]]:
    """Fetch OHLCV klines from Binance public API."""
    def _fetch() -> requests.Response:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": TIMEFRAME, "limit": CANDLE_COUNT},
            timeout=15,
        )
        resp.raise_for_status()
        return resp

    response = call_with_retry(
        _fetch,
        resource_name=f"Binance klines {symbol}",
        retry_exceptions=(requests.RequestException,),
    )
    data = response.json()
    return [
        {
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
        for k in data
    ]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _smart_round(v: float) -> float:
    """Round to sensible decimal places based on value magnitude."""
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
    """Simple moving average; first period-1 elements are None."""
    result: list[float | None] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1 : i + 1]) / period)
    return result


def compute_atr(candles: list[dict], period: int = 14) -> float:
    """Average True Range for volatility measurement."""
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


def compute_entry_zone(
    candles: list[dict],
    trend: str,
    signal: str,
    ma7: float,
    ma10: float,
    ma20: float,
) -> dict:
    """Calculate optimal entry price zone and key levels."""
    atr = compute_atr(candles)
    recent_low = min(c["low"] for c in candles[-10:])
    recent_high = max(c["high"] for c in candles[-10:])
    current_close = candles[-1]["close"]

    if signal in ("STRONG_LONG", "WEAK_LONG"):
        support = min(ma20, ma10, recent_low)
        upper_bound = min(current_close * 1.01, ma7)
        zone = {
            "support": _smart_round(support),
            "optimal_entry": _smart_round(max(support, ma10 * 0.99)),
            "upper_bound": _smart_round(upper_bound),
        }
    elif signal in ("STRONG_SHORT", "WEAK_SHORT"):
        resistance = max(ma20, ma10, recent_high)
        lower_bound = max(current_close * 0.99, ma7)
        zone = {
            "lower_bound": _smart_round(lower_bound),
            "optimal_entry": _smart_round(min(resistance, ma10 * 1.01)),
            "resistance": _smart_round(resistance),
        }
    else:
        zone = {
            "near_support": _smart_round(min(ma20, recent_low)),
            "near_resistance": _smart_round(max(ma20, recent_high)),
        }

    zone["atr"] = _smart_round(atr)
    zone["current_price"] = _smart_round(current_close)
    return zone


def compute_entry_prices(
    p0: float, atr: float, trend: str, signal: str,
    vol_ratio: float, s_trend: float, ma7: float, ma10: float, ma20: float,
) -> dict:
    """Compute Entry 2 (pullback) and Entry 3 (momentum) prices per pseudocode."""
    is_long = signal in ("STRONG_LONG", "WEAK_LONG")
    is_short = signal in ("STRONG_SHORT", "WEAK_SHORT")

    if not is_long and not is_short:
        return {
            "entry_2": None,
            "entry_3": None,
            "confidence_2": 0,
            "confidence_3": 0,
        }

    bias_score = min(1.0, max(0.0, abs(s_trend) / 5.0))
    pullback_factor = 1.0 - bias_score

    if vol_ratio > 2.0:
        vol_factor = 1.5
    elif vol_ratio > 1.5:
        vol_factor = 1.3
    elif vol_ratio > 1.0:
        vol_factor = 1.1
    elif vol_ratio > 0.7:
        vol_factor = 1.0
    else:
        vol_factor = 0.8

    if is_long:
        ma_alignment = 1.5 if ma7 > ma10 > ma20 else (1.0 if ma7 > ma10 else 0.75)
    elif is_short:
        ma_alignment = 1.5 if ma7 < ma10 < ma20 else (1.0 if ma7 < ma10 else 0.75)
    else:
        ma_alignment = 1.0

    momentum_factor = vol_factor * ma_alignment

    if is_long:
        e2 = p0 - (0.5 * atr * pullback_factor)
        e3 = p0 + (0.75 * atr * momentum_factor)
    elif is_short:
        e2 = p0 + (0.5 * atr * pullback_factor)
        e3 = p0 - (0.75 * atr * momentum_factor)
    else:
        e2 = p0
        e3 = p0

    # Confidence rates
    confidence_2 = round(min(100, bias_score * 100))
    max_momentum = 2.25  # max vol_factor (1.5) * max ma_alignment (1.5)
    confidence_3 = round(min(100, (momentum_factor / max_momentum) * 100))

    return {
        "entry_2": _smart_round(e2),
        "entry_3": _smart_round(e3),
        "confidence_2": confidence_2,
        "confidence_3": confidence_3,
        "bias_score": round(bias_score, 2),
        "vol_factor": round(vol_factor, 2),
        "ma_alignment": round(ma_alignment, 2),
    }


# ---------------------------------------------------------------------------
# Trend Engine  (Layer 1)
# ---------------------------------------------------------------------------

def evaluate_trend(ma7: float, ma10: float, ma20: float) -> tuple[str, float]:
    """Determine trend direction and S_TREND score (range -5 .. +5).

    Returns (trend_label, s_trend_score).
    """
    ma_max = max(ma7, ma10, ma20)
    ma_min = min(ma7, ma10, ma20)
    spread = (ma_max - ma_min) / ma_min * 100 if ma_min > 0 else 0

    if spread < 0.5:
        return ("SIDEWAY", 0.0)

    if ma7 > ma10 > ma20:
        gap = (ma7 - ma20) / ma20 * 100
        if gap > 3.0:
            return ("BULLISH", 5.0)
        if gap > 1.5:
            return ("BULLISH", 4.0)
        if gap > 0.8:
            return ("BULLISH", 3.0)
        if gap > 0.3:
            return ("BULLISH", 2.0)
        return ("BULLISH", 1.0)

    if ma7 < ma10 < ma20:
        gap = (ma20 - ma7) / ma20 * 100
        if gap > 3.0:
            return ("BEARISH", -5.0)
        if gap > 1.5:
            return ("BEARISH", -4.0)
        if gap > 0.8:
            return ("BEARISH", -3.0)
        if gap > 0.3:
            return ("BEARISH", -2.0)
        return ("BEARISH", -1.0)

    if ma7 > ma20:
        return ("BULLISH", 0.5)
    if ma7 < ma20:
        return ("BEARISH", -0.5)
    return ("SIDEWAY", 0.0)


# ---------------------------------------------------------------------------
# Execution Engine  (Layer 2)
# ---------------------------------------------------------------------------

def compute_momentum_score(
    close: float,
    ma3_current: float,
    ma3_prev: float,
    volume: float,
    vol_ma20: float,
) -> float:
    """Compute S_MOMENTUM score (capped at -5 .. +5)."""
    score = 0.0

    # MA3 position
    diff_pct = (close - ma3_current) / ma3_current * 100 if ma3_current > 0 else 0
    if diff_pct > 0.5:
        score += 2.0
    elif diff_pct > 0.1:
        score += 1.0
    elif diff_pct < -0.5:
        score -= 2.0
    elif diff_pct < -0.1:
        score -= 1.0

    # MA3 slope
    slope_pct = (ma3_current - ma3_prev) / ma3_prev * 100 if ma3_prev > 0 else 0
    if slope_pct > 0.1:
        score += 1.0
    elif slope_pct < -0.1:
        score -= 1.0

    # Volume ratio (spec §6.2)
    vol_ratio = volume / vol_ma20 if vol_ma20 > 0 else 0
    if vol_ratio > 2.0:
        score += 3.0
    elif vol_ratio >= 1.5:
        score += 2.0
    elif vol_ratio >= 1.0:
        score += 1.0
    elif vol_ratio >= 0.7:
        score += 0.0
    else:
        score -= 2.0

    return max(-5.0, min(5.0, score))


# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------

def classify_signal(e_score: float, trend: str) -> str:
    """Map E_SCORE + trend to a signal name."""
    if trend == "SIDEWAY":
        return "WAIT"
    if e_score >= STRONG_LONG_THRESHOLD:
        return "STRONG_LONG"
    if e_score >= WEAK_LONG_MIN:
        return "WEAK_LONG"
    if e_score <= STRONG_SHORT_THRESHOLD:
        return "STRONG_SHORT"
    if e_score <= WEAK_SHORT_MAX:
        return "WEAK_SHORT"
    return "WAIT"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def resolve_action(
    signal: str,
    e_score: float,
    trend: str,
    ma3_current: float,
    ma3_prev: float,
    volume: float,
    vol_ma20: float,
    prev_state: str,
    prev_side: str,
    prev_entry_count: int,
) -> tuple[str, str, str, int]:
    """Return (state, side, action, entry_count).

    state  : NO_POSITION | BUILDING_POSITION | IN_POSITION
    side   : NONE | LONG | SHORT
    action : NO_TRADE | OPEN_LONG_ENTRY_1 | OPEN_SHORT_ENTRY_1
             | ADD_LONG_ENTRY_2 | ADD_SHORT_ENTRY_2
             | ADD_LONG_ENTRY_3 | ADD_SHORT_ENTRY_3
             | REDUCE_LONG | REDUCE_SHORT
             | EXIT_LONG | EXIT_SHORT
             | HOLD
    """
    state = prev_state
    side = prev_side
    entry_count = prev_entry_count
    is_long_signal = signal in ("STRONG_LONG", "WEAK_LONG")
    is_short_signal = signal in ("STRONG_SHORT", "WEAK_SHORT")

    vol_ratio = volume / vol_ma20 if vol_ma20 > 0 else 0
    ma3_slope = (ma3_current - ma3_prev) / ma3_prev * 100 if ma3_prev > 0 else 0

    # ---- FLAT: consider Entry 1 ----
    if state == "NO_POSITION":
        if is_long_signal and trend == "BULLISH" and e_score >= WEAK_LONG_MIN:
            return ("BUILDING_POSITION", "LONG", "OPEN_LONG_ENTRY_1", 1)
        if is_short_signal and trend == "BEARISH" and e_score <= WEAK_SHORT_MAX:
            return ("BUILDING_POSITION", "SHORT", "OPEN_SHORT_ENTRY_1", 1)
        return ("NO_POSITION", "NONE", "NO_TRADE", 0)

    # ---- BUILDING_POSITION ----
    if state == "BUILDING_POSITION":
        # Risk management (by position side)
        if side == "LONG":
            if e_score < LONG_EXIT:
                return ("NO_POSITION", "NONE", "EXIT_LONG", 0)
            if e_score < LONG_REDUCE:
                return ("NO_POSITION", "NONE", "REDUCE_LONG", 0)
            if e_score < LONG_STOP_ADD:
                return (state, side, "HOLD", entry_count)
        elif side == "SHORT":
            if e_score > SHORT_EXIT:
                return ("NO_POSITION", "NONE", "EXIT_SHORT", 0)
            if e_score > SHORT_REDUCE:
                return ("NO_POSITION", "NONE", "REDUCE_SHORT", 0)
            if e_score > SHORT_STOP_ADD:
                return (state, side, "HOLD", entry_count)

        # Scaling logic
        if entry_count == 1 and side == "LONG":
            if ma3_slope > 0 and vol_ratio > 1.0 and is_long_signal:
                return ("BUILDING_POSITION", "LONG", "ADD_LONG_ENTRY_2", 2)
        if entry_count == 1 and side == "SHORT":
            if ma3_slope < 0 and vol_ratio > 1.0 and is_short_signal:
                return ("BUILDING_POSITION", "SHORT", "ADD_SHORT_ENTRY_2", 2)

        if entry_count == 2 and side == "LONG":
            if vol_ratio > 2.0 and is_long_signal:
                return ("IN_POSITION", "LONG", "ADD_LONG_ENTRY_3", 3)
        if entry_count == 2 and side == "SHORT":
            if vol_ratio > 2.0 and is_short_signal:
                return ("IN_POSITION", "SHORT", "ADD_SHORT_ENTRY_3", 3)

        return (state, side, "HOLD", entry_count)

    # ---- IN_POSITION: only risk management ----
    if state == "IN_POSITION":
        if side == "LONG":
            if e_score < LONG_EXIT:
                return ("NO_POSITION", "NONE", "EXIT_LONG", 0)
            if e_score < LONG_REDUCE:
                return ("BUILDING_POSITION", "LONG", "REDUCE_LONG", 1)
        elif side == "SHORT":
            if e_score > SHORT_EXIT:
                return ("NO_POSITION", "NONE", "EXIT_SHORT", 0)
            if e_score > SHORT_REDUCE:
                return ("BUILDING_POSITION", "SHORT", "REDUCE_SHORT", 1)
        return (state, side, "HOLD", entry_count)

    return (state, side, "HOLD", entry_count)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

def check_kill_switch(btc_candles: list[dict]) -> bool:
    """Return True if market-wide emergency detected."""
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
        return {"state": "NO_POSITION", "side": "NONE", "entry_count": 0}
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
    return {"state": "NO_POSITION", "side": "NONE", "entry_count": 0}


def save_state(
    coin: str, state: str, side: str, entry_count: int,
    e_score: float, signal: str, action: str, timestamp: str,
) -> None:
    """Persist position state to Firestore."""
    db = _get_db()
    if db is None:
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(coin)
        call_with_retry(
            lambda: doc_ref.set({
                "state": state,
                "side": side,
                "entry_count": entry_count,
                "e_score": round(e_score, 2),
                "signal": signal,
                "action": action,
                "timestamp": timestamp,
            }),
            resource_name=f"Firestore save {coin} state",
        )
    except Exception as exc:
        print(f"[crypto_trading] Warning: could not save state for {coin}: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _signal_icon(result: dict) -> str:
    """Return icon for the coin heading based on signal/action."""
    sig = result["signal"]
    act = result["action"]
    if act in ("EXIT_LONG", "EXIT_SHORT", "KILL_SWITCH"):
        return "❗❗❗"
    if act in ("REDUCE_LONG", "REDUCE_SHORT"):
        return "🟡"
    if sig == "STRONG_LONG":
        return "💚"
    if sig == "WEAK_LONG":
        return "🟢"
    if sig == "STRONG_SHORT":
        return "🔴"
    if sig == "WEAK_SHORT":
        return "🟠"
    return "🟡"


def compute_position_state(state: str, side: str, entry_count: int) -> str:
    """Derive standardized position state."""
    if state == "NO_POSITION":
        return "FLAT"
    if side == "LONG":
        if state == "IN_POSITION":
            return f"LONG_ENTRY_{entry_count}"
        return f"LONG_ENTRY_{entry_count}"
    if side == "SHORT":
        if state == "IN_POSITION":
            return f"SHORT_ENTRY_{entry_count}"
        return f"SHORT_ENTRY_{entry_count}"
    return "FLAT"


def compute_next_rules(position_state: str, signal: str, e_score: float, trend: str) -> list[str]:
    """Return list of next-action rules based on current position."""
    rules: list[str] = []
    if position_state == "FLAT":
        if signal in ("STRONG_LONG", "WEAK_LONG") and trend == "BULLISH":
            rules.append("OPEN_LONG_ENTRY_1 if score >= 2.0")
        elif signal in ("STRONG_SHORT", "WEAK_SHORT") and trend == "BEARISH":
            rules.append("OPEN_SHORT_ENTRY_1 if score <= -2.0")
        else:
            rules.append("Wait for trend confirmation + score threshold")
        return rules

    if position_state.startswith("LONG"):
        if position_state in ("LONG_ENTRY_1",):
            rules.append("LONG_ENTRY_2 (30% money) if MA3 recovery + volume > 1x")
        if position_state in ("LONG_ENTRY_1", "LONG_ENTRY_2"):
            rules.append("LONG_ENTRY_3 (40% money) if breakout + volume spike > 2x")
        rules.append("REDUCE_LONG if score < 0")
        rules.append("EXIT_LONG if score < -2")

    if position_state.startswith("SHORT"):
        if position_state in ("SHORT_ENTRY_1",):
            rules.append("SHORT_ENTRY_2 (30% money) if MA3 rejection + volume > 1x")
        if position_state in ("SHORT_ENTRY_1", "SHORT_ENTRY_2"):
            rules.append("SHORT_ENTRY_3 (40% money) if breakdown + volume spike > 2x")
        rules.append("REDUCE_SHORT if score > 0")
        rules.append("EXIT_SHORT if score > 2")

    return rules


def _action_text(result: dict) -> str:
    """Human-readable action description."""
    a = result["action"]
    z = result.get("entry_zone", {})
    price = z.get("optimal_entry") or z.get("current_price", "?")

    if a == "KILL_SWITCH": return "Emergency exit (kill switch)"
    if a == "NO_TRADE": return "No action – wait for setup"
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
    return a


def _optimal_text(result: dict) -> str:
    """Optimal entry price."""
    z = result.get("entry_zone", {})
    if result["signal"] in ("STRONG_LONG", "WEAK_LONG", "STRONG_SHORT", "WEAK_SHORT"):
        return f"${z.get('optimal_entry', '?')}"
    return "-"


def _zone_text(result: dict) -> str:
    """Entry zone range."""
    z = result.get("entry_zone", {})
    sig = result["signal"]
    if sig in ("STRONG_LONG", "WEAK_LONG"):
        return f"${z.get('support', '?')} – ${z.get('upper_bound', '?')} (ATR: ${z.get('atr', '?')})"
    if sig in ("STRONG_SHORT", "WEAK_SHORT"):
        return f"${z.get('lower_bound', '?')} – ${z.get('resistance', '?')} (ATR: ${z.get('atr', '?')})"
    return f"Support ${z.get('near_support', '?')} – Resistance ${z.get('near_resistance', '?')}"


def format_detail(result: dict) -> str:
    """Detailed per-coin section (no Action block, shown at top once)."""
    icon = _signal_icon(result)
    position = result["position_state"]
    action = _action_text(result)
    optimal = _optimal_text(result)
    zone = _zone_text(result)
    score = result["e_score"]
    z = result.get("entry_zone", {})
    e2 = z.get("entry_2")
    e3 = z.get("entry_3")
    heading = f"## {icon} {result['coin']}" if icon else f"## {result['coin']}"
    score_str = f"{score:+.1f}" if score != 0 else "0.0"
    lines = [heading, f"STAGE: {position}. Score={score_str}", f"ACTION: {action}"]
    lines.append(f"OPTIMAL: {optimal}. ZONE: {zone}")
    sig = result["signal"]
    if sig in ("STRONG_LONG", "WEAK_LONG", "STRONG_SHORT", "WEAK_SHORT") and e2 is not None and e3 is not None:
        c2 = z.get("confidence_2", "?")
        c3 = z.get("confidence_3", "?")
        prefix = "LONG" if sig in ("STRONG_LONG", "WEAK_LONG") else "SHORT"
        lines.append(f"{prefix} ENTRY2: ${e2} (confidence {c2}%) | {prefix} ENTRY3: ${e3} (confidence {c3}%)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-coin analysis pipeline
# ---------------------------------------------------------------------------

def analyse_coin(
    coin: str,
    candles: list[dict],
    kill_switch_active: bool,
) -> dict:
    """Run full analysis pipeline for one coin; return output dict."""
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    # Indicators
    ma3_all = sma(closes, 3)
    ma7_all = sma(closes, 7)
    ma10_all = sma(closes, 10)
    ma20_all = sma(closes, 20)
    vol_ma20_all = sma(volumes, 20)

    ma3 = ma3_all[-1] if ma3_all[-1] is not None else closes[-1]
    ma3_prev = ma3_all[-2] if len(ma3_all) > 1 and ma3_all[-2] is not None else ma3
    ma7 = ma7_all[-1] if ma7_all[-1] is not None else closes[-1]
    ma10 = ma10_all[-1] if ma10_all[-1] is not None else closes[-1]
    ma20 = ma20_all[-1] if ma20_all[-1] is not None else closes[-1]
    vol_ma20 = vol_ma20_all[-1] if vol_ma20_all[-1] is not None else volumes[-1]

    last_close = closes[-1]
    last_volume = volumes[-1]

    # Layer 1 – Trend Engine
    trend, s_trend = evaluate_trend(ma7, ma10, ma20)

    # Layer 2 – Execution Engine
    s_momentum = compute_momentum_score(
        last_close, ma3, ma3_prev, last_volume, vol_ma20,
    )
    e_score = round(E_WEIGHT_TREND * s_trend + E_WEIGHT_MOMENTUM * s_momentum, 2)

    # Signal classification
    signal = classify_signal(e_score, trend)

    # Entry zone
    entry_zone = compute_entry_zone(candles, trend, signal, ma7, ma10, ma20)

    # Entry 2 & 3 prices
    vol_ratio = last_volume / vol_ma20 if vol_ma20 > 0 else 0
    p0 = entry_zone.get("optimal_entry") or last_close
    entry_prices = compute_entry_prices(
        p0, entry_zone.get("atr", 0), trend, signal,
        vol_ratio, s_trend, ma7, ma10, ma20,
    )
    entry_zone.update(entry_prices)

    # Kill-switch override
    if kill_switch_active:
        return {
            "coin": coin,
            "trend": trend,
            "e_score": e_score,
            "signal": signal,
            "position_state": "FLAT",
            "action": "KILL_SWITCH",
            "leverage": LEVERAGE,
            "entry_zone": entry_zone,
            "next_rules": ["Wait for market to stabilise"],
            "timestamp": _now_vnt().isoformat(),
        }

    # Load previous state
    prev = load_state(coin)
    prev_state = prev.get("state", "NO_POSITION")
    prev_side = prev.get("side", "NONE")
    prev_entry_count = prev.get("entry_count", 0)

    # State machine
    state, side, action, entry_count = resolve_action(
        signal, e_score, trend,
        ma3, ma3_prev,
        last_volume, vol_ma20,
        prev_state, prev_side, prev_entry_count,
    )

    position_state = compute_position_state(state, side, entry_count)
    next_rules = compute_next_rules(position_state, signal, e_score, trend)

    output = {
        "coin": coin,
        "trend": trend,
        "e_score": e_score,
        "signal": signal,
        "position_state": position_state,
        "action": action,
        "leverage": LEVERAGE,
        "entry_zone": entry_zone,
        "next_rules": next_rules,
        "timestamp": _now_vnt().isoformat(),
    }

    # Persist state
    save_state(
        coin, state, side, entry_count,
        e_score, signal, action, output["timestamp"],
    )

    return output


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    webhook_url = os.environ.get("DISCORD_BREAKING_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_BREAKING_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(1)

    now_vnt = _now_vnt()
    print(f"[crypto_trading] Starting at {now_vnt.strftime('%Y-%m-%d %H:%M %Z')}")

    # Kill-switch check (BTC)
    print("[crypto_trading] Fetching BTC data for kill-switch…")
    try:
        btc_candles = fetch_klines(BTC_SYMBOL)
    except requests.RequestException as exc:
        print(f"[crypto_trading] Fatal: cannot fetch BTC data: {exc}",
              file=sys.stderr)
        sys.exit(1)

    kill_switch = check_kill_switch(btc_candles)
    if kill_switch:
        print("[crypto_trading] KILL SWITCH ACTIVE – market stress detected!")
    else:
        print("[crypto_trading] Kill switch not triggered.")

    # Analyse each coin
    results: list[dict[str, Any]] = []
    for coin in COINS:
        symbol = SYMBOL_MAP[coin]
        print(f"[crypto_trading] Fetching {symbol}…")
        try:
            candles = fetch_klines(symbol)
        except requests.RequestException as exc:
            print(f"[crypto_trading] Warning: cannot fetch {symbol}: {exc}",
                  file=sys.stderr)
            continue

        print(f"[crypto_trading] Analysing {coin}…")
        result = analyse_coin(coin, candles, kill_switch)
        results.append(result)
        print(
            f"  {coin}: trend={result['trend']} "
            f"E_SCORE={result['e_score']:.2f} "
            f"signal={result['signal']} "
            f"action={result['action']}"
        )

    # Build combined action summary (always show LONG + SHORT rules)
    action_blocks: list[str] = [
        "LONG:\n"
        "  \u2022 OPEN if score >= 2.0 and trend bullish\n"
        "  \u2022 ENTRY2 (30% money) if MA3 recovery + volume > 1x\n"
        "  \u2022 ENTRY3 (40% money) if breakout + volume spike > 2x\n"
        "  \u2022 REDUCE if score < 0\n"
        "  \u2022 EXIT if score < -2",
        "SHORT:\n"
        "  \u2022 OPEN if score <= -2.0 and trend bearish\n"
        "  \u2022 ENTRY2 (30% money) if MA3 rejection + volume > 1x\n"
        "  \u2022 ENTRY3 (40% money) if breakdown + volume spike > 2x\n"
        "  \u2022 REDUCE if score > 0\n"
        "  \u2022 EXIT if score > 2",
    ]

    ks_flag = " 🚨 KILL SWITCH" if kill_switch else ""
    header = (
        f"**Crypto Trading Signals**{ks_flag}\n"
        f"{now_vnt.strftime('%d/%m/%Y %I:%M %p (VNT)')} | {LEVERAGE}x | 15%/coin"
    )
    active = [r for r in results if r['signal'] not in ('WAIT', 'NA')]

    separator = "\n⋆｡°✩ — ⋆｡°✩ — ⋆｡°✩\n"

    if not active:
        message = f"{header}\n\nNo action for all coin.{separator}"
    else:
        lines = [header, "", "Action:", *action_blocks, ""]
        for r in active:
            lines.append(format_detail(r))
            lines.append("")
        message = "\n".join(lines) + separator

    print("[crypto_trading] Sending to Discord…")
    send_message(webhook_url, message)
    print("[crypto_trading] Done.")


def run() -> None:
    try:
        main()
    except Exception as exc:
        webhook_url = os.environ.get("DISCORD_BREAKING_WEBHOOK_URL")
        if webhook_url:
            send_message(webhook_url, f"Cannot run due to {exc}")
        raise


if __name__ == "__main__":
    run()
