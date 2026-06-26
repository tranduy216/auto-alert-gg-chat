"""
TRX Strategy — Long only, pyramiding
Entry: price near MA20 (1.5% buffer) + volume > avg
Sizing: 1.5% of CURRENT equity per entry (compounding)
Pyramid: +1 entry every 10% price increase from last entry
Exit: trailing 20% or MA20 < MA50 cross
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 2.0
ENTRY_PCT = 0.015   # 1.5% of current equity
TRAIL_PCT = 0.80    # 20% retracement
MA_BUF = 0.015       # 1.5% buffer from MA20
PYRAMID_PCT = 0.10   # 10% price increase from last entry

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
    if not da or len(da) < 50: return coin, None
    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    vol_ma20 = sma(vols, 20)

    entries = []   # list of {ep, hi, mp}
    eq = 1.0       # equity as fraction of BASE
    curve = []; yearly_eq = {}
    last_ep = 0    # last entry price for pyramiding
    import datetime

    for idx in range(30, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            if entries:
                for e in entries:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                entries = []
            curve.append(eq)
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m20 = ma20[idx]; vavg = vol_ma20[idx]
        if m20 is None or vavg is None or vavg == 0: continue

        # ── Volume condition: last 2 days > 20-day avg ──
        vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg

        # ── Exit: trailing 20% only ──
        for e in entries[:]:
            e['hi'] = max(e.get('hi', cc), hi)
            if cc <= e['hi'] * TRAIL_PCT:
                raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                entries.remove(e)

        # ── Entry: price near MA20 (1.5% buffer) + volume ──
        near_ma20 = abs(cc - m20) / m20 <= MA_BUF
        if near_ma20 and vol_cond and (not last_ep or idx > 0):
            # Enter new position at 1.5% of current equity
            mp = eq * ENTRY_PCT  # fraction of BASE
            entries.append({'ep': cc, 'hi': cc, 'mp': mp})
            last_ep = cc

        # ── Pyramid: +10% from last entry price ──
        if last_ep > 0 and cc >= last_ep * (1 + PYRAMID_PCT):
            mp = eq * ENTRY_PCT
            entries.append({'ep': cc, 'hi': cc, 'mp': mp})
            last_ep = cc

        # ── Track equity ──
        ureal = 0
        for e in entries:
            raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV / BASE
            ureal += raw / 100 * (1 - 2 * 0.0005 * LEV)
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--years', type=str)
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()
    selected_years = set(int(y.strip()) for y in args.years.split(',')) if args.years else None
    data = load_data()
    coins = ['TRX', 'ETH', 'BNB', 'LINK', 'BTC']
    results = []
    for coin in coins:
        da = data.get(f'{coin}USDT_4000_1609434000000', [])
        res = backtest_coin(coin, da, selected_years)
        if res[1]: results.append(res)
    if results:
        cagrs = [r[1]['cagr'] for r in results]
        print(f"\nAvg CAGR: {sum(cagrs)/len(cagrs):+.2f}%")

if __name__ == '__main__': main()
