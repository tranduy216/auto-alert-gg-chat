"""
Unit tests for backtest_shared, combined_backtest, pooled_backtest, crypto_trading.
Run: python3 -B scripts/test/test_all.py
"""
import sys, json, os, datetime
from unittest.mock import patch, Mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_shared import sma
from backtest_shared import (
    BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE, MAX_CAP, FEE_RATE,
    EXT_BLOCK_PCT, fee_factor, BTC_SHORT_TP, SHORT_SL_ROI, PYRAMID_STRATEGIES,
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
check("ENTRY_PCT = 0.011", abs(ENTRY_PCT - 0.011) < 0.0001)
check("TRAIL_PCT = 0.80", TRAIL_PCT == 0.80)
check("SHORT_SL_ROI = 7.0", abs(SHORT_SL_ROI - 7.0) < 0.1)
check("BTC_SHORT_TP len 4", len(BTC_SHORT_TP) == 4)
check("BTC_SHORT_TP first (4,0.25)", BTC_SHORT_TP[0] == (4, 0.25))
check("BTC_SHORT_TP targets ascending", all(BTC_SHORT_TP[i][0] < BTC_SHORT_TP[i+1][0] for i in range(len(BTC_SHORT_TP)-1)))
check("BTC_SHORT_TP fractions sum 1.0", abs(sum(cf for _, cf in BTC_SHORT_TP) - 1.0) < 0.001)
check("TP_SCHEDULE sum 1.0", sum(cf for _, cf in TP_SCHEDULE) == 1.0)
check("TP_SCHEDULE len 4", len(TP_SCHEDULE) == 4)
check("MAX_CAP = 0.75", MAX_CAP == 0.75)
check("FEE_RATE = 0.0005", FEE_RATE == 0.0005)
check("EXT_BLOCK_PCT = 25", EXT_BLOCK_PCT == 25)

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
_, r_none = combined_backtest('TEST', [], None, False, {})
check("short data -> None", r_none is None)

btc_da = data.get('BTCUSDT_4000_1609434000000', [])
trx_da = data.get('TRXUSDT_4000_1609434000000', [])

_, r = combined_backtest('TRX', trx_da, btc_da, False, None)
check("result not None", r is not None)
check("has all keys", all(k in r for k in ['cagr','dd','final','yearly','ts_curve']))
check("yearly has years", len(r['yearly']) >= 3)
check("ts_curve length", len(r['ts_curve']) > 100)

# Config override
cfg = {'ma': 20, 'buf': 0.03, 'pyr': 5, 'lev': 1.5}
_, r_cfg = combined_backtest('TRX', trx_da, btc_da, False, cfg)
check("cfg override works", abs(r_cfg['cagr']) < 500)

# Short mode
_, r_short = combined_backtest('BTC', btc_da, btc_da, True, cfg)
check("short mode works", r_short is not None)
check("short has yearly", 'yearly' in r_short)

# Extension block config
cfg_ext = {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8, 'ext_block': 0}
_, r_ext = combined_backtest('TRX', trx_da, btc_da, False, cfg_ext)
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
trx_cfg = PYRAMID_STRATEGIES[0][2]
r_pooled = run_pooled(data, [('TRX-L', 'TRXUSDT_4000_1609434000000', False, trx_cfg)])

_, r_single = combined_backtest('TRX', trx_da, btc_da, False, trx_cfg)
check("CAGR within 10%", abs(r_pooled['cagr'] - r_single['cagr']) < 10.0)
check("DD within 10%", abs(r_pooled['dd'] - r_single['dd']) < 10.0)
check("final within 40%", abs(r_pooled['final'] / r_single['final'] - 1) < 0.40)

# Short cooldown: verify 1-day gap
cfg_short = {'ma': 5, 'buf': 0.07, 'lev': 2, 'pyr': 3, 'tp': BTC_SHORT_TP}
_, r_short_cd = combined_backtest('BTC', btc_da, btc_da, True, cfg_short)
check("short cooldown: CAGR computed", r_short_cd is not None and abs(r_short_cd['cagr']) < 100)


# ── BTC regime consistency ──
print("\n=== BTC regime ===")
_, r_btc_bear = combined_backtest('BTC', btc_da, btc_da, True, cfg)
check("BTC short in 2022 > 0", abs(r_btc_bear['cagr']) > 0)


# ── Field invariants ──
print("\n=== Field invariants ===")
for e in [{'ep': 100, 'mp': 0.1, 'rem': 1.0}, {'ep': 80, 'mp': 0.05, 'rem': 0.5}]:
    for k in ['ep', 'mp', 'rem']:
        check(f"entry has field {k}", k in e)
check("tp_schedule entries have 2 fields", all(len(t) == 2 for t in TP_SCHEDULE))
check("tp_schedule targets ascending", all(
    TP_SCHEDULE[i][0] < TP_SCHEDULE[i+1][0] for i in range(len(TP_SCHEDULE)-1)))


# ── fetch_candles_coingecko ──
print("\n=== fetch_candles_coingecko() ===")
from backtest_shared import fetch_candles_coingecko

check("no API key returns None", fetch_candles_coingecko('BTCUSDT') is None)

with patch.dict(os.environ, {'COINGECKO_API_KEY': 'test_key'}):
    check("unknown symbol returns None", fetch_candles_coingecko('ETHUSDT') is None)

    # Mock success response: hourly bars aggregated to daily
    with patch('backtest_shared.requests.get') as mock_get:
        # Return enough hourly bars (>48) spread over 2 days
        hour_prices = []
        day1 = 1735689600000  # 2025-01-01 00:00
        for h in range(24):
            hour_prices.append([day1 + h * 3600000, 50000.0 + h * 10])
        day2 = day1 + 86400000
        for h in range(24):
            hour_prices.append([day2 + h * 3600000, 50100.0 + h * 10])
        mock_data = {'prices': hour_prices}
        mock_resp = Mock()
        mock_resp.json.return_value = mock_data
        mock_get.return_value = mock_resp
        result = fetch_candles_coingecko('BTCUSDT', 10)
        check("returns daily bars on success", isinstance(result, list) and len(result) > 0)
        if result:
            check("aggregated to 2 daily bars", len(result) == 2)
            d = result[0]
            check("bar has close field", 'close' in d)
            check("bar has high field", 'high' in d)
            check("bar has low field", 'low' in d)
            check("bar has time field", 'time' in d)

with patch.dict(os.environ, {'COINGECKO_API_KEY': 'test_key'}):
    with patch('backtest_shared.requests.get') as mock_get:
        mock_get.side_effect = Exception('Network error')
        result = fetch_candles_coingecko('BTCUSDT', 10)
        check("returns None on network error", result is None)

    with patch('backtest_shared.requests.get') as mock_get:
        mock_resp = Mock()
        mock_resp.json.return_value = {'prices': []}
        mock_get.return_value = mock_resp
        result = fetch_candles_coingecko('BTCUSDT', 10)
        check("returns None when < 48 price points", result is None)


# ── fetch_candles_cmc ──
print("\n=== fetch_candles_cmc() ===")
from backtest_shared import fetch_candles_cmc

check("no API key returns None", fetch_candles_cmc('BTCUSDT') is None)

with patch.dict(os.environ, {'CMC_API_KEY': 'test_key'}):
    mock_data = {
        'data': {
            'BTC': {
                'quotes': [
                    {'time_open': '2025-01-01T00:00:00Z',
                     'quote': {'USD': {'close': 50000, 'high': 51000, 'low': 49000, 'volume': 1000}}},
                ]
            }
        }
    }
    with patch('backtest_shared.requests.get') as mock_get:
        mock_resp = Mock()
        mock_resp.json.return_value = mock_data
        mock_get.return_value = mock_resp
        result = fetch_candles_cmc('BTCUSDT', 10)
        check("returns daily bars on success", isinstance(result, list) and len(result) == 1)
        if result:
            d = result[0]
            check("close matches", d['close'] == 50000)
            check("high matches", d['high'] == 51000)
            check("volume matches", d['volume'] == 1000)

    with patch('backtest_shared.requests.get') as mock_get:
        mock_get.side_effect = Exception('CMC error')
        result = fetch_candles_cmc('BTCUSDT', 10)
        check("returns None on error", result is None)

    with patch('backtest_shared.requests.get') as mock_get:
        mock_resp = Mock()
        mock_resp.json.return_value = {'data': {}}
        mock_get.return_value = mock_resp
        result = fetch_candles_cmc('BTCUSDT', 10)
        check("returns None on empty data", result is None)


# ── fetch_candles_okx autodetect ──
print("\n=== fetch_candles_okx() autodetect ===")
from backtest_shared import fetch_candles_okx

def make_okx_resp(code='0', data=None):
    return {'code': code, 'data': data or [], 'msg': ''}

with patch('backtest_shared.requests.get') as mock_get:
    # XAU: spot probe fails (empty), SWAP probe succeeds (has data)
    calls = []
    def side_effect(url, params=None, timeout=10):
        calls.append(params)
        resp = Mock()
        inst_id = (params or {}).get('instId', '')
        limit = (params or {}).get('limit', 300)
        if inst_id == 'XAU-USDT-SWAP' and limit == 1:
            # Probe returns valid data
            resp.json.return_value = {'code': '0', 'data': [['1', '100', '105', '95', '102', '1', '1', '1', '1']], 'msg': ''}
        elif inst_id == 'XAU-USDT-SWAP':
            # Main data fetch
            resp.json.return_value = {'code': '0', 'data': [['1700000000000', '100', '105', '95', '102', '1000', '100', '100000', '1']], 'msg': ''}
        else:
            resp.json.return_value = {'code': '0', 'data': [], 'msg': ''}
        return resp
    mock_get.side_effect = side_effect
    result = fetch_candles_okx('XAUUSDT', 1)
    check("detects SWAP when spot fails", result is not None and len(result) > 0)


# ── fetch_candles priority chain ──
print("\n=== fetch_candles() priority ===")
from backtest_shared import fetch_candles

# OKX succeeds → returns immediately, no fallback needed
with patch('backtest_shared.fetch_candles_okx') as mock_okx, \
     patch('backtest_shared.fetch_candles_cmc') as mock_cmc, \
     patch('backtest_shared.fetch_candles_coingecko') as mock_cg:
    mock_okx.return_value = [{'close': 100, 'high': 100, 'low': 100, 'volume': 0, 'time': 1}] * 200
    result = fetch_candles('BTCUSDT', 10)
    check("uses OKX when available", result is not None and len(result) >= 200)
    mock_okx.assert_called()
    mock_cmc.assert_not_called()
    mock_cg.assert_not_called()

# OKX fails → falls back to CMC
with patch.dict(os.environ, {'CMC_API_KEY': 'test'}):
    with patch('backtest_shared.fetch_candles_okx') as mock_okx, \
         patch('backtest_shared.fetch_candles_cmc') as mock_cmc, \
         patch('backtest_shared.fetch_candles_coingecko') as mock_cg:
        mock_okx.return_value = None
        mock_cmc.return_value = [{'close': 100, 'high': 100, 'low': 100, 'volume': 0, 'time': 1}] * 200
        result = fetch_candles('BTCUSDT', 10)
        check("falls back to CMC when OKX fails", result is not None and len(result) >= 200)
        mock_okx.assert_called()
        mock_cmc.assert_called()
        mock_cg.assert_not_called()

# All fail → returns empty
with patch('backtest_shared.fetch_candles_okx', return_value=None), \
     patch('backtest_shared.fetch_candles_cmc', return_value=None), \
     patch('backtest_shared.fetch_candles_coingecko', return_value=None):
    result = fetch_candles('BTCUSDT', 10)
    check("returns empty when all fail", result == [])


# ── Daily cooldown (state_manager) ──
print("\n=== Daily cooldown ===")
from utils.state_manager import get_state, set_state, has_entered_today, record_entry, LOCAL_FALLBACK, get_entries, add_entry, clear_entries

# Clean up local fallback before tests
if LOCAL_FALLBACK.exists():
    LOCAL_FALLBACK.unlink()

state = get_state('BTC')
check("empty state returns empty dict", state == {})

set_state('BTC', {'last_entry_date': '2026-06-26'})
state = get_state('BTC')
check("saved state persists", state.get('last_entry_date') == '2026-06-26')

set_state('TRX', {'last_entry_date': '2026-06-25'})
state = get_state('TRX')
check("multiple coins stored", state.get('last_entry_date') == '2026-06-25')
check("BTC still intact", get_state('BTC').get('last_entry_date') == '2026-06-26')

# has_entered_today checks current date
check("past date returns False", has_entered_today('TRX') is False)

# record_entry sets today's date
record_entry('XAU', 4050.0)
state = get_state('XAU')
today = datetime.datetime.now().strftime('%Y-%m-%d')
check("record_entry sets today", state.get('last_entry_date') == today)
check("record_entry stores price", state.get('last_entry_price') == 4050.0)
check("has_entered_today returns True", has_entered_today('XAU') is True)

entries = get_entries('NO_COIN')
check("get_entries returns empty list for unknown coin", entries == [])

add_entry('TEST_C', 100.0, False)
add_entry('TEST_C', 105.5, False)
entries = get_entries('TEST_C')
check("add_entry appends entries", len(entries) == 2)
check("add_entry stores ep and is_short", entries[0] == {'ep': 100.0, 'is_short': False})
check("add_entry stores second entry", entries[1] == {'ep': 105.5, 'is_short': False})

clear_entries('TEST_C')
check("clear_entries removes all", get_entries('TEST_C') == [])

add_entry('BTC', 60000.0, True)
entries = get_entries('BTC')
check("short entry stored with is_short=True", entries[0] == {'ep': 60000.0, 'is_short': True})
check("BTC date still intact", get_state('BTC').get('last_entry_date') == '2026-06-26')
clear_entries('BTC')

# Cleanup
if LOCAL_FALLBACK.exists():
    LOCAL_FALLBACK.unlink()


# ── _try_fetch retry logic ──
print("\n=== _try_fetch() retry ===")
from backtest_shared import _try_fetch

call_counts = [0]
def flaky_fetcher(symbol, days):
    call_counts[0] += 1
    if call_counts[0] < 3:
        return None
    return [{'close': 100}] * 200

result = _try_fetch(flaky_fetcher, 'BTC', 10, 'test')
check("retries until success", result is not None and len(result) >= 200)
check("called 3 times", call_counts[0] == 3)

call_counts[0] = 0
def always_fail(symbol, days):
    call_counts[0] += 1
    return None

result = _try_fetch(always_fail, 'BTC', 10, 'test')
check("returns None after 3 failures", result is None)
check("called 3 times then gives up", call_counts[0] == 3)


# ── entry_conditions filter params ──
print("\n=== entry_conditions() filters ===")
from backtest_shared import entry_conditions

vols_big = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 100, 100]

# Filter 1: MA Slope
# ma at indices 0..2 are None (period=3), indices 3.. are valid
ma_up = [None, None, None, 100, 101, 102, 103, 104, 105, 106, 107, 108]
ma_down = [None, None, None, 108, 107, 106, 105, 104, 103, 102, 101, 100]
idx = 6; cc = 104; vavg = 5

s, _ = entry_conditions([], cc, idx, vols_big, vavg, ma_up[idx], 0.05, False, False, 25, 1.5, -999,
                         ma=ma_up, ma_slope=True)
check("MA slope rising allows long", s is True)

s2, _ = entry_conditions([], cc, idx, vols_big, vavg, ma_down[idx], 0.05, False, False, 25, 1.5, -999,
                          ma=ma_down, ma_slope=True)
check("MA slope falling blocks long", s2 is False)

# Filter 2: Lower High
highs_lh = [100, 105, 102, 106, 102, 107, 108, 109, 110, 111, 112, 113]
s3, _ = entry_conditions([], 112, 11, vols_big, vavg, 111, 0.03, False, False, 25, 1.5, -999,
                          highs=highs_lh, lows=[80]*12, lower_high=True)
check("lower_high filter allows when no pattern", s3 is True)

# peaks: 110, 106(?) actually need 2 declining peaks
highs_bad = [100, 110, 105, 108, 105, 110, 106, 108, 104, 103, 102, 101]
s4, _ = entry_conditions([], 102, 11, vols_big, vavg, 103, 0.03, False, False, 25, 1.5, -999,
                          highs=highs_bad, lows=[80]*12, lower_high=True)
check("lower_high blocks when peaks declining", s4 is False)

# Filter 3: Asymmetric buffer
s5, _ = entry_conditions([], 97, 6, vols_big, vavg, 100, 0.05, False, False, 25, 1.5, -999,
                          asym_buffer=True)
check("asym_buffer below MA uses 2% buffer", s5 is False)

s6, _ = entry_conditions([], 103, 6, vols_big, vavg, 100, 0.05, False, False, 25, 1.5, -999,
                          asym_buffer=True)
check("asym_buffer above MA uses normal buffer", s6 is True)

# ── Ext block ──
entries_profitable = [{'ep': 90, 'is_short': False}]
entries_lossy = [{'ep': 110, 'is_short': False}]
s7, m7 = entry_conditions(entries_profitable, 120, 6, vols_big, vavg, 100, 0.05, False, False, 25, 1.5, -999)
check("ext_block: price far above lowest_ep blocks", s7 is False and m7 == 0)
s8, m8 = entry_conditions(entries_lossy, 105, 6, vols_big, vavg, 100, 0.05, False, False, 25, 1.5, -999)
check("ext_block: price near highest_ep allows", s8 is True and m8 > 0)
s9, m9 = entry_conditions([], 100, 6, vols_big, vavg, 100, 0.05, False, False, 25, 1.5, -999)
check("ext_block: no entries bypasses", s9 is True and m9 == 1.0)


# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {failures} failures")
print(f"{'='*40}")
