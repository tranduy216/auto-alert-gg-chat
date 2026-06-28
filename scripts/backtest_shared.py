"""
Shared backtest logic — constants, helpers, data loading.
All backtest files should import from here to avoid duplication.
"""
import json, os, sys, datetime, requests, time
from pathlib import Path

def sma(values, period):
    """Simple Moving Average — O(N) with rolling sum."""
    period = int(period)
    result = []
    rolling_sum = 0.0
    for i in range(len(values)):
        rolling_sum += values[i]
        if i < period - 1:
            result.append(None)
        else:
            if i >= period:
                rolling_sum -= values[i - period]
            result.append(rolling_sum / period)
    return result

# ── Constants ──

BASE = 10000
ENTRY_PCT = 0.011        # 1.1% margin per entry (~$300 on $14K at 2x)
TRAIL_PCT = 0.80        # 20% trailing stop from extreme (long only)
MA_BUF = 0.03           # 3% buffer default
MA_PERIOD = 20          # MA period default
TP_SCHEDULE = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
BTC_SHORT_TP = [(4, 0.25), (8, 0.25), (12, 0.25), (16, 0.25)]

# ── Long config ──
LONG_TP = [(10, 0.05), (20, 0.10), (30, 0.15), (40, 0.20), (50, 0.10)]
LONG_MAX_MARGIN = 0.75

# ── Short config ──
SHORT_TP = [(4, 0.30), (8, 0.40), (12, 0.30)]  # 3 stages: close 30/40/30%
SHORT_MAX_MARGIN = 0.40 # max 40% margin per coin (80% exposure at 2x)
SHORT_CLOSE_PCT = 0.08  # closeAll if price rises 8% from trough (16% ROI at 2x)
SHORT_COOLDOWN_ENTRY = 2  # 2 days between short entries
SL_COOLDOWN = 2          # 2 days after stop loss
EXT_BLOCK_PCT = 25      # block adds when price >25% from extreme entry
FEE_RATE = 0.0005       # 0.05% per side
MAX_CAP = 0.75          # max margin deployed (backtest only)

# ── Winner Multiplier Table ──
WINNER_MULT_TABLE = [
    (15, 2.5),
    (10, 2.0),
    (5, 1.5),
    (0, 1.2),
    (-5, 0.75),
]

# ── Pyramid Strategies (single source of truth for all scripts) ──
# Format: (coin, is_short, cfg)  — cfg = {entry: {...}, exit: {...}, pyramid: {...}}
PYRAMID_STRATEGIES = [
    ('TRX', False, {
        'entry': {'ma': 15, 'buffer': 0.05, 'vol_bars': 3, 'lev': 2},
        'exit':  {'trail': 0.82, 'tp': [(10, 0.05), (20, 0.10), (30, 0.15), (40, 0.20), (50, 0.10)]},
    }),
    ('XAU', False, {
        'entry': {'ma': 20, 'buffer': 0.05, 'vol_bars': 3, 'lev': 2, 'lower_high': True},
        'exit':  {'mode': 'ma_cross', 'ma_short': 40, 'ma_long': 90, 'buffer': 0.03},
        'pyramid': {'enabled': True, 'entry_mult': 1.5},
    }),
    ('BTC', True, {
        'entry': {'ma': 10, 'buffer': 0.05, 'lev': 2.5, 'short_mult': 3.0},
        'exit':  {'trail': 0.80, 'tp': [(4, 0.30), (8, 0.40), (12, 0.30)]},
        'pyramid': {'enabled': True, 'entry_mult': 0.7, 'pyr_step': 8, 'pyr_cap': 3},
    }),
]


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
                'open': b2[0].get('open', b2[0].get('close', 0)),
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
                'open': float(b2[0][1]),
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
    """Fetch PAXGUSDT daily bars. Reads raw 12h cache, aggregates to 1d.
    Falls back to Binance API if cache unavailable."""
    cache_path = Path(__file__).parent / "_klines_12h_5y.json"
    try:
        if cache_path.exists():
            raw = json.loads(cache_path.read_text())
            cache_key = next((k for k in raw if k.startswith('PAXGUSDT_4000_')), None)
            if not cache_key:
                cache_key = "PAXGUSDT_4000_1609434000000"
            cached = raw.get(cache_key)
            if cached and isinstance(cached, list):
                candles = cached
                daily = []
                for i in range(1, len(candles), 2):
                    b2 = candles[i-1:i+1]
                    daily.append({
                        'open': b2[0].get('open', b2[0].get('close', 0)),
                        'close': b2[-1]['close'],
                        'high': max(x['high'] for x in b2),
                        'low': min(x['low'] for x in b2),
                        'volume': sum(x['volume'] for x in b2),
                        'time': b2[0]['open_time'],
                    })
                print(f"[backtest_shared] Local cache {cache_key}: {len(daily)} daily bars", file=sys.stderr)
                return daily
    except Exception:
        pass
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
                'open': float(b2[0][1]),
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
        base = symbol.replace('USDT', '')
        okx_symbols = [f'{base}-USDT', f'{base}-USDT-SWAP']
        url = 'https://www.okx.com/api/v5/market/candles'
        all_candles = []; before = ''
        okx_symbol = None
        for sym in okx_symbols:
            params = {'instId': sym, 'bar': '1D', 'limit': 1}
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get('code') == '0' and data.get('data'):
                    okx_symbol = sym
                    break
            except Exception:
                continue
        if not okx_symbol:
            print(f"[backtest_shared] OKX {symbol}: no valid instrument found", file=sys.stderr)
            return None
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
                'open': float(k[1]),
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


def fetch_candles_coingecko(symbol, days=600):
    """Fetch OHLCV from CoinGecko market_chart, aggregate hourly → daily."""
    api_key = os.environ.get('COINGECKO_API_KEY', '')
    cg_id = {'BTCUSDT': 'bitcoin', 'TRXUSDT': 'tron', 'XAUUSDT': 'pax-gold'}.get(symbol)
    if not cg_id:
        return None
    try:
        headers = {'x-cg-demo-api-key': api_key} if api_key else {}
        url = f'https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart'
        params = {'vs_currency': 'usd', 'days': str(min(days * 2, 720))}
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        prices = data.get('prices', [])
        if len(prices) < 48:
            return None
        daily_map = {}
        for ts, price in prices:
            day = ts // (86400 * 1000)
            d = daily_map.get(day)
            if d is None:
                daily_map[day] = {'open': price, 'high': price, 'low': price, 'close': price, 'time': day * 86400 * 1000}
            else:
                d['high'] = max(d['high'], price)
                d['low'] = min(d['low'], price)
                d['close'] = price
        daily = sorted(daily_map.values(), key=lambda x: x['time'])
        daily = daily[-days:] if len(daily) > days else daily
        print(f"[backtest_shared] CoinGecko {symbol}: {len(daily)} daily bars", file=sys.stderr)
        return daily
    except Exception as e:
        print(f"[backtest_shared] CoinGecko {symbol} failed: {e}", file=sys.stderr)
        return None


def fetch_candles_cmc(symbol, days=600):
    """Fetch OHLCV from CoinMarketCap (requires CMC_API_KEY env)."""
    api_key = os.environ.get('CMC_API_KEY', '')
    if not api_key:
        return None
    try:
        headers = {'X-CMC_PRO_API_KEY': api_key}
        url = 'https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical'
        params = {'symbol': symbol.replace('USDT', ''), 'convert': 'USD', 'count': min(days, 365)}
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get('data', {}).get(symbol.replace('USDT', ''), {}).get('quotes', [])
        if not quotes:
            return None
        daily = []
        for q in quotes:
            quote = q.get('quote', {}).get('USD', {})
            daily.append({
                'open': float(quote.get('open', quote.get('close', 0))),
                'close': float(quote.get('close', 0)),
                'high': float(quote.get('high', 0)),
                'low': float(quote.get('low', 0)),
                'volume': float(quote.get('volume', 0)),
                'time': int(datetime.datetime.strptime(q['time_open'][:10], '%Y-%m-%d').timestamp() * 1000),
            })
        print(f"[backtest_shared] CMC {symbol}: {len(daily)} daily bars", file=sys.stderr)
        return daily
    except Exception as e:
        print(f"[backtest_shared] CMC {symbol} failed: {e}", file=sys.stderr)
        return None


def _try_fetch(fetcher, symbol, days, _label):
    """Try one fetcher with 3 attempts, 0.5s cooldown."""
    for attempt in range(3):
        data = fetcher(symbol, days)
        if data and len(data) >= 200:
            return data
        if attempt < 2:
            time.sleep(0.5)
    return None


def fetch_candles(symbol, days=600):
    """Fetch daily candles. Priority: OKX → CMC → CoinGecko. 0.5s cooldown between attempts."""
    for fetcher, label in [(fetch_candles_okx, 'OKX'), (fetch_candles_cmc, 'CMC'), (fetch_candles_coingecko, 'CoinGecko')]:
        data = _try_fetch(fetcher, symbol, days, label)
        if data:
            return data
        print(f"[backtest_shared] {label} {symbol} exhausted, trying next source", file=sys.stderr)
        time.sleep(0.5)
    print(f"[backtest_shared] ERROR: All sources failed for {symbol}", file=sys.stderr)
    return []


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
    for threshold, mult in WINNER_MULT_TABLE:
        if avg > threshold:
            return mult
    return 0.5


def avg_entry(entries):
    """Return (avg_price, total_weight) weighted by mp * rem (backtest) or 1 (live)."""
    if not entries:
        return None, 0
    total_weight = 0
    weighted_sum = 0
    for e in entries:
        if 'mp' in e:
            w = e['mp'] * e.get('rem', 1.0)
        else:
            w = 1
        total_weight += w
        weighted_sum += e['ep'] * w
    avg = weighted_sum / total_weight if total_weight > 0 else None
    return avg, total_weight


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
                     ma_slope=False, lower_high=False, asym_buffer=False,
                     vol_bars=2, green_min_count=0, green_window=0,
                     opens=None, closes=None):
    """
    Kiểm tra điều kiện entry — shared giữa backtest và live.
    Returns: (should_enter, mult) — mult luôn là giá trị đúng (dùng cho pyramid).

    Optional filters:
      ma_slope       : Long requires MA rising, Short requires MA falling
      lower_high     : Long blocked if 2 recent peaks forming lower highs
      asym_buffer    : 5% buffer above MA, 2% buffer below MA (default 3%)
      vol_bars       : Number of recent bars for volume average check (default 2)
      green_min_count: Require N green candles in green_window for long (default 0=off)
      green_window   : Window for green candle count (default = vol_bars)
      opens          : List of open prices for green candle check
    """
    effective_buf = ma_buf
    if asym_buffer and m_ma and cc < m_ma:
        effective_buf = 0.02

    near_ma = abs(cc - m_ma) / m_ma <= effective_buf if m_ma else False
    vol_cond = idx >= vol_bars and sum(vols[idx - vol_bars + 1:idx + 1]) / vol_bars > vavg
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

    # Filter 3 — Green candle count (long only, avoid dead cat bounce)
    if not is_short and green_min_count > 0 and opens is not None and closes is not None:
        gwin = green_window if green_window > 0 else vol_bars
        window = min(gwin, idx + 1)
        green_cnt = 0
        for i in range(idx - window + 1, idx + 1):
            if opens[i] is not None and closes[i] is not None and closes[i] > opens[i]:
                green_cnt += 1
        if green_cnt < green_min_count:
            return False, 1.0

    # Compute mult dù entry có fire hay không (pyramid cần mult)
    mult = winner_mult(entries, cc, is_short, lev_coin)
    if entries and not is_short:
        lowest_ep = min(e['ep'] for e in entries)
        if (cc - lowest_ep) / lowest_ep * 100 > ext_block:
            mult = 0
    elif entries and is_short:
        highest_ep = max(e['ep'] for e in entries)
        if (highest_ep - cc) / highest_ep * 100 > 15:
            mult = 0

    should = (can_enter and near_ma and vol_cond and idx - lei >= 0 and mult > 0)
    return should, mult


def compute_roi(e, cc, is_short, lev):
    """ROI của 1 entry."""
    if is_short:
        return (e['ep'] - cc) / e['ep'] * 100 * lev
    return (cc - e['ep']) / e['ep'] * 100 * lev

