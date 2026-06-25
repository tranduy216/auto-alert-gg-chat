"""
New Strategy v2 — 1d, 2x lev, limit entry near MA5-MA25 zone
TP 60% staged 7-50% ROI, 40% trail at 18% ROI, SL 25%, peak DD 18%
"""

import json, hashlib, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from trading_config import BASE, FEE_RATE, SF
from new_strategy_config import *
from crypto_trading import sma, compute_rsi


def fetch(data_cache, symbol):
    return data_cache.get(f"{symbol}_4000_1609434000000", [])


def load_data():
    p = Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f:
        raw = json.load(f)
    # Aggregate 6h -> 1d: take every 4th entry (6h * 4 = 1d)
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(3, len(candles), 4):
            b4 = candles[i-3:i+1]
            daily.append({
                'open_time': b4[0]['open_time'],
                'open': b4[0]['open'],
                'high': max(x['high'] for x in b4),
                'low': min(x['low'] for x in b4),
                'close': b4[-1]['close'],
                'volume': sum(x['volume'] for x in b4),
            })
        data[sym] = daily
    return data


def backtest_coin(coin, data_cache, use_cache, selected_years):
    da = fetch(data_cache, coin + "USDT")
    if not da:
        return coin, None

    closes = [c['close'] for c in da]
    n = len(closes)
    if n < MA100 + 20:
        return coin, None

    # ── Indicators ──
    def rsi_at(idx, period=14):
        if idx < period:
            return 50.0
        return compute_rsi(closes[:idx+1], period)

    ma5 = sma(closes, MA5)
    ma25 = sma(closes, MA25)
    ma100 = sma(closes, MA100)
    vol_ma20 = sma([c['volume'] for c in da], 20)

    # ── State ──
    entries = []
    eq = 1.0
    curve = []
    yearly_eq = {}
    lei = -999  # last entry index

    # ── Main loop ──
    for idx in range(max(MA100 + 10, 150), n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        d_cur = __import__('datetime').datetime.fromtimestamp(da[idx]['open_time'] / 1000)
        cur_year = d_cur.year

        # Year filter
        if selected_years and cur_year not in selected_years:
            if entries:
                for e in entries:
                    raw = ((cc - e['ep']) / e['ep'] * 100) * e['mp'] * LEV
                    eq += raw * e['rem'] / 100 * (1 - 2 * FEE_RATE * LEV)
                entries = []
            curve.append(eq)
            if d_cur.month == 12: yearly_eq[cur_year] = eq
            continue

        # ── Entry logic ──
        m5_v = ma5[idx]; m25_v = ma25[idx]; m100_v = ma100[idx]
        if None in (m5_v, m25_v, m100_v):
            curve.append(eq)
            if d_cur.month == 12: yearly_eq[cur_year] = eq
            continue

        dep = sum(e['mp'] for e in entries)
        can_enter = dep < MAX_COIN_EQ_PCT and (idx - lei >= 3)

        if can_enter and len(entries) < MAX_ENTRIES:
            # Buy when: price > MA5 (short-term up) AND price < MA25 (pullback from resistance)
            if cc > m5_v and cc < m25_v * 1.01:
                entry = {'ep': cc, 'mp': ENTRY_SIZE, 'tp': 0, 'rem': 1.0,
                         'hi': cc, 'tstop': None, 'lev': LEV, 'sl': SL,
                         'tp_sched': TP_60,
                         'trail_act': TRAIL_ACT, 'trail_dist': TRAIL_DIST,
                         'trail_close': TRAIL_CLOSE, 'peak_dd': PEAK_DD}
                entries.append(entry); lei = idx

        # ── Exit logic ──
        ne = []
        for e in entries:
            ep = e['ep']; rem = e['rem']; tp_s = e['tp']
            hi_e = e['hi']; tstop = e['tstop']
            sl = e['sl']; lev = e['lev']
            tp_sched = e['tp_sched']; trail_act = e['trail_act']
            trail_dist = e['trail_dist']; trail_close = e['trail_close']
            peak_dd = e['peak_dd']
            ff = 1 - 2 * FEE_RATE * lev
            raw_roi = (cc - ep) / ep * 100 * e['mp'] * lev
            rm = False

            # SL
            if raw_roi <= -sl:
                eq += raw_roi * rem / 100 * ff; rm = True

            # Staggered TP (60% of position)
            elif not rm and tp_s < len(tp_sched):
                trg, cf_pct = tp_sched[tp_s]
                if raw_roi >= trg:
                    cf = cf_pct * rem
                    eq += raw_roi * cf / 100 * ff
                    rem -= cf; e['rem'] = rem; e['tp'] = tp_s + 1
                    if rem <= 0.001: rm = True
                e['_peak_roi'] = max(e.get('_peak_roi', -999), raw_roi)

            # Peak DD: close remaining if profit drops peak_dd% from peak
            if not rm:
                peak_r = e.get('_peak_roi', -999)
                if peak_r > 0 and peak_r - raw_roi >= peak_dd:
                    eq += raw_roi * rem / 100 * ff; rm = True

            # Trail remaining (40% of position, after all TPs complete)
            if not rm:
                e['_peak_roi'] = max(e.get('_peak_roi', -999), raw_roi)
                if tp_s >= len(tp_sched):
                    pnl = (cc - ep) / ep * 100
                    if pnl >= trail_act:
                        if tstop is None:
                            tstop = cc * (1 - trail_dist)
                        tstop = max(tstop, hi_e * (1 - trail_dist))
                        e['tstop'] = tstop; e['hi'] = max(hi_e, cc)
                        if bl <= tstop:
                            cf = trail_close * rem
                            eq += raw_roi * cf / 100 * ff
                            rem -= cf; e['rem'] = rem
                            if rem <= 0.001: rm = True
                else:
                    e['hi'] = max(hi_e, cc)

            if not rm: ne.append(e)
        entries = ne

        # ── Track equity ──
        ureal = 0
        for e in entries:
            raw = ((cc - e['ep']) / e['ep'] * 100) * e['mp'] * e['lev']
            ureal += raw * e['rem'] / 100 * (1 - 2 * FEE_RATE * e['lev'])
        total_eq = eq + ureal
        curve.append(total_eq)
        if d_cur.month == 12: yearly_eq[cur_year] = total_eq

    # ── Results ──
    teq = curve[-1] if curve else eq
    years = len(curve) / 365 if curve else 1
    cagr = (teq ** (1 / years) - 1) * 100 if teq > 0 else 0

    # Max DD
    peak = curve[0] if curve else eq; md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > md: md = dd

    yearly_cagr = {}
    sorted_years = sorted(yearly_eq.keys())
    for i, yr in enumerate(sorted_years):
        prev = yearly_eq[sorted_years[i-1]] if i > 0 else 1.0
        yearly_cagr[yr] = (yearly_eq[yr] / prev - 1) * 100

    print(f"\n{coin}:")
    print(f"  CAGR: {cagr:+.2f}%")
    print(f"  Max DD: {md:.2f}%")
    print(f"  Final Equity: ${teq * BASE:,.2f}")
    for yr in sorted(yearly_cagr):
        print(f"    {yr}: {yearly_cagr[yr]:+.2f}%")

    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE,
                  'yearly': yearly_cagr}


def main():
    parser = argparse.ArgumentParser(description='New Strategy Backtest')
    parser.add_argument('--coin', type=str)
    parser.add_argument('--years', type=str)
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()

    if args.coin:
        coins = [args.coin.upper()]
    else:
        coins = ["ETH", "TRX"]

    selected_years = None
    if args.years:
        selected_years = set(int(y.strip()) for y in args.years.split(','))

    use_cache = not args.no_cache
    data_cache = load_data()
    print(f"Loaded {len(data_cache)} symbols")

    results = []
    for coin in coins:
        result = backtest_coin(coin, data_cache, use_cache, selected_years)
        results.append(result)

    if len(results) > 1:
        cagrs = [r[1]['cagr'] for r in results if r[1]]
        print(f"\nAvg CAGR: {sum(cagrs)/len(cagrs):+.2f}%")


if __name__ == '__main__':
    main()
