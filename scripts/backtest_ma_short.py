"""
12h/1D Hybrid Trend + Pullback Strategy
- Trend: 1D MA3 > MA5 > MA7 → long | MA3 < MA5 < MA7 → short
- Entry: 12h — price near MA3 (1%), MA3 near MA7 (1%)
- TP 6%, SL 3%, 1% equity/entry, 1x leverage
- Coins: BNB, SOL, ETH
"""
import json, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from backtest_shared import sma, compute_results

COINS = ['BNB', 'SOL', 'ETH']
ENTRY_PCT = 0.01
TP_PCT = 0.06
SL_PCT = 0.03
LEV = 1.0
FEE_RATE = 0.0005
BASE = 10000
MA_NEAR_BUF = 0.01
PRICE_NEAR_BUF = 0.01


def load_12h():
    return json.loads((Path(__file__).parent / "_klines_12h_5y.json").read_text())


def backtest(coin, raw_12h):
    if len(raw_12h) < 20:
        return None, 0, 0

    # Daily bars
    nd = len(raw_12h) // 2
    daily = []
    for i in range(nd):
        b = raw_12h[i*2:i*2+2]
        daily.append({
            'close': b[-1]['close'],
            'high': max(x['high'] for x in b),
            'low': min(x['low'] for x in b),
        })

    dc = [b['close'] for b in daily]
    dh = [b['high'] for b in daily]
    dl = [b['low'] for b in daily]
    dma3 = sma(dc, 3)
    dma5 = sma(dc, 5)
    dma7 = sma(dc, 7)

    h12c = [c['close'] for c in raw_12h]
    h12h = [c['high'] for c in raw_12h]
    h12l = [c['low'] for c in raw_12h]
    h12m3 = sma(h12c, 3)
    h12m7 = sma(h12c, 7)

    eq = 1.0
    entries = []
    wins = 0
    losses = 0
    curve = []
    yearly = {}

    for ri in range(10, len(raw_12h)):
        di = ri // 2
        if di < 7 or di >= len(daily):
            continue

        d3, d5, d7 = dma3[di], dma5[di], dma7[di]
        if d3 is None or d5 is None or d7 is None:
            continue

        uptrend = d3 > d5 > d7
        downtrend = d3 < d5 < d7
        if not uptrend and not downtrend:
            continue

        cc = raw_12h[ri]['close']
        hi = raw_12h[ri]['high']
        lo = raw_12h[ri]['low']
        ts = raw_12h[ri]['open_time']
        dt = datetime.datetime.fromtimestamp(ts / 1000)

        m3 = h12m3[ri]
        m7 = h12m7[ri]
        if m3 is None or m7 is None:
            continue

        for e in list(entries):
            if ri <= e['ri']:
                continue
            if e.get('short'):
                if hi >= e['ep'] * (1 + SL_PCT):
                    eq += -SL_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                    entries.remove(e); losses += 1
                elif lo <= e['ep'] * (1 - TP_PCT):
                    eq += TP_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                    entries.remove(e); wins += 1
            else:
                if lo <= e['ep'] * (1 - SL_PCT):
                    eq += -SL_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                    entries.remove(e); losses += 1
                elif hi >= e['ep'] * (1 + TP_PCT):
                    eq += TP_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                    entries.remove(e); wins += 1

        ma_near = abs(m3 - m7) / m7 <= MA_NEAR_BUF
        price_near = abs(cc - m3) / m3 <= PRICE_NEAR_BUF

        if ma_near and price_near:
            if uptrend and not any(x['ri'] == ri for x in entries):
                dep = sum(x['mp'] for x in entries)
                if dep + ENTRY_PCT <= 1.0:
                    entries.append({'ep': cc, 'mp': ENTRY_PCT, 'ri': ri, 'short': False})
            elif downtrend and not any(x['ri'] == ri for x in entries):
                dep = sum(x['mp'] for x in entries)
                if dep + ENTRY_PCT <= 1.0:
                    entries.append({'ep': cc, 'mp': ENTRY_PCT, 'ri': ri, 'short': True})

        ureal = sum(
            (e['ep'] - cc) / e['ep'] * LEV * e['mp'] if e.get('short')
            else (cc - e['ep']) / e['ep'] * LEV * e['mp']
            for e in entries
        )
        total_eq = eq + ureal
        curve.append(total_eq)
        if dt.month == 12:
            yearly[dt.year] = total_eq

    if curve:
        last_yr = datetime.datetime.fromtimestamp(raw_12h[-1]['open_time'] / 1000).year
        if last_yr not in yearly:
            yearly[last_yr] = curve[-1]

    return compute_results(curve, yearly, BASE, days=len(curve)), wins, losses


def main():
    raw = load_12h()
    print("=" * 65)
    print("  12h/1D Hybrid Trend + Pullback")
    print("  Trend: 1D MA3>MA5>MA7 (long) | MA3<MA5<MA7 (short)")
    print("  Entry: 12h — price near MA3(1%), MA3 near MA7(1%)")
    print("  Exit:  TP=6%, SL=3%")
    print("  Size:  1% equity/entry, 1x")
    print("=" * 65)

    tw, tl = 0, 0
    for coin in COINS:
        key = next((k for k in raw if k.startswith(f'{coin}USDT_4000_')), None)
        if not key:
            print(f"  {coin}: no data")
            continue
        r = backtest(coin, raw[key])
        if not r or not r[0]:
            print(f"  {coin}: failed")
            continue
        res, wins, losses = r
        tt = wins + losses
        wr = wins / tt * 100 if tt > 0 else 0
        tw += wins; tl += losses
        print(f"\n  {coin}")
        print(f"  {'='*55}")
        print(f"    CAGR:   {res['cagr']:>+7.1f}%")
        print(f"    Max DD: {res['dd']:>7.1f}%")
        print(f"    Final:  ${res['final']:>9,.0f}")
        print(f"    Trades: {tt} (W:{wins} L:{losses}) WR: {wr:.1f}%")
        for y in sorted(res['yearly']):
            print(f"    {y}: {res['yearly'][y]:>+7.1f}%")
        print(f"    Longs:  {sum(1 for e in raw[key] if False)}")  # not tracked separately

    total_t = tw + tl
    print(f"\n{'='*65}")
    print(f"  TOTAL: {total_t} trades | WR: {tw/total_t*100:.1f}% ({tw}/{tl})")

    # Portfolio
    print(f"\n  PORTFOLIO (equal weight)")
    print(f"  {'='*55}")
    combined = {}
    for coin in COINS:
        key = next((k for k in raw if k.startswith(f'{coin}USDT_4000_')), None)
        if not key:
            continue
        r12 = raw[key]
        nd = len(r12) // 2
        daily = [{'close': r12[i*2+1]['close'] if i*2+1<len(r12) else r12[i*2]['close'],
                  'high': max(r12[i*2]['high'], r12[i*2+1]['high']),
                  'low': min(r12[i*2]['low'], r12[i*2+1]['low'])} for i in range(nd)]
        dc = [b['close'] for b in daily]
        dh = [b['high'] for b in daily]
        dl = [b['low'] for b in daily]
        dma3, dma5, dma7 = sma(dc,3), sma(dc,5), sma(dc,7)
        h12c = [c['close'] for c in r12]
        h12m3 = sma(h12c,3); h12m7 = sma(h12c,7)
        eq = 1.0; entries = []; pts = []
        for ri in range(10, len(r12)):
            di = ri // 2
            if di < 7 or di >= len(daily): continue
            d3, d5, d7 = dma3[di], dma5[di], dma7[di]
            if d3 is None or d5 is None or d7 is None: continue
            uptrend = d3 > d5 > d7; downtrend = d3 < d5 < d7
            if not uptrend and not downtrend: continue
            cc = r12[ri]['close']; hi = r12[ri]['high']; lo = r12[ri]['low']
            ts = r12[ri]['open_time']
            m3, m7 = h12m3[ri], h12m7[ri]
            if m3 is None or m7 is None: continue
            for e in list(entries):
                if ri <= e['ri']: continue
                if e.get('short'):
                    if hi >= e['ep']*(1+SL_PCT): eq += -SL_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV); entries.remove(e)
                    elif lo <= e['ep']*(1-TP_PCT): eq += TP_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV); entries.remove(e)
                else:
                    if lo <= e['ep']*(1-SL_PCT): eq += -SL_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV); entries.remove(e)
                    elif hi >= e['ep']*(1+TP_PCT): eq += TP_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV); entries.remove(e)
            ma_near = abs(m3-m7)/m7 <= MA_NEAR_BUF; price_near = abs(cc-m3)/m3 <= PRICE_NEAR_BUF
            if ma_near and price_near:
                if uptrend and not any(x['ri']==ri for x in entries):
                    dep = sum(x['mp'] for x in entries)
                    if dep + ENTRY_PCT <= 1.0: entries.append({'ep': cc, 'mp': ENTRY_PCT, 'ri': ri, 'short': False})
                elif downtrend and not any(x['ri']==ri for x in entries):
                    dep = sum(x['mp'] for x in entries)
                    if dep + ENTRY_PCT <= 1.0: entries.append({'ep': cc, 'mp': ENTRY_PCT, 'ri': ri, 'short': True})
            ureal = sum((e['ep']-cc)/e['ep']*LEV*e['mp'] if e.get('short') else (cc-e['ep'])/e['ep']*LEV*e['mp'] for e in entries)
            pts.append((ts, eq+ureal))
        combined[coin] = pts

    if len(combined) >= 2:
        merged = {}
        for pts in combined.values():
            for ts, v in pts:
                d = datetime.datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d')
                merged.setdefault(d, []).append(v)
        pf = []; py = {}; peak = 1.0; mdd = 0
        for d in sorted(merged):
            vals = merged[d]; av = sum(vals)/len(vals)
            pf.append(av)
            if av > peak: peak = av
            dd_cur = (peak-av)/peak*100
            if dd_cur > mdd: mdd = dd_cur
            yr = int(d[:4]); py[yr] = av
        pr = compute_results(pf, py, BASE)
        print(f"    CAGR:   {pr['cagr']:>+7.1f}%")
        print(f"    Max DD: {pr['dd']:>7.1f}%")
        print(f"    Final:  ${pr['final']:>9,.0f}")
        for y in sorted(pr['yearly']):
            print(f"    {y}: {pr['yearly'][y]:>+7.1f}%")

    print()


if __name__ == '__main__':
    main()
