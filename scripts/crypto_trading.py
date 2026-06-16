#!/usr/bin/env python3
"""Crypto Trading Signal System (v4)

Runs 3 times/day via GitHub Actions cron at 06:00, 12:00, 20:00 VNT.

System (v4):
  Layer 1 – Trend Engine (3D candles, MA7/MA10/MA20) → TrendScore ±3
  Layer 2 – Execution Engine (1D candles, MA3/MA7/Vol/ATR14) → weighted probs
  3-stage scaling entries with 3x leverage
  Hard capital cap: max 15 % margin per coin

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
    _VNT_TZ = timezone(timedelta(hours=7), name="VNT")
    def _now_vnt() -> datetime:
        return datetime.now(_VNT_TZ)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COINS = ["BTC", "ETH", "BNB", "SOL", "ARB", "LINK", "PAXG"]
SYMBOL_MAP: dict[str, str] = {coin: f"{coin}USDT" for coin in COINS}
BTC_SYMBOL = "BTCUSDT"

CANDLE_COUNT = 30

LEVERAGE = 3
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

def _fetch_binance(symbol: str, interval: str = "1d", host: str = "api.binance.com") -> list[dict] | None:
    try:
        resp = requests.get(
            f"https://{host}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": CANDLE_COUNT},
            timeout=15,
        )
        resp.raise_for_status()
        return _parse_binance_klines(resp.json())
    except Exception as e:
        print(f"  [{host}] {symbol} failed: {e}")
        return None

def _fetch_okx(symbol: str, interval: str = "1D") -> list[dict] | None:
    okx_map = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT", "BNBUSDT": "BNB-USDT",
               "SOLUSDT": "SOL-USDT", "ARBUSDT": "ARB-USDT", "LINKUSDT": "LINK-USDT",
               "PAXGUSDT": "PAXG-USDT"}
    inst_id = okx_map.get(symbol)
    if not inst_id:
        return None
    try:
        resp = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": inst_id, "bar": interval, "limit": CANDLE_COUNT},
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
    ("Binance", None),
    ("Binance US", "api.binance.us"),
    ("Binance GCP", "api-gcp.binance.com"),
    ("OKX", None),
]
_ACTIVE_SOURCE_IDX = 0

def _build_source_fns(symbol: str, interval: str = "1d") -> list[tuple[str, callable]]:
    fns: list[tuple[str, callable]] = []
    okx_iv = OKX_INTERVAL_MAP.get(interval, interval)
    for name, host in _SOURCE_LIST:
        if name == "OKX":
            fns.append((name, lambda s=symbol, iv=okx_iv: _fetch_okx(s, iv)))
        elif host:
            fns.append((name, lambda s=symbol, iv=interval, h=host: _fetch_binance(s, iv, h)))
        else:
            fns.append((name, lambda s=symbol, iv=interval: _fetch_binance(s, iv)))
    cg_id = COINGECKO_IDS.get(symbol)
    if cg_id:
        fns.append(("CoinGecko", lambda s=symbol, c=cg_id, iv=interval: _parse_coingecko_klines(c, s, iv)))
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

def fetch_klines(symbol: str, interval: str = "1d") -> list[dict[str, float | int]]:
    """Fetch OHLCV klines, trying sources with adaptive fallback."""
    global _ACTIVE_SOURCE_IDX
    sources = _build_source_fns(symbol, interval)
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
    return close > ma7 and volume_score >= 0.4


def compute_entry1_signal_short(close: float, ma7: float, volume_score: float) -> bool:
    return close < ma7 and volume_score >= 0.4


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
) -> tuple[str, str]:
    """Return (position_state, action)."""

    if prev_pos_state == "FLAT":
        if trend_score >= 2 and entry1_long:
            return ("LONG_ENTRY_1", "OPEN_LONG_ENTRY_1")
        if trend_score <= -2 and entry1_short:
            return ("SHORT_ENTRY_1", "OPEN_SHORT_ENTRY_1")
        return ("FLAT", "NO_TRADE")

    if prev_pos_state == "LONG_ENTRY_1":
        if p_long_entry2 >= 0.70:
            return ("LONG_ENTRY_2", "ADD_LONG_ENTRY_2")
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        if trend_score < 0:
            return ("FLAT", "REDUCE_LONG")
        return ("LONG_ENTRY_1", "HOLD")

    if prev_pos_state == "LONG_ENTRY_2":
        if p_long_entry3 >= 0.75:
            return ("LONG_ENTRY_3", "ADD_LONG_ENTRY_3")
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        return ("LONG_ENTRY_2", "HOLD")

    if prev_pos_state == "LONG_ENTRY_3":
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        return ("LONG_ENTRY_3", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_1":
        if p_short_entry2 >= 0.70:
            return ("SHORT_ENTRY_2", "ADD_SHORT_ENTRY_2")
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        if trend_score > 0:
            return ("FLAT", "REDUCE_SHORT")
        return ("SHORT_ENTRY_1", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_2":
        if p_short_entry3 >= 0.75:
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
        return {"position_state": "FLAT", "last_action": ""}
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
) -> None:
    """Persist position state to Firestore."""
    db = _get_db()
    if db is None:
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION).document(coin)
        call_with_retry(
            lambda: doc_ref.set({
                "position_state": position_state,
                "action": action,
                "last_action": action,
                "trend_score": trend_score,
                "entry2_prob": round(entry2_prob, 2),
                "entry3_prob": round(entry3_prob, 2),
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
    act = result["action"]
    if act in ("EXIT_LONG", "EXIT_SHORT", "KILL_SWITCH"):
        return "❗❗❗"
    if act in ("REDUCE_LONG", "REDUCE_SHORT"):
        return "🟡"
    if "LONG" in act:
        return "💚"
    if "SHORT" in act:
        return "🔴"
    return "🟡"


def compute_next_rules(position_state: str) -> list[str]:
    rules: list[str] = []
    if position_state == "FLAT":
        rules.append("OPEN_LONG if TrendScore >= +2 and Entry1Signal")
        rules.append("OPEN_SHORT if TrendScore <= -2 and Entry1Signal")
        return rules
    if position_state.startswith("LONG"):
        if position_state == "LONG_ENTRY_1":
            rules.append("ADD ENTRY2 if P_Entry2 >= 0.70")
            rules.append("REDUCE if TrendScore < 0 | EXIT if TrendScore < -2")
        elif position_state == "LONG_ENTRY_2":
            rules.append("ADD ENTRY3 if P_Entry3 >= 0.75")
            rules.append("EXIT if TrendScore < -2")
        elif position_state == "LONG_ENTRY_3":
            rules.append("EXIT if TrendScore < -2")
    elif position_state.startswith("SHORT"):
        if position_state == "SHORT_ENTRY_1":
            rules.append("ADD ENTRY2 if P_Entry2 >= 0.70")
            rules.append("REDUCE if TrendScore > 0 | EXIT if TrendScore > 2")
        elif position_state == "SHORT_ENTRY_2":
            rules.append("ADD ENTRY3 if P_Entry3 >= 0.75")
            rules.append("EXIT if TrendScore > 2")
        elif position_state == "SHORT_ENTRY_3":
            rules.append("EXIT if TrendScore > 2")
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
) -> dict:
    ts = _now_vnt().isoformat()

    # --- Trend Engine (3D) ---
    closes_3d = [c["close"] for c in candles_3d]

    ma7_3d_all = sma(closes_3d, 7)
    ma10_3d_all = sma(closes_3d, 10)
    ma20_3d_all = sma(closes_3d, 20)

    ma7_3d = ma7_3d_all[-1] if ma7_3d_all[-1] is not None else closes_3d[-1]
    ma10_3d = ma10_3d_all[-1] if ma10_3d_all[-1] is not None else closes_3d[-1]
    ma20_3d = ma20_3d_all[-1] if ma20_3d_all[-1] is not None else closes_3d[-1]

    trend_label, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
    ts_val = trend_strength(trend_score)

    # --- Execution Engine (1D) ---
    closes_1d = [c["close"] for c in candles_1d]
    highs_1d = [c["high"] for c in candles_1d]
    lows_1d = [c["low"] for c in candles_1d]
    volumes_1d = [c["volume"] for c in candles_1d]

    ma3_1d_all = sma(closes_1d, 3)
    ma7_1d_all = sma(closes_1d, 7)
    ma10_1d_all = sma(closes_1d, 10)
    vol_ma20_1d_all = sma(volumes_1d, 20)

    ma3_1d = ma3_1d_all[-1] if ma3_1d_all[-1] is not None else closes_1d[-1]
    ma7_1d = ma7_1d_all[-1] if ma7_1d_all[-1] is not None else closes_1d[-1]
    ma10_1d = ma10_1d_all[-1] if ma10_1d_all[-1] is not None else closes_1d[-1]
    vol_ma20_1d = vol_ma20_1d_all[-1] if vol_ma20_1d_all[-1] is not None else volumes_1d[-1]

    last_close = closes_1d[-1]
    last_low = lows_1d[-1]
    last_high = highs_1d[-1]
    last_volume = volumes_1d[-1]

    atr_1d = compute_atr(candles_1d, 14)

    # Scores
    volume_score = compute_volume_score(last_volume, vol_ma20_1d)
    reaction_score_long = compute_reaction_score_long(last_close, last_low, ma3_1d)
    reaction_score_short = compute_reaction_score_short(last_close, last_high, ma3_1d)

    resistance = compute_resistance(candles_1d, ma7_1d, ma10_1d)
    support = compute_support(candles_1d, ma7_1d, ma10_1d)
    break_score_long = compute_break_score_long(last_close, resistance, atr_1d)
    break_score_short = compute_break_score_short(last_close, support, atr_1d)

    atr_score = compute_atr_score(atr_1d, last_close)

    # Entry 1 signals
    entry1_long = compute_entry1_signal_long(last_close, ma7_1d, volume_score)
    entry1_short = compute_entry1_signal_short(last_close, ma7_1d, volume_score)

    # Entry 2 / 3 probabilities
    ts_long = max(0.0, ts_val)
    ts_short = max(0.0, -ts_val)

    p_long_entry2 = min(1.0, max(0.0, 0.35 * ts_long + 0.25 * reaction_score_long
                                  + 0.25 * volume_score + 0.15 * atr_score))
    p_short_entry2 = min(1.0, max(0.0, 0.35 * ts_short + 0.25 * reaction_score_short
                                   + 0.25 * volume_score + 0.15 * atr_score))
    p_long_entry3 = min(1.0, max(0.0, 0.30 * ts_long + 0.20 * reaction_score_long
                                  + 0.30 * volume_score + 0.20 * break_score_long))
    p_short_entry3 = min(1.0, max(0.0, 0.30 * ts_short + 0.20 * reaction_score_short
                                   + 0.30 * volume_score + 0.20 * break_score_short))

    # Entry zone
    entry_zone = compute_entry_zone_v4(candles_1d, trend_score, ma7_1d, ma10_1d, atr_1d)

    # Kill-switch override
    if kill_switch_active:
        return {
            "coin": coin,
            "trend": trend_label,
            "trend_score": trend_score,
            "entry2_prob": 0.0,
            "entry3_prob": 0.0,
            "position_state": "FLAT",
            "action": "KILL_SWITCH",
            "leverage": LEVERAGE,
            "entry_zone": entry_zone,
            "volume_score": volume_score,
            "reaction_score": reaction_score_long if trend_score >= 0 else reaction_score_short,
            "atr_score": atr_score,
            "break_score": break_score_long if trend_score >= 0 else break_score_short,
            "next_rules": ["Wait for market to stabilise"],
            "timestamp": ts,
        }

    # Load previous state
    prev = load_state(coin)
    prev_pos_state = prev.get("position_state", "FLAT")

    # State machine
    pos_state, action = resolve_action_v4(
        trend_score,
        entry1_long,
        entry1_short,
        p_long_entry2,
        p_short_entry2,
        p_long_entry3,
        p_short_entry3,
        prev_pos_state,
    )

    next_rules = compute_next_rules(pos_state)

    output = {
        "coin": coin,
        "trend": trend_label,
        "trend_score": trend_score,
        "entry2_prob": round(max(p_long_entry2, p_short_entry2), 2),
        "entry3_prob": round(max(p_long_entry3, p_short_entry3), 2),
        "position_state": pos_state,
        "action": action,
        "leverage": LEVERAGE,
        "entry_zone": entry_zone,
        "volume_score": volume_score,
        "reaction_score": reaction_score_long if trend_score >= 0 else reaction_score_short,
        "atr_score": atr_score,
        "break_score": break_score_long if trend_score >= 0 else break_score_short,
        "next_rules": next_rules,
        "timestamp": ts,

    }

    # Persist state
    save_state(
        coin, pos_state, action, trend_score,
        output["entry2_prob"], output["entry3_prob"], ts,
    )

    return output


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

    # Kill-switch check (BTC default 1d)
    print("[crypto_trading] Fetching BTC data for kill-switch\u2026")
    try:
        btc_candles = fetch_klines(BTC_SYMBOL)
    except requests.RequestException as exc:
        print(f"[crypto_trading] Fatal: cannot fetch BTC data: {exc}",
              file=sys.stderr)
        sys.exit(1)

    kill_switch = check_kill_switch(btc_candles)
    if kill_switch:
        print("[crypto_trading] KILL SWITCH ACTIVE \u2013 market stress detected!")
    else:
        print("[crypto_trading] Kill switch not triggered.")

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
        result = analyse_coin(coin, candles_3d, candles_1d, kill_switch)
        results.append(result)
        print(
            f"  {coin}: trend={result['trend']} "
            f"TrendScore={result['trend_score']:+d} "
            f"state={result['position_state']} "
            f"action={result['action']}"
        )

    # Filter to coins with real actions (skip NO_TRADE / HOLD)
    changed = [r for r in results if r['action'] not in ('NO_TRADE', 'HOLD')]

    # Build action summary
    action_blocks: list[str] = [
        "LONG:\n"
        "  \u2022 OPEN if TrendScore >= +2 and Entry1Signal\n"
        "  \u2022 ADD ENTRY2 if P_Entry2 >= 0.70\n"
        "  \u2022 ADD ENTRY3 if P_Entry3 >= 0.75\n"
        "  \u2022 REDUCE if TrendScore < 0\n"
        "  \u2022 EXIT if TrendScore < -2",
        "SHORT:\n"
        "  \u2022 OPEN if TrendScore <= -2 and Entry1Signal\n"
        "  \u2022 ADD ENTRY2 if P_Entry2 >= 0.70\n"
        "  \u2022 ADD ENTRY3 if P_Entry3 >= 0.75\n"
        "  \u2022 REDUCE if TrendScore > 0\n"
        "  \u2022 EXIT if TrendScore > 2",
    ]

    ks_flag = " \U0001f6a8 KILL SWITCH" if kill_switch else ""
    header = (
        f"**Crypto Trading Signals (v4)**{ks_flag}\n"
        f"{now_vnt.strftime('%d/%m/%Y %I:%M %p (VNT)')} | {LEVERAGE}x | 15%/coin"
    )

    # Urgent signals: any real action → send immediately (runs hourly)
    urgent = any(r['action'] not in ('NO_TRADE', 'HOLD') for r in results)

    # Scheduled VNT hours: always send summary (5, 10, 15, 21)
    scheduled_hours = {5, 10, 15, 21}
    is_scheduled = now_vnt.hour in scheduled_hours

    if not urgent and not is_scheduled:
        print("[crypto_trading] Skipping – no urgent signal and off-schedule.")
        return

    separator = "\n\u22c6\u0451\u00b0\u271d\u00a0\u2014 \u22c6\u0451\u00b0\u271d\u00a0\u2014 \u22c6\u0451\u00b0\u271d\n"

    if not changed:
        message = f"{header}\n\nNo action for all coin.{separator}"
    else:
        lines = [header, "", "Action:", *action_blocks, ""]
        for r in changed:
            lines.append(format_detail(r))
            lines.append("")
        message = "\n".join(lines) + separator

    print("[crypto_trading] Sending to Discord\u2026")
    send_message(webhook_url, message)
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
