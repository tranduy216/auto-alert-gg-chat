"""
Trend Hold Strategy v2
- Long: Coin Close > MA200 (bull, go long)
- Short: Coin Close < MA200 (bear, go short)
- Exit: trailing 15% from extreme only (no force-close on trend flip)
- 2 coins: ETH, TRX | 2x lev, 10% per entry, 5-day cooldown
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 2.0; ENTRY_SIZE = 0.10
TRAIL_PCT = 0.85; MAX_ENTRIES = 10; MAX_DEPLOYED = 1.0

def load_data():
    p = Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f: raw = json.load(f)
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({'close': b2[-1]['close'], 'high': max(x['high'] for x in b2),
                         'low': min(x['low'] for x in b2), 'time': b2[0]['open_time']})
        data[sym] = daily
    return data


def backtest_coin(coin, da, selected_years):
    if not da or len(da) < 220: return coin, None
    closes = [c['close'] for c in da]; n = len(closes)
    ma200 = sma(closes, 200)
    entries = []; lei = -999; eq = 1.0; curve = []; yearly_eq = {}
    import datetime

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            if entries:
                for e in entries:
                    if e.get('is_short'): raw = (e['ep'] - cc) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    else: raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                entries = []
            curve.append(eq)
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m200 = ma200[idx]
        if m200 is None: continue

        bull = cc > m200
        bear = cc < m200

        # ── Trail exit ONLY (no force-close on trend flip) ──
        for e in entries[:]:
            if e.get('is_short'):
                e['lo'] = min(e.get('lo', bl), bl)
                if cc >= e['lo'] / TRAIL_PCT:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                    entries.remove(e)
            else:
                e['hi'] = max(e.get('hi', cc), hi)
                if cc <= e['hi'] * TRAIL_PCT:
                    raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                    entries.remove(e)

        # ── Entry (5-day cooldown) ──
        dep = sum(e.get('mp', ENTRY_SIZE) for e in entries)
        if dep < MAX_DEPLOYED and len(entries) < MAX_ENTRIES and (idx - lei >= 5):
            if bull:
                entries.append({'ep': cc, 'hi': cc, 'mp': ENTRY_SIZE, 'is_short': False}); lei = idx
            elif bear:
                entries.append({'ep': cc, 'lo': bl, 'mp': ENTRY_SIZE, 'is_short': True}); lei = idx

        # ── Track equity ──
        ureal = 0
        for e in entries:
            if e.get('is_short'): raw = (e['ep'] - cc) / e['ep'] * 100 * ENTRY_SIZE * LEV
            else: raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
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
    p = argparse.ArgumentParser()
    p.add_argument('--years', type=str); p.add_argument('--no-cache', action='store_true')
    args = p.parse_args()
    selected_years = set(int(y.strip()) for y in args.years.split(',')) if args.years else None
    data = load_data()
    results = []
    for coin in ['ETH', 'TRX']:
        da = data.get(f"{coin}USDT_4000_1609434000000", [])
        res = backtest_coin(coin, da, selected_years)
        if res[1]: results.append(res)
    if len(results) > 1:
        print(f"\nAvg CAGR: {sum(r[1]['cagr'] for r in results)/len(results):+.2f}%")

if __name__ == '__main__': main()
