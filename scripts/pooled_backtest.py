"""
Pooled Backtest — shared $10k equity pool, first-come-first-served signals.
All coins share one capital pool. Signals compete for the 75% cap.
"""
import json, requests, time
from pathlib import Path
import sys, datetime
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000
ENTRY_PCT = 0.015
TRAIL_PCT = 0.80
TP_SCHEDULE = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
MAX_CAP = 0.75  # 75% of total asset value per coin


def load_data():
    p = Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f: raw = json.load(f)
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({
                'close': b2[-1]['close'], 'high': max(x['high'] for x in b2),
                'low': min(x['low'] for x in b2),
                'volume': sum(x['volume'] for x in b2),
                'time': b2[0]['open_time'],
            })
        data[sym] = daily
    return data


def fetch_paxg():
    url = 'https://api.binance.com/api/v3/klines'
    start_ts = int(datetime.datetime(2022, 1, 1).timestamp() * 1000)
    all_candles = []
    while True:
        params = {'symbol': 'PAXGUSDT', 'interval': '12h', 'startTime': start_ts, 'limit': 1000}
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        if not data or isinstance(data, dict):
            break
        all_candles.extend(data)
        start_ts = data[-1][6] + 1
        if len(data) < 1000:
            break
        time.sleep(0.5)
    daily = []
    for i in range(1, len(all_candles), 2):
        b2 = all_candles[i-1:i+1]
        daily.append({
            'close': float(b2[-1][4]),
            'high': max(float(x[2]) for x in b2),
            'low': min(float(x[3]) for x in b2),
            'volume': sum(float(x[5]) for x in b2),
            'time': b2[0][0],
        })
    return daily


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
    if avg > 15: return 2.5
    elif avg > 10: return 2.0
    elif avg > 5: return 1.5
    elif avg > 0: return 1.2
    elif avg > -5: return 0.75
    else: return 0.5


def total_asset_value(all_entries, closes_map, eq, lev_map):
    val = eq
    for coin, entries in all_entries.items():
        if not entries:
            continue
        cc = closes_map.get(coin)
        if cc is None:
            continue
        lev = lev_map.get(coin, 1.5)
        for e in entries:
            is_short = e.get('is_short', False)
            if is_short:
                val += (e['ep'] - cc) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
            else:
                val += (cc - e['ep']) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
    return val


def run_pooled(data, strategies):
    """
    strategies: list of (label, coin_key, is_short, cfg)
    Returns: portfolio curve, yearly CAGR, max DD
    """
    # Precompute MAs and align timestamps
    coin_data = {}  # label -> {closes, vols, high, low, times, ma_short, vol_ma20, btc_bull}
    timestamps = set()
    
    for label, coin_key, is_short, cfg in strategies:
        da = data.get(coin_key)
        if not da: continue
        closes = [c['close'] for c in da]; n = len(closes)
        vols = [c['volume'] for c in da]
        highs = [c['high'] for c in da]
        lows = [c['low'] for c in da]
        times = [c['time'] for c in da]

        ma_short = sma(closes, cfg.get('ma', 20))
        vol_ma20 = sma(vols, 20)
        
        coin_data[label] = {
            'closes': closes, 'vols': vols, 'highs': highs, 'lows': lows,
            'times': times, 'ma_short': ma_short, 'vol_ma20': vol_ma20,
            'n': n, 'is_short': is_short, 'cfg': cfg, 'da': da,
        }
        for t in times[200:]:
            timestamps.add(t)
    
    tss = sorted(timestamps)
    
    # BTC regime (shared)
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    btc_closes = [c['close'] for c in btc_da]
    btc_times = [c['time'] for c in btc_da]
    btc_ma200 = sma(btc_closes, 200)
    btc_time_to_idx = {t: i for i, t in enumerate(btc_times)}

    # Per-coin state
    entries_map = {label: [] for label, _, _, _ in strategies}  # label -> list of entries
    lei_map = {label: -999 for label, _, _, _ in strategies}
    last_ep_map = {label: 0 for label, _, _, _ in strategies}
    idx_map = {label: 0 for label, _, _, _ in strategies}  # current index in coin's data
    time_to_idx = {label: {t: i for i, t in enumerate(coin_data[label]['times'])} for label in coin_data}

    eq = 1.0  # shared realized equity
    curve = []
    yearly_eq = {}
    ts_curve = []

    for ts in tss:
        # Check BTC regime
        btc_bull = False
        if btc_ma200:
            btc_idx = btc_time_to_idx.get(ts)
            if btc_idx is not None and btc_idx >= 200 and btc_ma200[btc_idx]:
                btc_bull = btc_closes[btc_idx] > btc_ma200[btc_idx]

        dt = datetime.datetime.fromtimestamp(ts / 1000)
        yr = dt.year

        # First: process exits for all coins
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200:
                continue
            cc = cd['closes'][idx]; hi = cd['highs'][idx]; bl = cd['lows'][idx]
            is_short = cd['is_short']; cfg = cd['cfg']
            lev_coin = cfg.get('lev', 1.5)
            tp_sched = cfg.get('tp', TP_SCHEDULE)
            trail_pct = cfg.get('trail', TRAIL_PCT)
            entries = entries_map[label]

            # BTC regime exit (shorts only)
            for e in entries[:]:
                if e.get('is_short') and btc_bull:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                    eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * lev_coin)
                    entries.remove(e)
                    continue

                # TP + trail
                if e.get('is_short'):
                    e['lo'] = min(e.get('lo', bl), bl)
                    roi = (e['ep'] - cc) / e['ep'] * 100 * lev_coin
                    tp_stage = e.get('tp', 0)
                    if tp_stage < len(tp_sched):
                        trg, cf = tp_sched[tp_stage]
                        if roi >= trg:
                            raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                            eq += raw * cf / 100 * (1 - 2 * 0.0005 * lev_coin)
                            e['rem'] = e.get('rem', 1.0) - cf
                            e['tp'] = tp_stage + 1
                            if e.get('rem', 1.0) <= 0.001:
                                entries.remove(e)
                    elif cc >= e['lo'] / trail_pct:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * (1 - 2 * 0.0005 * lev_coin)
                        entries.remove(e)
                else:
                    e['hi'] = max(e.get('hi', cc), hi)
                    if cc <= e['hi'] * trail_pct:
                        raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * (1 - 2 * 0.0005 * lev_coin)
                        entries.remove(e)

        # Second: process entries for all coins (first-come-first-served by strategy order)
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200:
                continue
            cc = cd['closes'][idx]; hi = cd['highs'][idx]; bl = cd['lows'][idx]
            is_short = cd['is_short']; cfg = cd['cfg']
            lev_coin = cfg.get('lev', 1.5)
            ma_period = cfg.get('ma', 20)
            ma_buf = cfg.get('buf', 0.03)
            pyr_roi = cfg.get('pyr', 5)
            entries = entries_map[label]

            m_ma = cd['ma_short'][idx]
            vavg = cd['vol_ma20'][idx]
            if m_ma is None or vavg is None or vavg == 0:
                continue

            vol_cond = idx >= 2 and (cd['vols'][idx] + cd['vols'][idx-1]) / 2 > vavg
            near_ma = abs(cc - m_ma) / m_ma <= ma_buf

            can_enter_long = not is_short
            can_enter_short = is_short and not btc_bull
            active = can_enter_long or can_enter_short

            if not active or not near_ma or not vol_cond:
                continue

            # Compute mult and extension block
            mult = winner_mult(entries, cc, is_short, lev_coin)
            if entries:
                lowest_ep = min(e['ep'] for e in entries)
                ext = abs(cc - lowest_ep) / lowest_ep * 100
                if ext > 30:
                    mult = 0

            if mult <= 0:
                continue

            # Check cooldown
            if idx - lei_map[label] < 0:
                continue

            # Compute total deployed (all coins) + total asset value for global cap
            total_dep = sum(sum(e.get('mp', 0) for e in entries) for entries in entries_map.values())
            closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts, -1)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
            lev_map = {l: coin_data[l]['cfg'].get('lev', 1.5) for l in coin_data}
            total_val = total_asset_value(entries_map, closes_map, eq, lev_map)

            # Entry
            dep_coin = sum(e.get('mp', 0) for e in entries)
            mp = eq * ENTRY_PCT / lev_coin * mult
            if total_dep + mp <= MAX_CAP * total_val:
                e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                if is_short:
                    e['lo'] = bl
                else:
                    e['hi'] = cc
                entries.append(e)
                last_ep_map[label] = cc
                lei_map[label] = idx

            # Pyramid
            last_ep = last_ep_map[label]
            lei = lei_map[label]
            if last_ep > 0 and idx - lei >= 0 and mult > 0:
                if can_enter_long:
                    roi = (cc - last_ep) / last_ep * 100 * lev_coin
                else:
                    roi = (last_ep - cc) / last_ep * 100 * lev_coin
                if roi >= pyr_roi:
                    total_dep = sum(sum(e.get('mp', 0) for e in entries) for entries in entries_map.values())
                    mp = eq * ENTRY_PCT / lev_coin * mult
                    if total_dep + mp <= MAX_CAP * total_val:
                        e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                        if is_short:
                            e['lo'] = bl
                        else:
                            e['hi'] = cc
                        entries.append(e)
                        last_ep_map[label] = cc
                        lei_map[label] = idx

        # Compute total unrealized PnL and record curve
        ureal = 0
        for label, entries in entries_map.items():
            lev_coin = coin_data[label]['cfg'].get('lev', 1.5)
            idx = time_to_idx[label].get(ts)
            if idx is None:
                continue
            cc = coin_data[label]['closes'][idx]
            for e in entries:
                if e.get('is_short'):
                    roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                else:
                    roi = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
                ureal += roi * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * lev_coin)

        total_eq = eq + ureal
        curve.append(total_eq)
        ts_curve.append((ts, total_eq))
        if dt.month == 12:
            yearly_eq[yr] = total_eq

    # Capture final partial year
    if curve:
        last_yr = datetime.datetime.fromtimestamp(tss[-1] / 1000).year
        if last_yr not in yearly_eq:
            yearly_eq[last_yr] = curve[-1]

    teq = curve[-1] if curve else eq
    years = len(tss) / 365 if tss else 1
    cagr = (teq ** (1 / years) - 1) * 100 if teq > 0 else 0
    peak = curve[0] if curve else eq
    md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > md: md = dd

    yearly_cagr = {}
    for y in sorted(yearly_eq.keys()):
        prev = yearly_eq.get(y - 1, 1.0)
        yearly_cagr[y] = (yearly_eq[y] / prev - 1) * 100

    return {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr}


def main():
    data = load_data()
    paxg_daily = fetch_paxg()
    data['PAXGUSDT_POOL'] = paxg_daily

    btc_key = 'BTCUSDT_4000_1609434000000'

    strategies = [
        ('TRX-L',  'TRXUSDT_4000_1609434000000', False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('PAXG-L', 'PAXGUSDT_POOL',              False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('BTC-S',  btc_key,                       True, {'ma': 5,  'buf': 0.05, 'pyr': 3, 'lev': 1.6}),
    ]

    r = run_pooled(data, strategies)

    print("POOLED BACKTEST — Shared $10k, first-come-first-served signals")
    print("=" * 70)
    print(f"{'Metric':<20} {'Value':>15}")
    print("-" * 70)
    print(f"{'CAGR':<20} {r['cagr']:>+14.1f}%")
    print(f"{'Max DD':<20} {r['dd']:>14.1f}%")
    print(f"{'Final equity':<20} ${r['final']:>14,.0f}")
    print("-" * 70)
    print(f"{'Year':<8} {'Return':>12}")
    print("-" * 70)
    for y in sorted(r['yearly'].keys()):
        print(f"{y:<8} {r['yearly'][y]:>+11.1f}%")
    print("=" * 70)


if __name__ == '__main__':
    main()
