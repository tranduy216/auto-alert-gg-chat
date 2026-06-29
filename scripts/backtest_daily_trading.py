"""
Backtest — Daily Trading (BNB & ETH) with pyramiding
- 12h/1D hybrid trend + pullback, multiple entries allowed
- 2% origin cap (10k) per entry, 2x leverage
- TP/SL calculated on avg entry price of all open entries
"""
import json, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from backtest_shared import sma, compute_results, atr

COINS = ['BNB', 'TRX']
CAPITAL_BASE = 10000
ENTRY_MARGIN_PCT = 0.02
LEV = 2.0
NOTIONAL = CAPITAL_BASE * ENTRY_MARGIN_PCT * LEV
ATR_PERIOD = 14
SL_ATR_MULT = 1.5
TP_ATR_MULT = 3.0
FALLBACK_TP_PCT = 0.06
FALLBACK_SL_PCT = 0.03
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
    h12h = [c['high'] for c in raw_12h]
    h12l = [c['low'] for c in raw_12h]
    h12m3, h12m7 = sma(h12c, 3), sma(h12c, 7)
    atr_vals = atr(h12h, h12l, h12c, ATR_PERIOD)

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

        atr_val = atr_vals[ri]
        if atr_val is None:
            tp_pct, sl_pct = FALLBACK_TP_PCT, FALLBACK_SL_PCT
        else:
            sl_pct = max(min((atr_val / cc) * SL_ATR_MULT, 0.10), 0.01)
            tp_pct = max(min((atr_val / cc) * TP_ATR_MULT, 0.20), 0.02)

        is_short = entries and entries[0].get('short', False)

        # ── Exit: check TP/SL on avg entry price ──
        if entries:
            aep = avg_ep(entries)
            if is_short:
                if hi >= aep * (1 + sl_pct):
                    # SL hit — close all
                    for e in entries:
                        ret = -sl_pct * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    losses += 1
                    entries = []
                elif lo <= aep * (1 - tp_pct):
                    # TP hit — close all
                    for e in entries:
                        ret = tp_pct * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    wins += 1
                    entries = []
            else:
                if lo <= aep * (1 - sl_pct):
                    for e in entries:
                        ret = -sl_pct * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
                        eq += ret
                    losses += 1
                    entries = []
                elif hi >= aep * (1 + tp_pct):
                    for e in entries:
                        ret = tp_pct * e['mp'] * LEV * (1 - 2 * FEE_RATE * LEV)
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
                    # If direction flips, close existing batch at current price
                    if entries and entries[0].get('short') != direction_short:
                        # Close existing at current price
                        for e in entries:
                            if entries[0].get('short'):
                                ret = (e['ep'] - cc) / e['ep'] * LEV * e['mp'] * (1 - 2 * FEE_RATE * LEV)
                            else:
                                ret = (cc - e['ep']) / e['ep'] * LEV * e['mp'] * (1 - 2 * FEE_RATE * LEV)
                            eq += ret
                        entries = []
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
    print(f"  TP={FALLBACK_TP_PCT*100:.0f}%/{FALLBACK_SL_PCT*100:.0f}% (fallback) — dynamic ATR-based")
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

    print(f"{'='*60}")
    print()


if __name__ == '__main__':
    main()
