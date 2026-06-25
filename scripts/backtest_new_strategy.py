"""
New Strategy Backtest — 1d, 2x lev, isolated positions
Trend detection: MA10/30/100/180
- Bull: buy pullbacks near MA30/MA100
- Bear: buy strong bounces near MA100/MA180
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
    if n < MA180 + 10:
        return coin, None

    # ── Indicators ──
    def rsi_at(idx, period=14):
        if idx < period:
            return 50.0
        return compute_rsi(closes[:idx+1], period)

    ma10 = sma(closes, MA10)
    ma30 = sma(closes, MA30)
    ma100 = sma(closes, MA100)
    ma180 = sma(closes, MA180)
    vol_ma20 = sma([c['volume'] for c in da], 20)

    # Trend score: -3 (strong bear) to +3 (strong bull) based on MA alignment
    def trend_score(idx):
        m10 = ma10[idx]; m30 = ma30[idx]; m100 = ma100[idx]; m180 = ma180[idx]
        if None in (m10, m30, m100, m180):
            return 0
        score = 0
        if m10 > m30: score += 1
        if m30 > m100: score += 1
        if m100 > m180: score += 1
        if m10 < m30: score -= 1
        if m30 < m100: score -= 1
        if m100 < m180: score -= 1
        return score

    # ── State ──
    entries = []   # list of dicts: entry_price, size, rem, tp_stage, is_bounce, ...
    eq = 1.0
    curve = []
    yearly_eq = {}
    lei = -999  # last entry index

    # ── Main loop ──
    for idx in range(max(MA180 + 10, 200), n):
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
        ts = trend_score(idx)
        rsi_v = rsi_at(idx)
        vol = da[idx]['volume']
        vol_avg = vol_ma20[idx] if vol_ma20[idx] and vol_ma20[idx] > 0 else vol
        vs = vol / vol_avg if vol_avg > 0 else 0.2
        m10_v = ma10[idx]; m30_v = ma30[idx]; m100_v = ma100[idx]; m180_v = ma180[idx]
        if None in (m10_v, m30_v, m100_v, m180_v):
            curve.append(eq)
            if d_cur.month == 12: yearly_eq[cur_year] = eq
            continue

        dep = sum(e['mp'] for e in entries)
        can_enter = dep < MAX_COIN_EQ_PCT and (idx - lei >= 3)  # 3-day cooldown

        if can_enter and len(entries) < MAX_ENTRIES:
            # Trend direction from MA alignment
            ma_bull = m10_v > m30_v > m100_v   # full bull alignment
            ma_bear = m10_v < m30_v < m100_v   # full bear alignment
            near_m30 = m30_v > 0 and abs(cc - m30_v) / m30_v < 0.03
            near_m100 = m100_v > 0 and abs(cc - m100_v) / m100_v < 0.05

            entered = False

            # Trend: MA100 > MA180 = bull, MA100 < MA180 = bear
            is_bull_trend = m100_v > m180_v
            is_bear_trend = m100_v < m180_v
            near_m30 = m30_v > 0 and abs(cc - m30_v) / m30_v < 0.05

            # Bull pullback: bull trend + price near MA30 + RSI cooling
            if not entered and is_bull_trend and rsi_v < 50 and near_m30:
                entry = {'ep': cc, 'mp': ENTRY_SIZE, 'tp': 0, 'rem': 1.0,
                         'hi': cc, 'tstop': None, 'lev': LEV, 'sl': BULL_SL,
                         'is_bounce': False, 'tp_sched': BULL_TP,
                         'trail_act': BULL_TRAIL_ACT, 'trail_dist': BULL_TRAIL_DIST,
                         'trail_close': BULL_TRAIL_CLOSE}
                entries.append(entry); lei = idx; entered = True

            # Bear bounce: bear trend + oversold RSI + bullish candle (long lower wick)
            if not entered and is_bear_trend and rsi_v < 38:
                c_range = hi - bl
                lower_wick = (min(cc, da[idx]['open']) - bl) / c_range if c_range > 0 else 0
                long_wick = lower_wick > 0.35
                good_vol = vs > 0.7
                if long_wick or good_vol:
                    entry = {'ep': cc, 'mp': ENTRY_SIZE, 'tp': 0, 'rem': 1.0,
                             'hi': cc, 'tstop': None, 'lev': LEV, 'sl': BEAR_SL,
                             'is_bounce': True, 'tp_sched': BEAR_TP,
                             'trail_act': BEAR_TRAIL_ACT, 'trail_dist': BEAR_TRAIL_DIST,
                             'trail_close': BEAR_TRAIL_CLOSE}
                    entries.append(entry); lei = idx; entered = True

        # ── Exit logic ──
        ne = []
        for e in entries:
            ep = e['ep']; mp = e['mp']; rem = e['rem']; tp_s = e['tp']
            hi_e = e['hi']; tstop = e['tstop']
            lev = e['lev']; sl = e['sl']
            tp_sched = e['tp_sched']; trail_act = e['trail_act']
            trail_dist = e['trail_dist']; trail_close = e['trail_close']
            is_bounce = e['is_bounce']
            ff = 1 - 2 * FEE_RATE * lev
            raw_roi = (cc - ep) / ep * 100 * mp * lev

            rm = False

            # SL
            if raw_roi <= -sl:
                eq += raw_roi * rem / 100 * ff; rm = True

            # Staggered TP
            elif not rm and tp_s < len(tp_sched):
                trg, cf_pct = tp_sched[tp_s]
                if raw_roi >= trg:
                    cf = cf_pct * rem
                    eq += raw_roi * cf / 100 * ff
                    rem -= cf; e['rem'] = rem; e['tp'] = tp_s + 1
                    if rem <= 0.001: rm = True
                    e['_peak_roi'] = raw_roi

            # Trail after all TPs
            if not rm:
                peak_r = max(e.get('_peak_roi', -999), raw_roi)
                e['_peak_roi'] = peak_r
                if tp_s >= len(tp_sched):
                    pnl = (cc - ep) / ep
                    if pnl * 100 >= trail_act:
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
