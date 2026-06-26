"""
Unit tests for backtest_shared, combined_backtest, pooled_backtest.
Run: python3 -B -c "exec(open('scripts/test/test_all.py').read())"
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from crypto_trading import sma
from backtest_shared import (
    BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE, MAX_CAP, FEE_RATE,
    EXT_BLOCK_PCT, fee_factor,
    load_data, fetch_paxg, winner_mult, total_asset_value, compute_results,
)
from combined_backtest import backtest_coin as combined_backtest


failures = 0
def check(name, ok):
    global failures
    if ok: print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}")
        failures += 1


# ── shared: sma (from crypto_trading) ──
print("\n=== sma() ===")
check("period 3 basic", sma([1,2,3,4,5], 3) == [None, None, 2.0, 3.0, 4.0])
check("period too large", all(v is None for v in sma([1,2,3], 5)))
check("single value", sma([5], 1) == [5.0])
check("empty", sma([], 5) == [])
check("float input", sma([1.5, 2.5, 3.5], 2) == [None, 2.0, 3.0])
check("all same values", sma([10, 10, 10, 10], 2) == [None, 10.0, 10.0, 10.0])

# ── shared: constants ──
print("\n=== Constants ===")
check("BASE = 10000", BASE == 10000)
check("ENTRY_PCT = 0.015", ENTRY_PCT == 0.015)
check("TRAIL_PCT = 0.80", TRAIL_PCT == 0.80)
check("TP_SCHEDULE sum 1.0", sum(cf for _, cf in TP_SCHEDULE) == 1.0)
check("TP_SCHEDULE len 4", len(TP_SCHEDULE) == 4)
check("MAX_CAP = 0.75", MAX_CAP == 0.75)
check("FEE_RATE = 0.0005", FEE_RATE == 0.0005)
check("EXT_BLOCK_PCT = 30", EXT_BLOCK_PCT == 30)

# ── shared: fee_factor ──
print("\n=== fee_factor ===")
check("lev=1.5", round(fee_factor(1.5), 6) == 1 - 2 * 0.0005 * 1.5)
check("lev=1.0", round(fee_factor(1.0), 6) == 1 - 2 * 0.0005 * 1.0)
check("lev=2.0", round(fee_factor(2.0), 6) == 1 - 2 * 0.0005 * 2.0)
check("lev=0", fee_factor(0) == 1.0)

# ── shared: winner_mult ──
print("\n=== winner_mult() ===")
check("no entries", winner_mult([], 100, False, 1.5) == 1.0)
check("avg ROI >15", winner_mult([{'ep':90},{'ep':80}], 100, False, 1.5) == 2.5)
check("avg ROI 10-15", winner_mult([{'ep':92}], 100, False, 1.5) == 2.0)  # 13.04% → >10
check("avg ROI 5-10", winner_mult([{'ep':95}], 100, False, 1.5) == 1.5)   # 7.89% → >5
check("avg ROI 0-5", winner_mult([{'ep':98}], 100, False, 1.5) == 1.2)    # 3.06% → >0
check("avg ROI -5-0", winner_mult([{'ep':100}], 97, False, 1.5) == 0.75)  # -4.5% → >-5
check("avg ROI <-5", winner_mult([{'ep':100}], 95, False, 1.5) == 0.5)    # -7.5% → < -5
check("short profit", winner_mult([{'ep':100}], 90, True, 1.5) == 2.0)    # 15% → >10
check("leverage 2x", winner_mult([{'ep':80}], 84, False, 2.0) == 1.5)     # 10% → >5

# ── shared: total_asset_value ──
print("\n=== total_asset_value() ===")
check("no entries", abs(total_asset_value([], 100, 1.0, 1.5) - 1.0) < 1e-10)
check("one long entry profit", abs(total_asset_value(
    [{'ep': 90, 'mp': 0.1, 'rem': 1.0}], 100, 1.0, 1.5) - (1.0 + (10/90)*0.1*1.5)) < 1e-9)
check("one short entry profit", abs(total_asset_value(
    [{'ep': 100, 'mp': 0.1, 'rem': 1.0, 'is_short': True}], 90, 1.0, 1.5) -
    (1.0 + (10/100)*0.1*1.5)) < 1e-9)
check("partial rem", abs(total_asset_value(
    [{'ep': 90, 'mp': 0.1, 'rem': 0.4}], 100, 1.0, 1.5) -
    (1.0 + (10/90)*0.1*1.5*0.4)) < 1e-9)
check("zero entries list", abs(total_asset_value([], 100, 1.0, 1.5) - 1.0) < 1e-10)

# ── shared: compute_results ──
print("\n=== compute_results() ===")
r = compute_results([1.0, 1.1, 1.2], {2021: 1.2}, 10000)
check("CAGR positive", r['cagr'] > 0)
check("MD > 0", r['dd'] >= 0)
check("yearly key", 2021 in r['yearly'])
check("final computed", r['final'] > 10000)
check("returns dict", all(k in r for k in ['cagr','dd','final','yearly']))

r2 = compute_results([1.0, 0.9, 0.8], {2021: 0.8}, 10000)
check("CAGR negative", r2['cagr'] < 0)
check("MD ~20%", abs(r2['dd'] - 20.0) < 0.1)
check("final < initial", r2['final'] < 10000)

r3 = compute_results([], {}, 10000)
check("empty curve uses default", r3['cagr'] == 0)

# ── shared: load_data ──
print("\n=== load_data() ===")
data = load_data()
check("load_data returns dict", isinstance(data, dict))
check("has TRX", any('TRX' in k for k in data))
check("has BTC", any('BTC' in k for k in data))
sample = list(data.values())[0]
check("data has bars", len(sample) > 0)
if sample:
    bar = sample[0]
    check("bar has all fields", all(k in bar for k in ['close','high','low','volume','time']))
    check("bar high >= close", bar['high'] >= bar['close'])
    check("bar low <= close", bar['low'] <= bar['close'])
    check("bar volume >= 0", bar['volume'] >= 0)

# ── combined_backtest ──
print("\n=== combined_backtest: backtest_coin() ===")
_, r_none = combined_backtest('TEST', [], None, False, 1.0, None, None)
check("short data -> None", r_none is None)

btc_da = data.get('BTCUSDT_4000_1609434000000', [])
trx_da = data.get('TRXUSDT_4000_1609434000000', [])

_, r = combined_backtest('TRX', trx_da, btc_da, False, MAX_CAP, None, None)
check("result not None", r is not None)
check("has all keys", all(k in r for k in ['cagr','dd','final','yearly','ts_curve']))
check("yearly has years", len(r['yearly']) >= 3)
check("ts_curve length", len(r['ts_curve']) > 100)

# Config override
cfg = {'ma': 20, 'buf': 0.03, 'pyr': 5, 'lev': 1.5}
_, r_cfg = combined_backtest('TRX', trx_da, btc_da, False, MAX_CAP, None, cfg)
check("cfg override works", abs(r_cfg['cagr']) < 500)

# Short mode
_, r_short = combined_backtest('BTC', btc_da, btc_da, True, MAX_CAP, None, cfg)
check("short mode works", r_short is not None)
check("short has yearly", 'yearly' in r_short)

# Selected years
_, r_sel = combined_backtest('TRX', trx_da, btc_da, False, MAX_CAP, {2021, 2022}, None)
check("selected_years has 2021", 2021 in r_sel['yearly'])
check("selected_years has 2022", 2022 in r_sel['yearly'])

# Extension block config
cfg_ext = {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8, 'ext_block': 0}
_, r_ext = combined_backtest('TRX', trx_da, btc_da, False, MAX_CAP, None, cfg_ext)
check("ext_block override works", r_ext is not None)

# Portfolio merge
curves = [r['ts_curve'], r_short['ts_curve']]
merged = {}
for curve in curves:
    for ts, eq in curve:
        merged[ts] = merged.get(ts, []) + [eq]
tss = sorted(merged.keys())
pf_eq = [sum(merged[ts])/len(merged[ts]) for ts in tss if len(merged[ts]) == 2]
check("merged portfolio", len(pf_eq) > 0)
check("all equities positive", all(e > 0 for e in pf_eq))

# ── Verify combined vs pooled consistency (1-coin) ──
print("\n=== Pooled 1-coin ===")
from pooled_backtest import run_pooled
cfg = {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}
r_pooled = run_pooled(data, [('TRX-L', 'TRXUSDT_4000_1609434000000', False, cfg)])

_, r_single = combined_backtest('TRX', trx_da, btc_da, False, MAX_CAP, None, cfg)
check("CAGR within 2%", abs(r_pooled['cagr'] - r_single['cagr']) < 2.0)
check("DD within 2%", abs(r_pooled['dd'] - r_single['dd']) < 2.0)
check("final within 10%", abs(r_pooled['final'] / r_single['final'] - 1) < 0.10)


# ── BTC regime consistency ──
print("\n=== BTC regime ===")
_, r_btc_bear = combined_backtest('BTC', btc_da, btc_da, True, MAX_CAP, {2022}, cfg)
# 2022 was bear, should be positive CAGR
check("BTC short in 2022 > 0", abs(r_btc_bear['cagr']) > 0)


# ── Field invariants ──
print("\n=== Field invariants ===")
for e in [{'ep': 100, 'mp': 0.1, 'rem': 1.0}, {'ep': 80, 'mp': 0.05, 'rem': 0.5}]:
    for k in ['ep', 'mp', 'rem']:
        check(f"entry has field {k}", k in e)
check("tp_schedule entries have 2 fields", all(len(t) == 2 for t in TP_SCHEDULE))
check("tp_schedule targets ascending", all(
    TP_SCHEDULE[i][0] < TP_SCHEDULE[i+1][0] for i in range(len(TP_SCHEDULE)-1)))


# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {failures} failures")
print(f"{'='*40}")
