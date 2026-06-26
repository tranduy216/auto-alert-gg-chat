"""
Short Strategy — Isolated, hit-and-run
Entry: near MA20 from below + vol2d > volMA20 + bear trend
Exit: staged TP 3-8%, SL 3%
1x leverage, 1% capital per short
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 1.0
ENTRY_PCT = 0.01    # 1% of current equity
MA_BUF = 0.015      # test: 0.5, 1, 1.5, 2, 2.5, 3 %
TP_SCHEDULE = [(3, 0.25), (5, 0.25), (6, 0.25), (8, 0.25)]
SL_ROI = 3

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


def backtest_coin(coin, da, selected_years):
    if not da or len(da) < 60: return coin, None
    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    ma20 = sma(closes, 20); ma50 = sma(closes, 50)
    vol_ma20 = sma(vols, 20)

    entries = []; eq = 1.0; curve = []; yearly_eq = {}
    import datetime

    for idx in range(60, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            for e in entries:
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
            entries = []
            curve.append(eq)
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m20 = ma20[idx]; m50 = ma50[idx]; vavg = vol_ma20[idx]
        if None in (m20, m50) or vavg is None or vavg == 0: continue

        vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg

        # Short exit: SL + staged TP
        for e in entries[:]:
            roi = (e['ep'] - cc) / e['ep'] * 100 * LEV
            rm = False
            if roi <= -SL_ROI:
                eq += roi * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
                rm = True
            elif e['tp'] < len(TP_SCHEDULE):
                trg, cf = TP_SCHEDULE[e['tp']]
                if roi >= trg:
                    eq += roi * cf / 100 * (1 - 2 * 0.0005 * LEV)
                    e['rem'] = e.get('rem', 1.0) - cf
                    e['tp'] += 1
                    if e.get('rem', 1.0) <= 0.001: rm = True
            if rm: entries.remove(e)

        # Entry: near MA20 + volume + bear trend (cc < MA50)
        near_ma20 = abs(cc - m20) / m20 <= MA_BUF
        if near_ma20 and vol_cond and cc < m50:
            mp = eq * ENTRY_PCT
            entries.append({'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0})

        # Track
        ureal = 0
        for e in entries:
            roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
            ureal += roi * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
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

    print(f"{coin}: CAGR {cagr:+.2f}%  DD {md:.1f}%  Final ${teq*BASE:,.0f}")
    for y in sorted(yearly_cagr): print(f"  {y}: {yearly_cagr[y]:+.2f}%")
    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr}


def main():
    args = argparse.ArgumentParser()
    args.parse_args()
    data = load_data()
    coins = ['TRX', 'SOL', 'AVAX']
    results = []
    for coin in coins:
        da = data.get(f'{coin}USDT_4000_1609434000000', [])
        res = backtest_coin(coin, da, None)
        if res[1]: results.append(res)
    if results:
        cagrs = [r[1]['cagr'] for r in results]
        print(f"\nAvg CAGR: {sum(cagrs)/len(cagrs):+.2f}%")

if __name__ == '__main__': main()
