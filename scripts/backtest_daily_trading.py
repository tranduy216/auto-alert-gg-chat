"""
Backtest — Daily Trading (BNB & ETH) with pyramiding
- 12h/1D hybrid trend + pullback, multiple entries allowed
- 2% origin cap (10k) per entry, 2x leverage
- TP/SL calculated on avg entry price of all open entries
"""
import json, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from backtest_shared import sma, compute_results

COINS = ['BNB']
CAPITAL_BASE = 10000
ENTRY_MARGIN_PCT = 0.02
LEV = 2.0
NOTIONAL = CAPITAL_BASE * ENTRY_MARGIN_PCT * LEV
TP_PCT = 0.06
SL_PCT = 0.03
FEE_RATE = 0.0005
MA_NEAR_BUF = 0.01
PRICE_NEAR_BUF = 0.01


def load_12h():
    return json.loads((Path(__file__).parent / "_klines_12h_5y.json").read_text())


def avg_ep(entries):
    if not entries:
        return None
    total_w = sum(e.get('mp', 1) for e in entries)
    weighted = sum(e['ep'] * e.get('mp', 1) for e in entries)
    return weighted / total_w


def backtest(coin, raw_12h):
    if len(raw_12h) < 20:
        return None, 0, 0, 0

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
    dma3, dma5, dma7 = sma(dc, 3), sma(dc, 5), sma(dc, 7)

    h12c = [c['close'] for c in raw_12h]
    h12m3, h12m7 = sma(h12c, 3), sma(h12c, 7)

    eq = 1.0
    entries = []
    wins = 0
    losses = 0
    total_entries = 0
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

        cc = raw_12h[ri]['close']
        hi = raw_12h[ri]['high']
        lo = raw_12h[ri]['low']
        ts = raw_12h[ri]['open_time']
        dt = datetime.datetime.fromtimestamp(ts / 1000)

        m3, m7 = h12m3[ri], h12m7[ri]
        if m3 is None or m7 is None:
            continue

        is_short = entries and entries[0].get('short', False)

        # ── Exit: check TP/SL on avg entry price ──
        if entries:
            aep = avg_ep(entries)
            if is_short:
                if hi >= aep * (1 + SL_PCT):
                    # SL hit — close all
                    for e in entries:
                        ret = -SL_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    losses += 1
                    entries = []
                elif lo <= aep * (1 - TP_PCT):
                    # TP hit — close all
                    for e in entries:
                        ret = TP_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    wins += 1
                    entries = []
            else:
                if lo <= aep * (1 - SL_PCT):
                    for e in entries:
                        ret = -SL_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    losses += 1
                    entries = []
                elif hi >= aep * (1 + TP_PCT):
                    for e in entries:
                        ret = TP_PCT * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    wins += 1
                    entries = []

        # ── Entry — allow pyramiding ──
        if uptrend or downtrend:
            ma_near = abs(m3 - m7) / m7 <= MA_NEAR_BUF
            price_near = abs(cc - m3) / m3 <= PRICE_NEAR_BUF

            if ma_near and price_near:
                already = any(e['ri'] == ri for e in entries)
                if not already:
                    direction_short = downtrend
                    # Verify direction consistency
                    if entries:
                        if entries[0].get('short') != direction_short:
                            pass  # signal flipped — let it enter opposite
                    entries.append({
                        'ep': cc,
                        'mp': ENTRY_MARGIN_PCT,
                        'ri': ri,
                        'short': direction_short,
                    })
                    total_entries += 1

        # ── Unrealized PnL ──
        if entries:
            aep = avg_ep(entries)
            is_sh = entries[0].get('short', False)
            if is_sh:
                ureal = (aep - cc) / aep * LEV * sum(e['mp'] for e in entries)
            else:
                ureal = (cc - aep) / aep * LEV * sum(e['mp'] for e in entries)
        else:
            ureal = 0

        total_eq = eq + ureal
        curve.append(total_eq)
        if dt.month == 12:
            yearly[dt.year] = total_eq

    if curve:
        last_yr = datetime.datetime.fromtimestamp(raw_12h[-1]['open_time'] / 1000).year
        if last_yr not in yearly:
            yearly[last_yr] = curve[-1]

    return compute_results(curve, yearly, CAPITAL_BASE, days=len(curve)), wins, losses, total_entries


def main():
    raw = load_12h()
    print("=" * 60)
    print("  Daily Trading Backtest (pyramiding)")
    print(f"  Strategy: 12h/1D hybrid, multiple entries allowed")
    print(f"  Size: {ENTRY_MARGIN_PCT*100:.0f}% margin @ {LEV}x = ${NOTIONAL:,.0f}/entry")
    print(f"  TP={TP_PCT*100:.0f}%  SL={SL_PCT*100:.0f}%  (on avg entry price)")
    print("=" * 60)

    tw, tl, te = 0, 0, 0
    for coin in COINS:
        key = next((k for k in raw if k.startswith(f'{coin}USDT_4000_')), None)
        if not key:
            print(f"  {coin}: no data")
            continue
        r = backtest(coin, raw[key])
        if not r or not r[0]:
            print(f"  {coin}: failed")
            continue
        res, wins, losses, tentries = r
        tt = wins + losses
        wr = wins / tt * 100 if tt > 0 else 0
        tw += wins; tl += losses; te += tentries
        pf = res['final'] / CAPITAL_BASE
        print(f"\n  {coin}")
        print(f"  {'='*50}")
        print(f"    CAGR:          {res['cagr']:>+7.1f}%")
        print(f"    Max DD:        {res['dd']:>7.1f}%")
        print(f"    Final:         ${res['final']:>9,.0f}")
        print(f"    Profit factor: {pf:.2f}x")
        print(f"    Batches:       {tt} (W:{wins} L:{losses}) WR: {wr:.1f}%")
        print(f"    Total entries: {tentries} ({tentries/tt:.1f}/batch avg)")
        for y in sorted(res['yearly']):
            print(f"    {y}: {res['yearly'][y]:>+7.1f}%")

    total_t = tw + tl
    print(f"\n{'='*60}")
    print(f"  TOTAL: {total_t} trade batches | WR: {tw/total_t*100:.1f}% ({tw}/{tl})")
    print(f"  Total entries: {te}")
    print(f"{'='*60}")

    # Portfolio
    print(f"\n  PORTFOLIO (equal weight)")
    print(f"  {'='*50}")
    combined = {}
    for coin in COINS:
        key = next((k for k in raw if k.startswith(f'{coin}USDT_4000_')), None)
        if not key: continue
        r12 = raw[key]
        nd = len(r12) // 2
        daily = [{'close': r12[i*2+1]['close'] if i*2+1<len(r12) else r12[i*2]['close'],
                  'high': max(x['high'] for x in (r12[i*2], r12[i*2+1])),
                  'low': min(x['low'] for x in (r12[i*2], r12[i*2+1]))} for i in range(nd)]
        dc = [b['close'] for b in daily]
        dh = [b['high'] for b in daily]
        dl = [b['low'] for b in daily]
        dma3, dma5, dma7 = sma(dc,3), sma(dc,5), sma(dc,7)
        h12c = [c['close'] for c in r12]; h12m3 = sma(h12c,3); h12m7 = sma(h12c,7)
        eq = 1.0; entries = []; pts = []
        for ri in range(10, len(r12)):
            di = ri//2
            if di<7 or di>=len(daily): continue
            d3,d5,d7 = dma3[di],dma5[di],dma7[di]
            if d3 is None or d5 is None or d7 is None: continue
            uptrend=d3>d5>d7; downtrend=d3<d5<d7
            cc=r12[ri]['close']; hi=r12[ri]['high']; lo=r12[ri]['low']; ts=r12[ri]['open_time']
            m3,m7 = h12m3[ri],h12m7[ri]
            if m3 is None or m7 is None: continue
            if entries:
                is_sh = entries[0].get('short', False)
                aep = sum(e['ep']*e['mp'] for e in entries) / sum(e['mp'] for e in entries)
                if is_sh:
                    if hi >= aep*(1+SL_PCT):
                        for e in entries: eq += -SL_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV)
                        entries = []
                    elif lo <= aep*(1-TP_PCT):
                        for e in entries: eq += TP_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV)
                        entries = []
                else:
                    if lo <= aep*(1-SL_PCT):
                        for e in entries: eq += -SL_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV)
                        entries = []
                    elif hi >= aep*(1+TP_PCT):
                        for e in entries: eq += TP_PCT*e['mp']*LEV*(1-2*FEE_RATE*LEV)
                        entries = []
            if uptrend or downtrend:
                if abs(m3-m7)/m7 <= MA_NEAR_BUF and abs(cc-m3)/m3 <= PRICE_NEAR_BUF:
                    if not any(e['ri']==ri for e in entries):
                        entries.append({'ep': cc, 'mp': ENTRY_MARGIN_PCT, 'ri': ri, 'short': downtrend})
            if entries:
                is_sh = entries[0].get('short', False)
                aep = sum(e['ep']*e['mp'] for e in entries) / sum(e['mp'] for e in entries)
                total_mp = sum(e['mp'] for e in entries)
                if is_sh: ureal = (aep-cc)/aep*LEV*total_mp
                else: ureal = (cc-aep)/aep*LEV*total_mp
            else: ureal = 0
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
            dd = (peak-av)/peak*100
            if dd > mdd: mdd = dd
            yr = int(d[:4]); py[yr] = av
        pr = compute_results(pf, py, CAPITAL_BASE)
        print(f"    CAGR:     {pr['cagr']:>+7.1f}%")
        print(f"    Max DD:   {pr['dd']:>7.1f}%")
        print(f"    Final:    ${pr['final']:>9,.0f}")
        for y in sorted(pr['yearly']):
            print(f"    {y}: {pr['yearly'][y]:>+7.1f}%")

    print()


if __name__ == '__main__':
    main()
