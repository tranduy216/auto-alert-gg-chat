"""
Short Pyramid — BTC Bear Gate
- BTC < MA200: Bear market → only short
- Entry: near MA20 from above (3% buffer) + vol2d > volMA20
- Pyramid: +1 short when prev reaches 5% ROI
- Winner-takes-more, 100% cap, 20% trail from lowest
- 1.5x lev, 1.5% incl leverage
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 1.5
ENTRY_PCT = 0.015   # 1.5% incl leverage
TRAIL_PCT = 0.80    # 20% retracement
MA_BUF = 0.03       # 3% buffer
PYRAMID_ROI = 5     # 5% ROI trigger
TP_SCHEDULE = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]

def load_data():
    p = Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f: raw = json.load(f)
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({'close': b2[-1]['close'], 'high': max(x['high'] for x in b2),
                         'low': min(x['low'] for x in b2), 'volume': sum(x['volume'] for x in b2),
                         'time': b2[0]['open_time']})
        data[sym] = daily
    return data


def winner_mult(entries, cc):
    if not entries: return 1.0
    rois = []
    for e in entries:
        roi = (e['ep'] - cc) / e['ep'] * 100 * LEV  # short ROI
        rois.append(roi)
    avg = sum(rois) / len(rois)
    if avg > 15:    return 2.5
    elif avg > 10:  return 2.0
    elif avg > 5:   return 1.5
    elif avg > 0:   return 1.2
    elif avg > -5:  return 0.75
    else:           return 0.5


def backtest_coin(coin, da, btc_da, selected_years):
    if not da or not btc_da or len(da) < 60: return coin, None
    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    ma20 = sma(closes, 20); vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da]
    btc_ma200 = sma(btc_closes, 200)

    entries = []; eq = 1.0; lei = -999; last_ep = 0
    max_dep = 0; max_entries = 0; curve = []; yearly_eq = {}
    import datetime

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            for e in entries:
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
            entries = []
            curve.append(eq)
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m20 = ma20[idx]; vavg = vol_ma20[idx]
        btc_idx = min(idx, len(btc_closes) - 1)
        btc_bear = btc_idx >= 200 and btc_ma200[btc_idx] and btc_closes[btc_idx] < btc_ma200[btc_idx]

        if m20 is None or vavg is None or vavg == 0: continue

        vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg

        # If BTC exits bear → close all shorts
        if not btc_bear:
            for e in entries:
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
            entries = []

        # Short exit: staged TP (3-12%) then trail 20%
        for e in entries[:]:
            # Update lowest price for trail
            e['lo'] = min(e.get('lo', bl), bl)
            roi = (e['ep'] - cc) / e['ep'] * 100 * LEV
            # Staged TP
            tp_stage = e.get('tp', 0)
            if tp_stage < len(TP_SCHEDULE):
                trg, cf = TP_SCHEDULE[tp_stage]
                if roi >= trg:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                    eq += raw * cf / 100 * (1 - 2 * 0.0005 * LEV)
                    e['rem'] = e.get('rem', 1.0) - cf
                    e['tp'] = tp_stage + 1
                    if e.get('rem', 1.0) <= 0.001:
                        entries.remove(e)
            # Trail 20%
            elif cc >= e['lo'] / TRAIL_PCT:
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV * e.get('rem', 1.0)
                eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                entries.remove(e)

        # Entry: near MA20 + volume, only when BTC bear
        dep = sum(e.get('mp', 0) for e in entries)
        near_ma20 = abs(cc - m20) / m20 <= MA_BUF
        mult = winner_mult(entries, cc)

        if btc_bear and near_ma20 and vol_cond and (idx - lei >= 0):
            mp = eq * ENTRY_PCT / LEV * mult
            if (dep + mp) * LEV <= eq:
                entries.append({'ep': cc, 'lo': bl, 'mp': mp, 'rem': 1.0, 'tp': 0})
                last_ep = cc; lei = idx

        # Pyramid: prev short reaches 5% ROI
        if btc_bear and last_ep > 0 and (idx - lei >= 0):
            roi = (last_ep - cc) / last_ep * 100 * LEV
            if roi >= PYRAMID_ROI:
                dep = sum(e.get('mp', 0) for e in entries)
                mp = eq * ENTRY_PCT / LEV * mult
                if (dep + mp) * LEV <= eq:
                    entries.append({'ep': cc, 'lo': bl, 'mp': mp, 'rem': 1.0, 'tp': 0})
                    last_ep = cc; lei = idx

        dep_total = sum(e.get('mp', 0) for e in entries)
        if dep_total > max_dep: max_dep = dep_total
        if len(entries) > max_entries: max_entries = len(entries)

        ureal = 0
        for e in entries:
            roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
            ureal += roi / 100 * (1 - 2 * 0.0005 * LEV)
        total_eq = eq + ureal; curve.append(total_eq)
        if dt.month == 12: yearly_eq[yr] = total_eq

    teq = curve[-1] if curve else eq
    years = len(curve) / 365 if curve else 1
    cagr = (teq ** (1 / years) - 1) * 100 if teq > 0 else 0
    peak = curve[0] if curve else eq; md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > md: md = dd
    yearly_cagr = {}
    for y in sorted(yearly_eq.keys()):
        prev = yearly_eq.get(y - 1, 1.0)
        yearly_cagr[y] = (yearly_eq[y] / prev - 1) * 100

    print(f"{coin}: CAGR {cagr:+.2f}%  DD {md:.1f}%  Final ${teq*BASE:,.0f}  MaxPos {max_dep*LEV*100:.0f}%({max_entries}e)")
    for y in sorted(yearly_cagr): print(f"  {y}: {yearly_cagr[y]:+.2f}%")
    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr}


def main():
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    coins = ['AVAX', 'BTC', 'ETH']
    results = []
    for coin in coins:
        da = data.get(f'{coin}USDT_4000_1609434000000', [])
        res = backtest_coin(coin, da, btc_da, None)
        if res[1]: results.append(res)
    if results:
        cagrs = [r[1]['cagr'] for r in results]
        print(f"\nAvg CAGR: {sum(cagrs)/len(cagrs):+.2f}%")

if __name__ == '__main__': main()
