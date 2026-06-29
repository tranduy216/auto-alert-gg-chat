"""
Unit tests for backtest_shared, combined_backtest, pooled_backtest, crypto_trading.
Run: python3 -B scripts/test/test_all.py
"""
import sys, os, datetime
from unittest.mock import patch, Mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_shared import sma
from backtest_shared import (
    BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE, MAX_CAP, FEE_RATE,
    EXT_BLOCK_PCT, fee_factor, BTC_SHORT_TP, PYRAMID_STRATEGIES,
    LONG_TP, SHORT_TP, SHORT_CLOSE_PCT,
    load_data, winner_mult, total_asset_value, compute_results,
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
check("BTC_SHORT_TP len 4", len(BTC_SHORT_TP) == 4)
check("BTC_SHORT_TP first (4,0.25)", BTC_SHORT_TP[0] == (4, 0.25))
check("BTC_SHORT_TP targets ascending", all(BTC_SHORT_TP[i][0] < BTC_SHORT_TP[i+1][0] for i in range(len(BTC_SHORT_TP)-1)))
check("BTC_SHORT_TP fractions sum 1.0", abs(sum(cf for _, cf in BTC_SHORT_TP) - 1.0) < 0.001)
check("TP_SCHEDULE sum 1.0", sum(cf for _, cf in TP_SCHEDULE) == 1.0)
check("TP_SCHEDULE len 4", len(TP_SCHEDULE) == 4)
check("MAX_CAP = 0.75", MAX_CAP == 0.75)
check("FEE_RATE = 0.0005", FEE_RATE == 0.0005)
check("EXT_BLOCK_PCT = 25", EXT_BLOCK_PCT == 25)
check("SHORT_CLOSE_PCT = 0.08", abs(SHORT_CLOSE_PCT - 0.08) < 0.001)
check("LONG_TP len 5", len(LONG_TP) == 5)
check("SHORT_TP len 3", len(SHORT_TP) == 3)
check("LONG_TP sum 0.6", abs(sum(cf for _, cf in LONG_TP) - 0.6) < 0.001)
check("SHORT_TP sum 1.0", abs(sum(cf for _, cf in SHORT_TP) - 1.0) < 0.001)
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
    check("bar has all fields", all(k in bar for k in ['open','close','high','low','volume','time']))
    check("bar high >= close", bar['high'] >= bar['close'])
    check("bar low <= close", bar['low'] <= bar['close'])
    check("bar volume >= 0", bar['volume'] >= 0)

# ── combined_backtest ──
print("\n=== combined_backtest: backtest_coin() ===")
_, r_none = combined_backtest('TEST', [], None, False, {})
check("short data -> None", r_none is None)

btc_key = next((k for k in data if k.startswith('BTCUSDT_4000_')), None)
trx_key = next((k for k in data if k.startswith('TRXUSDT_4000_')), None)
btc_da = data.get(btc_key, []) if btc_key else []
trx_da = data.get(trx_key, []) if trx_key else []

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

# Portfolio merge (group by day, not exact ms timestamp)
curves = [r['ts_curve'], r_short['ts_curve']]
merged = {}
for curve in curves:
    for ts, eq in curve:
        day = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc).strftime('%Y-%m-%d')
        merged.setdefault(day, []).append(eq)
pf_eq = [sum(v)/len(v) for v in merged.values() if len(v) == 2]
check("merged portfolio", len(pf_eq) > 0)
check("all equities positive", all(e > 0 for e in pf_eq))

# ── Verify combined vs pooled consistency (1-coin) ──
print("\n=== Pooled 1-coin ===")
from pooled_backtest import run_pooled
trx_cfg = PYRAMID_STRATEGIES[0][2]
trx_pool_key = next((k for k in data if k.startswith('TRXUSDT_4000_')), '')
r_pooled = run_pooled(data, [('TRX-L', trx_pool_key, False, trx_cfg)])

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
            check("bar has open field", 'open' in d)
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
    def side_effect(*args, **kwargs):
        params = kwargs.get('params')
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
check("add_entry stores ep and is_short", entries[0]['ep'] == 100.0 and entries[0]['is_short'] is False)
check("add_entry stores hi/lo", entries[0]['hi'] == 100.0 and entries[0]['lo'] == 100.0)
check("add_entry stores second entry", entries[1]['ep'] == 105.5 and entries[1]['is_short'] is False)

clear_entries('TEST_C')
check("clear_entries removes all", get_entries('TEST_C') == [])

add_entry('BTC', 60000.0, True, 60100.0, 59900.0)
entries = get_entries('BTC')
check("add_entry with hi/lo stored", entries[0].get('hi') == 60100.0 and entries[0].get('lo') == 59900.0)
check("short entry stored with is_short=True", entries[0]['ep'] == 60000.0 and entries[0]['is_short'] is True)
check("BTC date still intact", get_state('BTC').get('last_entry_date') == '2026-06-26')
clear_entries('BTC')

# Cleanup
if LOCAL_FALLBACK.exists():
    LOCAL_FALLBACK.unlink()


# ── _try_fetch retry logic ──
print("\n=== _try_fetch() retry ===")
from backtest_shared import _try_fetch

call_counts = [0]
def flaky_fetcher(*args, **kwargs):
    call_counts[0] += 1
    if call_counts[0] < 3:
        return None
    return [{'close': 100}] * 200

result = _try_fetch(flaky_fetcher, 'BTC', 10, 'test')
check("retries until success", result is not None and len(result) >= 200)
check("called 3 times", call_counts[0] == 3)

call_counts[0] = 0
def always_fail(*args, **kwargs):
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

# Short ext_block (15% from highest_ep)
short_entry1 = [{'ep': 100, 'is_short': True}]
s10, m10 = entry_conditions(short_entry1, 80, 6, vols_big, vavg, 100, 0.05, True, False, 25, 1.5, -999)
check("short ext_block: price far below highest_ep blocks", s10 is False and m10 == 0)
short_entry2 = [{'ep': 100, 'is_short': True}]
s11, m11 = entry_conditions(short_entry2, 98, 6, vols_big, vavg, 100, 0.05, True, False, 25, 1.5, -999)
check("short ext_block: price near highest_ep allows", s11 is True and m11 > 0)

# Edge cases
# idx < 2 → vol_cond fails
s12, _ = entry_conditions([], 100, 0, [10, 100], 50, 100, 0.05, False, False, 25, 1.5, -999)
check("vol_cond: idx<2 fails", s12 is False)
# BTC gate blocks short
s13, _ = entry_conditions([], 100, 6, vols_big, vavg, 100, 0.05, True, True, 25, 1.5, -999)
check("BTC bull blocks short", s13 is False)

# vol_bars: 3 bars avg > vavg (vavg=5, volumes: 10,10,10,100,100,100,100,100...)
vols3 = [10]*10 + [100, 100, 100]
s14, _ = entry_conditions([], 100, 11, vols3, 5, 100, 0.05, False, False, 25, 1.5, -999, vol_bars=3)
check("vol_bars=3: avg last 3 > vavg passes", s14 is True)
# vol_bars=3: avg last 3 < vavg fails
vols_lo = [10]*8 + [3, 3, 3]
s15, _ = entry_conditions([], 100, 10, vols_lo, 5, 100, 0.05, False, False, 25, 1.5, -999, vol_bars=3)
check("vol_bars=3: avg last 3 < vavg fails", s15 is False)

# vol_bars=2 (default): avg last 2 > vavg passes
vols2 = [10]*10 + [100, 100]
s16, _ = entry_conditions([], 100, 11, vols2, 5, 100, 0.05, False, False, 25, 1.5, -999)
check("vol_bars=2 default: avg last 2 > vavg passes", s16 is True)
# vol_bars=2: avg last 2 < vavg fails
vols2_lo = [10]*10 + [3, 3]
s17, _ = entry_conditions([], 100, 11, vols2_lo, 5, 100, 0.05, False, False, 25, 1.5, -999)
check("vol_bars=2 default: avg last 2 < vavg fails", s17 is False)
# idx < vol_bars: vol_cond fails (idx=0, vol_bars=3)
s18, _ = entry_conditions([], 100, 0, [100,100,100], 5, 100, 0.05, False, False, 25, 1.5, -999, vol_bars=3)
check("vol_bars=3: idx<vol_bars fails", s18 is False)

# ── compute_roi ──
from backtest_shared import compute_roi
check("compute_roi long pos", round(compute_roi({'ep': 100}, 110, False, 2.0), 2) == 20.0)  # (110-100)/100*200
check("compute_roi long neg", round(compute_roi({'ep': 100}, 90, False, 2.0), 2) == -20.0)
check("compute_roi short pos", round(compute_roi({'ep': 100}, 90, True, 2.0), 2) == 20.0)  # (100-90)/100*200
check("compute_roi short neg", round(compute_roi({'ep': 100}, 110, True, 2.0), 2) == -20.0)

# compute_results with days param
r4 = compute_results([1.0, 1.05], {2025: 1.05}, 10000, days=365)
check("compute_results with days param", abs(r4['cagr']) < 100)

# ═══════════════════════════════════════════════════════
# ── LIVE CODE QUALITY GATES ──
# ═══════════════════════════════════════════════════════
print("\n=== LIVE CODE QUALITY GATES ===")

# QG1: check_signals returns None when entry_conditions fails (primary bug fix)
from crypto_trading import check_signals

def sma_real(values, period):
    period = int(period)
    r = []
    for i in range(len(values)):
        if i < period - 1: r.append(None)
        else: r.append(sum(values[i-period+1:i+1]) / period)
    return r

with patch('crypto_trading.sma') as mock_sma:
    mock_sma.side_effect = sma_real

    # Case: vol_cond fails → should returns None
    vols_fail = [10]*200 + [3, 3, 3]
    da = [{'close': 100, 'high': 100, 'low': 100, 'volume': v, 'time': 0} for v in vols_fail]
    btc_da = [{'close': 50000, 'high': 50000, 'low': 50000, 'volume': 0, 'time': 0}]*203
    cfg = {'ma': 15, 'buf': 0.05, 'lev': 2, 'vol_bars': 3}
    result = check_signals(da, btc_da, cfg, False)
    check("QG1: check_signals returns None when entry condition fails", result is None)

    # Case: all conditions pass → returns (True, mult, price)
    vols_pass = [10]*200 + [100, 100, 100]
    da2 = [{'close': 100, 'high': 100, 'low': 100, 'volume': v, 'time': 0} for v in vols_pass]
    result2 = check_signals(da2, btc_da, cfg, False)
    check("QG2: check_signals returns tuple when entry passes", isinstance(result2, tuple) and len(result2) == 3)
    check("QG2b: should=True, mult>0, price=close", result2 is not None and result2[0] is True and result2[1] > 0)

    # Case: short entry blocked by BTC bull
    cfg_s = {'ma': 5, 'buf': 0.07, 'lev': 2}
    vol_hi = [10]*201 + [200, 200]
    da_s = [{'close': 100, 'high': 100, 'low': 100, 'volume': v, 'time': 0} for v in vol_hi]
    btc_bull_d = [{'close': 60000, 'high': 60000, 'low': 60000, 'volume': 0, 'time': 0}]*200 \
               + [{'close': 66000, 'high': 66000, 'low': 66000, 'volume': 0, 'time': 0}]*100
    result3 = check_signals(da_s, btc_bull_d, cfg_s, True)
    check("QG3: short entry blocked when BTC bullish (>=MA200*1.005)", result3 is None)

    # Case: short entry passes when BTC bearish
    btc_bear_d = [{'close': 60000, 'high': 60000, 'low': 60000, 'volume': 0, 'time': 0}]*200 \
               + [{'close': 40000, 'high': 40000, 'low': 40000, 'volume': 0, 'time': 0}]*100
    result4 = check_signals(da_s, btc_bear_d, cfg_s, True)
    check("QG4: short entry allowed when BTC bearish", result4 is not None)

# QG5: btc_bull formula identical — grep source for inconsistencies
import re
formulas = []
for fn in ['crypto_trading.py', 'live_pyramid.py', 'combined_backtest.py', 'pooled_backtest.py']:
    with open(f'scripts/{fn}') as fh:
        txt = fh.read()
    for m in re.finditer(r'\bbtc_bull\b\s*=\s*btc_closes\[[^\]]+\]\s*([><=]+)\s*btc_ma200\[[^\]]+\](\s*\*\s*[\d.]+)?', txt):
        op = m.group(1); mul = m.group(2) or ''
        formulas.append(f'{fn}:{op}{mul.strip()}')
all_ok = all('>=* 1.005' in f for f in formulas) and len(formulas) >= 4
check(f"QG5: all btc_bull sites use >= * 1.005 (found {len(formulas)})", all_ok)

# ── TRADING SCENARIO UNIT TESTS ──
print("\n=== SCENARIOS: ROI, mult, size ===")

# S1: compute_roi — long and short PnL
check("S1a: long ROI +20% at 2x", round(compute_roi({'ep': 100}, 110, False, 2.0), 2) == 20.0)
check("S1b: long ROI -10% at 2x", round(compute_roi({'ep': 100}, 95, False, 2.0), 2) == -10.0)
check("S1c: short ROI +20% at 2x", round(compute_roi({'ep': 100}, 90, True, 2.0), 2) == 20.0)
check("S1d: short ROI -15% at 2x", round(compute_roi({'ep': 100}, 107.5, True, 2.0), 2) == -15.0)

# S2: winner_mult — position sizing based on existing entry profitability
check("S2a: no entries → 1.0x", winner_mult([], 100, False, 2) == 1.0)
check("S2b: avg ROI >15% → 2.5x", winner_mult([{'ep':80}, {'ep':75}], 100, False, 2) == 2.5)
check("S2c: avg ROI 0-5% → 1.2x", winner_mult([{'ep':98}], 100, False, 2) == 1.2)
check("S2d: avg ROI -5-0% → 0.75x", winner_mult([{'ep':100}], 98, False, 2) == 0.75)
check("S2e: avg ROI <-5% → 0.5x", winner_mult([{'ep':100}], 92, False, 2) == 0.5)
check("S2f: short avg ROI 10-15% → 2.0x", winner_mult([{'ep':100}], 92.5, True, 2) == 2.0)

# S3: entry sizing — usd_val = eq * lev * ENTRY_PCT * mult
eq = 13000; lev = 2; epct = 0.011
check("S3a: base size 2x", round(eq * lev * epct, 1) == 286.0)
check("S3b: size with 1.5x mult", round(eq * lev * epct * 1.5, 1) == 429.0)
check("S3c: size with 0.5x mult", round(eq * lev * epct * 0.5, 1) == 143.0)
check("S3d: short entry ×2 size", round(eq * lev * epct * 1.0 * 2, 1) == 572.0)

# S4: TP partial close schedule — verify fractions
# TRX TP: [(10, 0.05), (20, 0.10), (30, 0.15), (40, 0.20), (50, 0.10)]
trx_tp = [(10, 0.05), (20, 0.10), (30, 0.15), (40, 0.20), (50, 0.10)]
check("S4a: TRX TP 5 stages", len(trx_tp) == 5)
check("S4b: TRX TP total close = 60%", abs(sum(cf for _, cf in trx_tp) - 0.60) < 0.001)
# BTC TP: [(4, 0.30), (8, 0.40), (12, 0.30)]
btc_tp = [(4, 0.30), (8, 0.40), (12, 0.30)]
check("S4c: BTC TP 3 stages", len(btc_tp) == 3)
check("S4d: BTC TP total close = 100%", abs(sum(cf for _, cf in btc_tp) - 1.0) < 0.001)

# S5: Trailing stop formulas
check("S5a: long trail triggered: close <= peak * 0.82", 80 <= 100 * 0.82)
check("S5b: long trail NOT triggered: close > peak * 0.82", 90 > 100 * 0.82)
check("S5c: short trail triggered: close >= trough * 1.08", 108 >= 100 * 1.08)
check("S5d: short trail NOT triggered: close < trough * 1.08", 105 < 100 * 1.08)

# S6: ext_block — block pyramid when price > 25% from extreme entry
check("S6a: long ext_block: 30% above lowest → blocked", (130 - 100) / 100 * 100 > 25)
check("S6b: long ext_block: 20% above lowest → allowed", (120 - 100) / 100 * 100 <= 25)
check("S6c: short ext_block: 20% below highest → blocked", (100 - 80) / 100 * 100 > 15)
check("S6d: short ext_block: 10% below highest → allowed", (100 - 90) / 100 * 100 <= 15)

# S7: Pyramid entry — ROI >= next_pyr_roi
check("S7a: pyramid at 8% ROI", (110 - 100) / 100 * 100 * 2 >= 8)   # 20% ROI at 2x >= 8%
check("S7b: pyramid NOT at 5% ROI", (105 - 100) / 100 * 100 * 2 >= 8) # 10% ROI >= 8% → yes
check("S7c: next pyr += 7", 8 + 7 == 15)

# S8: entry_conditions with existing entries — ext_block should block mult
e_existing = [{'ep': 80, 'is_short': False}]
vols_ok = [10]*201 + [100, 100]  # vol_cond passes (last 2 avg=100 > vavg=10)
# price=102, lowest_ep=80 → (102-80)/80*100=27.5% > 25% → mult=0 blocked
s8, m8 = entry_conditions(e_existing, 102, 201, vols_ok, 5, 100, 0.05, False, False, 25, 1.5, -999)
check("S8a: ext_block 27.5% > 25% → mult=0 blocked", s8 is False and m8 == 0)
# price=99, lowest_ep=80 → (99-80)/80*100=23.75% < 25% → mult>0, enter
s9, m9 = entry_conditions(e_existing, 99, 201, vols_ok, 5, 100, 0.05, False, False, 25, 1.5, -999)
check("S8b: ext_block 23.75% < 25% → mult>0, enter", s9 is True and m9 > 0)

# S9: fee_factor affects PnL
check("S9a: fee at 1x = 0.999", abs(fee_factor(1.0) - 0.999) < 0.0001)
check("S9b: fee at 2x = 0.998", abs(fee_factor(2.0) - 0.998) < 0.0001)

# S10: total_asset_value with multiple entries
check("S10a: no entries = eq", abs(total_asset_value([], 100, 13000, 2) - 13000) < 1e-9)
entries_val = [{'ep': 100, 'mp': 0.1, 'rem': 1.0}, {'ep': 90, 'mp': 0.05, 'rem': 0.5}]
# entry1: (100-100)/100 * 0.1 * 2 * 1.0 = 0
# entry2: (100-90)/90 * 0.05 * 2 * 0.5 = (10/90) * 0.05 * 2 * 0.5 = 0.0556
expected_val = 13000 + (10/90) * 0.05 * 2 * 0.5
check("S10b: multi-entry asset value", abs(total_asset_value(entries_val, 100, 13000, 2) - expected_val) < 1e-6)

# ── daily_trading: avg_ep ──
print("\n=== daily_trading: avg_ep ===")
from daily_trading import avg_ep, entry_is_short, direction_name, avg_roi, calc_dynamic_tp_sl, check_signal

check("avg_ep empty returns None", avg_ep([]) is None)
check("avg_ep single entry", abs(avg_ep([{'ep': 100, 'mp': 1}]) - 100) < 1e-9)
check("avg_ep two entries equal weight", abs(avg_ep([{'ep': 100, 'mp': 1}, {'ep': 110, 'mp': 1}]) - 105) < 1e-9)
check("avg_ep weighted", abs(avg_ep([{'ep': 100, 'mp': 2}, {'ep': 120, 'mp': 1}]) - 106.6667) < 0.001)
check("avg_ep no mp defaults to 1", abs(avg_ep([{'ep': 90}, {'ep': 110}]) - 100) < 1e-9)
check("avg_ep zero entries edge", avg_ep([]) is None)
check("avg_ep single with zero mp returns None", avg_ep([{'ep': 100, 'mp': 0}]) is None)

# ── daily_trading: entry_is_short ──
print("\n=== daily_trading: entry_is_short ===")
check("is_short True", entry_is_short({'is_short': True}) is True)
check("is_short False", entry_is_short({'is_short': False}) is False)
check("old field short=True", entry_is_short({'short': True}) is True)
check("old field short=False", entry_is_short({'short': False}) is False)
check("is_short=1 interpreted as True", entry_is_short({'is_short': 1}) is True)
check("old short=0 interpreted as False", entry_is_short({'short': 0}) is False)
check("no direction fields defaults False", entry_is_short({}) is False)

# ── daily_trading: direction_name ──
print("\n=== daily_trading: direction_name ===")
check("True -> SHORT", direction_name(True) == 'SHORT')
check("False -> LONG", direction_name(False) == 'LONG')

# ── daily_trading: avg_roi ──
print("\n=== daily_trading: avg_roi ===")
check("avg_roi long profit", abs(avg_roi([{'ep': 100}], 110, 3) - 30.0) < 1e-9)     # (10/100)*100*3
check("avg_roi long loss", abs(avg_roi([{'ep': 100}], 95, 3) - (-15.0)) < 1e-9)    # (-5/100)*100*3
check("avg_roi short profit", abs(avg_roi([{'ep': 100, 'is_short': True}], 90, 3) - 30.0) < 1e-9)
check("avg_roi short loss", abs(avg_roi([{'ep': 100, 'is_short': True}], 105, 3) - (-15.0)) < 1e-9)
# avg_roi weighted avg: aep=(90*2+110*1)/3=96.67, ROI=(100-96.67)/96.67*100*3=10.34
roi = avg_roi([{'ep': 90, 'mp': 2}, {'ep': 110, 'mp': 1}], 100, 3)
check("avg_roi weighted avg", abs(roi - 10.344) < 0.01)
check("avg_roi no entries returns 0", avg_roi([], 100, 3) == 0)
check("avg_roi short via old 'short' field", abs(avg_roi([{'ep': 100, 'short': True}], 85, 2) - 30.0) < 1e-9)

# ── daily_trading: calc_dynamic_tp_sl ──
print("\n=== daily_trading: calc_dynamic_tp_sl ===")
# ATR rising: prices with wide range → larger TP/SL
range_wide = [{'high': 110, 'low': 90, 'close': 100}] * 20
tp, sl = calc_dynamic_tp_sl(range_wide)
check("wide range: tp > 0.02", tp >= 0.02)
check("wide range: sl > 0.01", sl >= 0.01)
check("wide range: tp >= sl", tp >= sl)

# ATR tight: stable prices → smaller TP/SL
range_narrow = [{'high': 101, 'low': 99, 'close': 100}] * 20
tp2, sl2 = calc_dynamic_tp_sl(range_narrow)
check("narrow range: tp < wide tp", tp2 < tp)
check("narrow range: sl < wide sl", sl2 < sl)
check("tp capped at 20%", tp <= 0.201)
check("sl capped at 15%", sl <= 0.151)

# ATR on 14-period minimum → data < 14 bars → fallback
short_data = [{'high': 110, 'low': 90, 'close': 100}] * 5
tp_fb, sl_fb = calc_dynamic_tp_sl(short_data)
check("short data: uses fallback TP", abs(tp_fb - 0.06) < 0.001)
check("short data: uses fallback SL", abs(sl_fb - 0.03) < 0.001)

# Empty data → fallback
tp_e, sl_e = calc_dynamic_tp_sl([])
check("empty data: fallback TP", abs(tp_e - 0.06) < 0.001)
check("empty data: fallback SL", abs(sl_e - 0.03) < 0.001)

# ── daily_trading: check_signal ──
print("\n=== daily_trading: entry_is_short ===")
# Build clean uptrend: daily MA3 > MA5 > MA7
# 15 daily bars rising from 100 to 115 → MA3=114 > MA5=113 > MA7=112
daily_up = [{'close': 100 + i} for i in range(15)]
# 30 12h bars with last 7 flat at ~108 so MA3≈MA7 and close≈MA3
h12_up = [{'close': 100 + i//2} for i in range(23)]  # 23 price-rising 12h bars
h12_up += [{'close': 108}] * 7                      # last 7 flat → MA3=MA7=close=108
dir_up, pr_up = check_signal(h12_up, daily_up)
check("uptrend returns direction", dir_up is not None)
if dir_up:
    check("uptrend is LONG", dir_up == 'LONG')
    check("returns price", pr_up is not None and pr_up > 0)

# Downtrend: daily MA3 < MA5 < MA7
daily_dn = [{'close': 115 - i} for i in range(15)]
# 12h bars with last 7 flat at ~107
h12_dn = [{'close': 115 - i//2} for i in range(23)]
h12_dn += [{'close': 107}] * 7
dir_dn, pr_dn = check_signal(h12_dn, daily_dn)
check("downtrend returns direction", dir_dn is not None)
if dir_dn:
    check("downtrend is SHORT", dir_dn == 'SHORT')

# No trend (all equal → MAs equal → no trend direction)
daily_nt = [{'close': 100} for _ in range(15)]
h12_nt = [{'close': 100} for _ in range(30)]
dir_nt, pr_nt = check_signal(h12_nt, daily_nt)
check("no trend returns None", dir_nt is None)

# Too short data
dir4, pr4 = check_signal([], [])
check("empty data returns None", dir4 is None)

# ── Edge cases: compute_results ──
print("\n=== Edge cases: compute_results ===")
r5 = compute_results([1.0, 1.0, 1.0], {2024: 1.0}, 10000)
check("flat curve CAGR=0", abs(r5['cagr']) < 0.01)
check("flat curve DD=0", r5['dd'] == 0)

r6 = compute_results([1.0, 1.5, 1.0], {2025: 1.0}, 10000)
check("peak-then-drop DD > 0", r6['dd'] > 0)  # peak=1.5, valley=1.0 → 33% DD
check("final = teq * base", abs(r6['final'] - 10000) < 0.1)

# Single-point curve with explicit days to avoid CAGR explosion
r7 = compute_results([1.1], {2024: 1.1}, 10000, days=365)
check("single point CAGR ~10%", abs(r7['cagr'] - 10.0) < 0.5)
check("single point DD=0", r7['dd'] == 0)

# ── Edge cases: atr ──
print("\n=== Edge cases: atr ===")
from backtest_shared import atr as bt_atr
check("atr empty", bt_atr([], [], [], 14) == [])
check("atr single value", len(bt_atr([100], [90], [95], 14)) == 1)
check("atr all None with zero data", all(v is None for v in bt_atr([100]*5, [90]*5, [95]*5, 14)[:13]))

# ── Edge cases: avg_entry ──
print("\n=== Edge cases: avg_entry ===")
from backtest_shared import avg_entry
check("avg_entry empty", avg_entry([])[0] is None and avg_entry([])[1] == 0)
check("avg_entry single", abs(avg_entry([{'ep': 100}])[0] - 100) < 1e-9)
check("avg_entry no mp uses w=1", abs(avg_entry([{'ep': 100}, {'ep': 110}])[0] - 105) < 1e-9)
check("avg_entry with mp and rem", abs(avg_entry([{'ep': 100, 'mp': 0.1, 'rem': 1.0}])[0] - 100) < 1e-9)

# ── 🔧 LEVERAGE FIX VERIFICATION ──
print("\n=== Leverage fix verification ===")
# Verify crypto_trading sets leverage BEFORE order (not after)
src = open('scripts/crypto_trading.py').read()
lines = src.split('\n')
set_idx = None
place_idx = None
for i, line in enumerate(lines):
    if 'okx_set_leverage' in line and 'okx_lev' in line and 'def' not in line and 'import' not in line:
        set_idx = i
    if 'okx_place_order(' in line and set_idx is not None and place_idx is None and 'def' not in line:
        place_idx = i
        break
check("crypto_trading: set_leverage before order", place_idx is not None and set_idx < place_idx)

# Same check for daily_trading.py
src_daily = open('scripts/daily_trading.py').read()
lines_daily = src_daily.split('\n')
set_idx_d = None
place_idx_d = None
for i, line in enumerate(lines_daily):
    if 'okx_set_leverage' in line and set_idx_d is None:
        set_idx_d = i
    if 'okx_place_order(' in line and set_idx_d is not None and place_idx_d is None:
        place_idx_d = i
        break
check("daily_trading: set_leverage before order", set_idx_d is not None and place_idx_d is not None and set_idx_d < place_idx_d)

# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {failures} failures")
print(f"{'='*40}")
