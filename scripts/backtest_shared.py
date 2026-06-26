"""
Shared backtest logic — constants, helpers, data loading.
All backtest files should import from here to avoid duplication.
"""
import json, sys, datetime, requests, time
from pathlib import Path

def sma(values, period):
    """Simple Moving Average."""
    period = int(period)
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1 : i + 1]) / period)
    return result

# ── Constants ──

BASE = 10000
ENTRY_PCT = 0.015       # 1.5% of equity per entry (including leverage)
TRAIL_PCT = 0.80        # 20% trailing stop from extreme
MA_BUF = 0.03           # 3% buffer default
MA_PERIOD = 20          # MA period default
PYRAMID_ROI_DEFAULT = 5
TP_SCHEDULE = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
BTC_SHORT_TP = [(4, 0.20), (8, 0.20), (12, 0.20), (16, 0.20), (20, 0.20)]
# Short TP ladder: 20%@4%, 20%@8%, 20%@12%, 20%@16%, 20%@20% = 100%
MAX_CAP = 0.75          # max margin deployed (% of total asset value)
FEE_RATE = 0.0005       # 0.05% per side
EXT_BLOCK_PCT = 25      # block adds when price >25% from extreme entry


def fee_factor(lev):
    """Factor applied to PnL for round-trip fees."""
    return 1 - 2 * FEE_RATE * lev


# ── Data Loading ──

def load_data(filepath=None):
    """Load 12h klines, aggregate pairwise → 1d bars."""
    p = Path(filepath) if filepath else Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f:
        raw = json.load(f)
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({
                'close': b2[-1]['close'],
                'high': max(x['high'] for x in b2),
                'low': min(x['low'] for x in b2),
                'volume': sum(x['volume'] for x in b2),
                'time': b2[0]['open_time'],
            })
        data[sym] = daily
    return data


def fetch_binance(symbol, days=600):
    """Fetch klines from Binance, aggregate 12h → 1d bars."""
    try:
        url = 'https://api.binance.com/api/v3/klines'
        start_ms = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp() * 1000)
        candles = []
        while True:
            params = {'symbol': symbol, 'interval': '12h', 'startTime': start_ms, 'limit': 1000}
            raw = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, params=params, timeout=30)
                    resp.raise_for_status()
                    raw = resp.json()
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"[backtest_shared] Binance {symbol} page retry {attempt+1}/2: {e}", file=sys.stderr)
                        time.sleep(0.5)
                    else:
                        raise
            if not raw or isinstance(raw, dict): break
            candles.extend(raw); start_ms = raw[-1][6] + 1
            if len(raw) < 1000: break
            time.sleep(0.3)
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({
                'close': float(b2[-1][4]), 'high': max(float(x[2]) for x in b2),
                'low': min(float(x[3]) for x in b2), 'volume': sum(float(x[5]) for x in b2),
                'time': b2[0][0],
            })
        print(f"[backtest_shared] Binance {symbol}: {len(daily)} daily bars", file=sys.stderr)
        return daily
    except Exception as e:
        print(f"[backtest_shared] Binance {symbol} fetch failed: {e}", file=sys.stderr)
        return []


def fetch_paxg(from_ts=None):
    """Fetch PAXGUSDT 12h klines from Binance, aggregate → 1d bars."""
    try:
        if from_ts is None:
            from_ts = int(datetime.datetime(2022, 1, 1).timestamp() * 1000)
        url = 'https://api.binance.com/api/v3/klines'
        candles = []
        while True:
            params = {'symbol': 'PAXGUSDT', 'interval': '12h',
                      'startTime': from_ts, 'limit': 1000}
            raw = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, params=params, timeout=30)
                    resp.raise_for_status()
                    raw = resp.json()
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"[backtest_shared] PAXG page retry {attempt+1}/2: {e}", file=sys.stderr)
                        time.sleep(0.5)
                    else:
                        raise
            if not raw or isinstance(raw, dict):
                break
            candles.extend(raw)
            from_ts = raw[-1][6] + 1
            if len(raw) < 1000:
                break
            time.sleep(0.5)
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({
                'close': float(b2[-1][4]),
                'high': max(float(x[2]) for x in b2),
                'low': min(float(x[3]) for x in b2),
                'volume': sum(float(x[5]) for x in b2),
                'time': b2[0][0],
            })
        print(f"[backtest_shared] Binance PAXG: {len(daily)} daily bars", file=sys.stderr)
        return daily
    except Exception as e:
        print(f"[backtest_shared] Binance PAXG fetch failed: {e}", file=sys.stderr)
        return []


def fetch_candles_okx(symbol, days=600):
    """Fetch OHLCV daily candles from OKX (primary data source). Returns 1d bars or None on failure."""
    try:
        okx_symbol = symbol.replace('USDT', '-USDT')
        url = 'https://www.okx.com/api/v5/market/candles'
        all_candles = []
        before = ''
        while len(all_candles) < days:
            params = {'instId': okx_symbol, 'bar': '1D', 'limit': min(300, days - len(all_candles))}
            if before:
                params['before'] = before
            data = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, params=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"[backtest_shared] OKX {symbol} page retry {attempt+1}/2: {e}", file=sys.stderr)
                        time.sleep(0.5)
                    else:
                        raise
            if data.get('code') != '0':
                print(f"[backtest_shared] OKX {symbol} API error: {data.get('msg', 'unknown')}", file=sys.stderr)
                break
            candles = data.get('data', [])
            if not candles:
                break
            all_candles.extend(candles)
            before = candles[-1][0]
            if len(candles) < params['limit']:
                break
            time.sleep(0.3)
        if not all_candles:
            print(f"[backtest_shared] OKX returned 0 bars for {symbol}", file=sys.stderr)
            return None
        all_candles = list(reversed(all_candles))
        daily = []
        for k in all_candles:
            daily.append({
                'close': float(k[4]),
                'high': float(k[2]),
                'low': float(k[3]),
                'volume': float(k[5]),
                'time': int(k[0]),
            })
        print(f"[backtest_shared] OKX {symbol}: {len(daily)} daily bars", file=sys.stderr)
        return daily
    except Exception as e:
        print(f"[backtest_shared] OKX {symbol} fetch failed: {e}", file=sys.stderr)
        return None


def fetch_candles(symbol, days=600):
    """Fetch daily candles. Primary: OKX (3 attempts), fallback: Binance (3 attempts).
    Each retry has 0.5s cooldown."""
    for attempt in range(3):
        data = fetch_candles_okx(symbol, days)
        if data and len(data) >= 200:
            return data
        if attempt < 2:
            print(f"[backtest_shared] OKX {symbol} attempt {attempt+2}/3 retrying...", file=sys.stderr)
            time.sleep(0.5)
    print(f"[backtest_shared] Falling back to Binance for {symbol}", file=sys.stderr)
    for attempt in range(3):
        data = fetch_binance(symbol, days)
        if data and len(data) >= 200:
            return data
        if attempt < 2:
            print(f"[backtest_shared] Binance {symbol} attempt {attempt+2}/3 retrying...", file=sys.stderr)
            time.sleep(0.5)
    print(f"[backtest_shared] ERROR: OKX+Binance both failed for {symbol} after 3 attempts each", file=sys.stderr)
    return data if data else []


# ── Entry Sizing ──

def winner_mult(entries, cc, is_short, lev):
    """Return position size multiplier based on average ROI of existing entries."""
    if not entries:
        return 1.0
    rois = []
    for e in entries:
        if is_short:
            roi = (e['ep'] - cc) / e['ep'] * 100 * lev
        else:
            roi = (cc - e['ep']) / e['ep'] * 100 * lev
        rois.append(roi)
    avg = sum(rois) / len(rois)
    if avg > 15:     return 2.5
    elif avg > 10:   return 2.0
    elif avg > 5:    return 1.5
    elif avg > 0:    return 1.2
    elif avg > -5:   return 0.75
    else:            return 0.5


# ── Asset Value ──

def total_asset_value(entries, cc, eq, lev):
    """eq + unrealized PnL of all open entries (single-coin)."""
    val = eq
    for e in entries:
        if e.get('is_short'):
            val += (e['ep'] - cc) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
        else:
            val += (cc - e['ep']) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
    return val


# ── Results Computation ──

def compute_results(curve, yearly_eq, base=BASE, days=None):
    """From curve (daily equity values), yearly_eq (year-end dict), compute CAGR, MD, etc.
    If days is provided, use it for CAGR period calculation (more accurate than len/365).
    """
    teq = curve[-1] if curve else 1.0
    years = (days or len(curve)) / 365 if (days or curve) else 1
    cagr = (teq ** (1 / years) - 1) * 100 if teq > 0 else 0

    peak = curve[0] if curve else teq
    md = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > md:
            md = dd

    yearly = {}
    for y in sorted(yearly_eq.keys()):
        prev = yearly_eq.get(y - 1, 1.0)
        yearly[y] = (yearly_eq[y] / prev - 1) * 100

    return {'cagr': cagr, 'dd': md, 'final': teq * base, 'yearly': yearly}


def entry_conditions(entries, cc, idx, vols, vavg, m_ma, ma_buf, is_short,
                     btc_bull, ext_block, lev_coin, lei=-999,
                     ma=None, highs=None, lows=None,
                     ma_slope=False, lower_high=False, asym_buffer=False):
    """
    Kiểm tra điều kiện entry — shared giữa backtest và live.
    Returns: (should_enter, mult) — mult luôn là giá trị đúng (dùng cho pyramid).

    Optional filters (via **kwargs or named params):
      ma_slope  : Long requires MA rising, Short requires MA falling
      lower_high: Long blocked if 2 recent peaks forming lower highs
      asym_buffer: 5% buffer above MA, 2% buffer below MA
    """
    effective_buf = ma_buf
    if asym_buffer and m_ma and cc < m_ma:
        effective_buf = 0.02

    near_ma = abs(cc - m_ma) / m_ma <= effective_buf if m_ma else False
    vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg
    can_enter = (not is_short) or (is_short and not btc_bull)

    # Filter 1 — MA Slope
    if ma_slope and ma is not None and idx >= 3 and m_ma and ma[idx-3] is not None:
        if is_short:
            if ma[idx] >= ma[idx-3]:
                return False, 1.0
        else:
            if ma[idx] <= ma[idx-3]:
                return False, 1.0

    # Filter 2 — Lower High (long) / Higher Low (short)
    if lower_high and highs is not None and lows is not None:
        window = min(30, idx + 1)
        start = max(0, idx + 1 - window)
        if is_short:
            win_lows = lows[start:idx + 1]
            troughs = []
            for i in range(1, len(win_lows) - 1):
                if win_lows[i] < win_lows[i-1] and win_lows[i] < win_lows[i+1]:
                    troughs.append(win_lows[i])
            if len(troughs) >= 2 and troughs[-1] > troughs[-2]:
                return False, 1.0
        else:
            win_highs = highs[start:idx + 1]
            peaks = []
            for i in range(1, len(win_highs) - 1):
                if win_highs[i] > win_highs[i-1] and win_highs[i] > win_highs[i+1]:
                    peaks.append(win_highs[i])
            if len(peaks) >= 2 and peaks[-1] < peaks[-2]:
                return False, 1.0

    # Compute mult dù entry có fire hay không (pyramid cần mult)
    mult = winner_mult(entries, cc, is_short, lev_coin)
    if entries:
        if is_short:
            highest_ep = max(e['ep'] for e in entries)
            if (highest_ep - cc) / highest_ep * 100 > ext_block:
                mult = 0
        else:
            lowest_ep = min(e['ep'] for e in entries)
            if (cc - lowest_ep) / lowest_ep * 100 > ext_block:
                mult = 0

    should = (can_enter and near_ma and vol_cond and idx - lei >= 0 and mult > 0)
    return should, mult


def compute_roi(e, cc, is_short, lev):
    """ROI của 1 entry."""
    if is_short:
        return (e['ep'] - cc) / e['ep'] * 100 * lev
    return (cc - e['ep']) / e['ep'] * 100 * lev

