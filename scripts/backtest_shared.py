"""
Shared backtest logic — constants, helpers, data loading.
All backtest files should import from here to avoid duplication.
"""
import json, datetime, requests, time
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
# Short TP ladder: 15%@4%, 15%@6%, 20%@8%, 20%@10%, 20%@12%, 10%@14% = 100%
HARD_SL = 8             # hard stop loss % for shorts (close all when roi <= -HARD_SL)
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


def fetch_paxg(from_ts=None):
    """Fetch PAXGUSDT 12h klines from Binance, aggregate → 1d bars."""
    if from_ts is None:
        from_ts = int(datetime.datetime(2022, 1, 1).timestamp() * 1000)
    url = 'https://api.binance.com/api/v3/klines'
    candles = []
    while True:
        params = {'symbol': 'PAXGUSDT', 'interval': '12h',
                  'startTime': from_ts, 'limit': 1000}
        resp = requests.get(url, params=params, timeout=30)
        raw = resp.json()
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
    return daily


# ── Entry Sizing ──

def winner_mult(entries, cc, is_short, lev):
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
                     btc_bull, ext_block, lev_coin, lei=-999):
    """
    Kiểm tra điều kiện entry — shared giữa backtest và live.
    Returns: (should_enter, mult) — mult=0 nếu bị block extension.
    """
    near_ma = abs(cc - m_ma) / m_ma <= ma_buf if m_ma else False
    vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg
    can_enter = (not is_short) or (is_short and not btc_bull)

    if not (can_enter and near_ma and vol_cond):
        return False, 0

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

    should = (idx - lei >= 0) and mult > 0
    return should, mult


def compute_roi(e, cc, is_short, lev):
    """ROI của 1 entry."""
    if is_short:
        return (e['ep'] - cc) / e['ep'] * 100 * lev
    return (cc - e['ep']) / e['ep'] * 100 * lev

