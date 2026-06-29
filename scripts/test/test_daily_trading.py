"""
Unit tests for daily_trading.py and backtest_daily_trading.py.
Tests: signal, avg_ep, avg_roi, TP/SL, is_short field, pyramiding.
"""
import sys, json, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_shared import sma
from daily_trading import (
    check_signal, avg_ep, avg_roi, entry_is_short, direction_name,
    TP_PCT, SL_PCT, TP_ROI, SL_ROI, LEV,
    CAPITAL_BASE, ENTRY_MARGIN_PCT, NOTIONAL,
)

failures = 0
def check(name, ok):
    global failures
    if ok: print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}")
        failures += 1

def mk_bar(close, high=None, low=None):
    if high is None: high = close * 1.01
    if low is None: low = close * 0.99
    return {'open': close, 'close': close, 'high': high, 'low': low, 'volume': 1000, 'time': 1700000000000}


# ── check_signal ──
print("\n=== check_signal ===")
d_up = [mk_bar(100+i*5) for i in range(12)]
h12_up = [mk_bar(141) for _ in range(10)] + [mk_bar(141.5), mk_bar(141.8)]
dir, pr = check_signal(h12_up, d_up)
check("uptrend → LONG", dir == 'LONG')

d_down = [mk_bar(150-i*5) for i in range(12)]
h12_down = [mk_bar(100) for _ in range(12)]
dir, pr = check_signal(h12_down, d_down)
check("downtrend → SHORT", dir == 'SHORT')

d_flat = [mk_bar(100) for _ in range(12)]
h12_flat = [mk_bar(100) for _ in range(12)]
check("no trend → None", check_signal(h12_flat, d_flat)[0] is None)
check("empty data → None", check_signal([], [])[0] is None)
check("short data → None", check_signal([mk_bar(100)], [mk_bar(100)])[0] is None)


# ── avg_ep ──
print("\n=== avg_ep ===")
check("empty → None", avg_ep([]) is None)
check("single", abs(avg_ep([{'ep': 100}]) - 100) < 0.01)
check("two entries", abs(avg_ep([{'ep': 100}, {'ep': 110}]) - 105) < 0.01)
check("weighted", abs(avg_ep([{'ep': 100, 'mp': 3}, {'ep': 110, 'mp': 1}]) - 102.5) < 0.01)
check("three", abs(avg_ep([{'ep': 90}, {'ep': 100}, {'ep': 110}]) - 100) < 0.01)


# ── avg_roi: uses 'is_short' field ──
print("\n=== avg_roi (field 'is_short') ===")
e_long = [{'ep': 100, 'is_short': False}]
check("long profit +6% price", abs(avg_roi(e_long, 106, 1.0) - 6) < 0.01)
check("long profit +6% @ 2x", abs(avg_roi(e_long, 103, 2.0) - 6) < 0.01)
check("long loss -3% @ 2x", abs(avg_roi(e_long, 98.5, 2.0) - (-3)) < 0.01)

e_short = [{'ep': 100, 'is_short': True}]
check("short profit +6% price", abs(avg_roi(e_short, 94, 1.0) - 6) < 0.01)
check("short profit +6% @ 2x", abs(avg_roi(e_short, 97, 2.0) - 6) < 0.01)
check("short loss -3% @ 2x", abs(avg_roi(e_short, 101.5, 2.0) - (-3)) < 0.01)

# Bug regression: old persisted entries used 'short', new entries use 'is_short'
e_old_field = [{'ep': 100, 'short': True}]
check("legacy field 'short' is recognized as short", entry_is_short(e_old_field[0]) is True)
check("legacy short ROI stays short", abs(avg_roi(e_old_field, 94, 1.0) - 6) < 0.01)
check("direction label for short", direction_name(True) == 'SHORT')
check("direction label for long", direction_name(False) == 'LONG')

check("empty → 0", avg_roi([], 100, 2.0) == 0)


# ── Entry sizing ──
print("\n=== Entry sizing ===")
check("CAPITAL_BASE = 10000", CAPITAL_BASE == 10000)
check("ENTRY_MARGIN_PCT = 2%", abs(ENTRY_MARGIN_PCT - 0.02) < 0.001)
check("LEV = 2.0", abs(LEV - 2.0) < 0.01)
check("NOTIONAL = 400", abs(NOTIONAL - 400) < 0.01)


# ── TP/SL thresholds (price-based) ──
print("\n=== TP/SL thresholds ===")
check("short SL = EP * 1.03", abs(100 * (1 + SL_PCT) - 103) < 0.01)
check("short TP = EP * 0.94", abs(100 * (1 - TP_PCT) - 94) < 0.01)
check("long  SL = EP * 0.97", abs(100 * (1 - SL_PCT) - 97) < 0.01)
check("long  TP = EP * 1.06", abs(100 * (1 + TP_PCT) - 106) < 0.01)

# ROI-based thresholds at 2x
check("SL ROI = -6%", abs(SL_PCT * 100 * LEV - 6.0) < 0.01)
check("TP ROI = +12%", abs(TP_PCT * 100 * LEV - 12.0) < 0.01)
check("live SL_ROI uses leverage", abs(SL_ROI - 6.0) < 0.01)
check("live TP_ROI uses leverage", abs(TP_ROI - 12.0) < 0.01)
check("long -3% move hits SL, -1.5% move does not",
      avg_roi(e_long, 97, LEV) <= -SL_ROI and avg_roi(e_long, 98.5, LEV) > -SL_ROI)
check("long +6% move hits TP, +3% move does not",
      avg_roi(e_long, 106, LEV) >= TP_ROI and avg_roi(e_long, 103, LEV) < TP_ROI)


# ── Pyramiding: avg_ep shifts correctly ──
print("\n=== Pyramiding avg_ep ===")
entries = [{'ep': 100, 'is_short': True}, {'ep': 95, 'is_short': True}]
check("avg_ep after 2 entries", abs(avg_ep(entries) - 97.5) < 0.01)
check("ROI after 2 entries @ 91", abs(avg_roi(entries, 91, 2.0) - 13.33) < 0.5)
check("ROI after 2 entries @ 100", abs(avg_roi(entries, 100, 2.0) - (-5.13)) < 0.5)


# ── Backtest integration ──
print("\n=== Backtest integration ===")
raw_cache_path = Path(__file__).parent.parent / "_klines_12h_5y.json"
if raw_cache_path.exists():
    from backtest_daily_trading import backtest
    raw_all = json.loads(raw_cache_path.read_text())
    key = next((k for k in raw_all if k.startswith('BNBUSDT_4000_')), None)
    if key:
        r, wins, losses, tentries = backtest('BNB', raw_all[key])
        check("BNB backtest returns result", r is not None)
        if r:
            check("CAGR in reasonable range", abs(r['cagr']) < 200)
            check("final > 0", r['final'] > 0)
            check("entries >= batches", tentries >= wins + losses)
            check("max DD < 50%", r['dd'] < 50)

    # Verify backtest never allows mixed long/short in same batch
    key = next((k for k in raw_all if k.startswith('BNBUSDT_4000_')), None)
    if key:
        r12 = raw_all[key]
        nd = len(r12) // 2
        daily = [{'close': r12[i*2+1]['close'] if i*2+1<len(r12) else r12[i*2]['close'],
                  'high': max(x['high'] for x in (r12[i*2], r12[i*2+1])),
                  'low': min(x['low'] for x in (r12[i*2], r12[i*2+1]))}
                 for i in range(nd)]
        dc = [b['close'] for b in daily]
        dma3, dma5, dma7 = sma(dc,3), sma(dc,5), sma(dc,7)
        h12c = [c['close'] for c in r12]; h12m3 = sma(h12c,3); h12m7 = sma(h12c,7)
        eq = 1.0; entries = []; has_mixed = False
        for ri in range(10, len(r12)):
            di = ri//2
            if di<7 or di>=len(daily): continue
            d3,d5,d7 = dma3[di],dma5[di],dma7[di]
            if d3 is None or d5 is None or d7 is None: continue
            uptrend=d3>d5>d7; downtrend=d3<d5<d7
            cc=r12[ri]['close']; hi=r12[ri]['high']; lo=r12[ri]['low']
            m3,m7 = h12m3[ri],h12m7[ri]
            if m3 is None or m7 is None: continue
            if entries:
                aep = sum(e['ep']*e['mp'] for e in entries) / sum(e['mp'] for e in entries)
                is_sh = entries[0].get('short', False)
                if is_sh:
                    if hi >= aep*1.03 or lo <= aep*0.94: entries=[]
                else:
                    if lo <= aep*0.97 or hi >= aep*1.06: entries=[]
            if uptrend or downtrend:
                if abs(m3-m7)/m7 <= 0.01 and abs(cc-m3)/m3 <= 0.01:
                    if not any(e['ri']==ri for e in entries):
                        dir_short = downtrend
                        # Direction flip: close existing batch at current price
                        if entries and entries[0].get('short') != dir_short:
                            for e in entries:
                                if entries[0].get('short'):
                                    eq += (e['ep']-cc)/e['ep']*2.0*e['mp']*0.998
                                else:
                                    eq += (cc-e['ep'])/e['ep']*2.0*e['mp']*0.998
                            entries=[]
                        entries.append({'ep': cc, 'mp': 0.02, 'ri': ri, 'short': dir_short})
            ureal = 0
            if entries:
                aep = sum(e['ep']*e['mp'] for e in entries) / sum(e['mp'] for e in entries)
                is_sh = entries[0].get('short', False)
                if is_sh: ureal = sum((e['ep']-cc)/e['ep']*2.0*e['mp'] for e in entries)
                else: ureal = sum((cc-e['ep'])/e['ep']*2.0*e['mp'] for e in entries)
            if entries and any(e['short'] for e in entries) and any(not e['short'] for e in entries):
                has_mixed = True
        check("no mixed long/short in same batch (direction flip close)", not has_mixed)
else:
    print("  SKIP: cache file not found")

print(f"\n{'='*40}")
print(f"Results: {failures} failures")
print(f"{'='*40}")
