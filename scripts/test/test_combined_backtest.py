"""
Unit tests for combined_backtest.py
Run: python3 -m pytest scripts/test/test_combined_backtest.py -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from combined_backtest import (
    sma, winner_mult, load_data, backtest_coin,
    TP_SCHEDULE, ENTRY_PCT, PYRAMID_ROI_DEFAULT
)


# ── sma() ──

def test_sma_basic():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    r = sma(values, 3)
    assert r[0] is None
    assert r[1] is None
    assert r[2] == 2.0         # (1+2+3)/3
    assert r[3] == 3.0         # (2+3+4)/3
    assert r[4] == 4.0         # (3+4+5)/3


def test_sma_period_larger_than_data():
    r = sma([1, 2, 3], 5)
    assert all(v is None for v in r)


def test_sma_single_value():
    r = sma([5.0], 1)
    assert r == [5.0]


def test_sma_empty():
    r = sma([], 5)
    assert r == []


# ── winner_mult() ──

def test_winner_mult_no_entries():
    assert winner_mult([], 100, False, 1.5) == 1.0


def test_winner_mult_positive_roi():
    entries = [{'ep': 90}, {'ep': 80}]
    # cc = 100: ROI = (100-90)/90*100*1.5=16.67%, (100-80)/80*100*1.5=37.5%
    # avg = (16.67+37.5)/2 = 27.08 → >15 → 2.5
    assert winner_mult(entries, 100, False, 1.5) == 2.5


def test_winner_mult_negative_roi():
    entries = [{'ep': 100}]
    # cc = 95: ROI = (95-100)/100*100*1.5 = -7.5% → < -5 → 0.5
    assert winner_mult(entries, 95, False, 1.5) == 0.5


def test_winner_mult_moderate_loss():
    entries = [{'ep': 100}]
    # cc = 97: ROI = (97-100)/100*100*1.5 = -4.5% → > -5 → 0.75
    assert winner_mult(entries, 97, False, 1.5) == 0.75


def test_winner_mult_deep_negative():
    entries = [{'ep': 100}]
    # cc = 85: ROI = (85-100)/100*100*1.5 = -22.5% → < -5 → 0.5
    assert winner_mult(entries, 85, False, 1.5) == 0.5


def test_winner_mult_short():
    entries = [{'ep': 100}]
    # cc = 90: ROI = (100-90)/100*100*1.5 = 15% → >10 → 2.0
    assert winner_mult(entries, 90, True, 1.5) == 2.0


def test_winner_mult_leverage_effect():
    entries = [{'ep': 80}]
    # cc = 84: ROI = (84-80)/80*100*2.0 = 10% → >5 → 1.5
    assert winner_mult(entries, 84, False, 2.0) == 1.5


# ── load_data() ──

def test_load_data_returns_dict():
    data = load_data()
    assert isinstance(data, dict)
    assert len(data) > 0
    for k, v in data.items():
        assert isinstance(v, list)
        if v:
            entry = v[0]
            assert 'close' in entry
            assert 'high' in entry
            assert 'low' in entry
            assert 'volume' in entry
            assert 'time' in entry


def test_load_data_daily_aggregation():
    """Each day should be 2x 12h candles aggregated into 1 daily"""
    data = load_data()
    for symbol, daily in data.items():
        if len(daily) > 1:
            # Verify high >= close >= low for each bar
            for bar in daily:
                assert bar['low'] <= bar['close'] <= bar['high']


# ── backtest_coin() basic properties ──

def test_backtest_coin_returns_none_for_short_data():
    _, result = backtest_coin('TEST', [], None, False, 1.0, None, None)
    assert result is None


def test_backtest_coin_returns_expected_keys():
    data = load_data()
    trx_da = data.get('TRXUSDT_4000_1609434000000', [])
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    _, result = backtest_coin('TRX', trx_da, btc_da, False, 1.0, None, None)
    assert result is not None
    for key in ('cagr', 'dd', 'final', 'yearly', 'ts_curve'):
        assert key in result


def test_backtest_coin_with_cfg_overrides():
    data = load_data()
    trx_da = data.get('TRXUSDT_4000_1609434000000', [])
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    cfg = {'ma': 20, 'buf': 0.03, 'pyr': 5, 'lev': 1.5}
    _, result = backtest_coin('TRX', trx_da, btc_da, False, 1.0, None, cfg)
    assert result is not None
    assert -100 < result['cagr'] < 500
    assert 0 <= result['dd'] <= 100


def test_backtest_coin_short_mode():
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    cfg = {'ma': 20, 'buf': 0.03, 'pyr': 5, 'lev': 1.5}
    _, result = backtest_coin('BTC', btc_da, btc_da, True, 0.30, None, cfg)
    assert result is not None
    assert 'yearly' in result


def test_backtest_coin_selected_years():
    data = load_data()
    trx_da = data.get('TRXUSDT_4000_1609434000000', [])
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    _, result = backtest_coin('TRX', trx_da, btc_da, False, 1.0, {2021, 2022}, None)
    assert result is not None
    yearly = result['yearly']
    # selected_years applies entry restrictions, but all years are recorded in equity
    assert 2021 in yearly
    assert 2022 in yearly


# ── TP_SCHEDULE invariant ──

def test_tp_schedule_sums_to_one():
    total = sum(cf for _, cf in TP_SCHEDULE)
    assert total == 1.0


# ── Portfolio merging sanity ──

def test_portfolio_merge_curve_exists():
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])

    # Run backtest for 2 coins
    strategies = [
        ('TRX-L', 'TRX', False, 1.0, {}),
        ('BTC-S', 'BTC', True, 0.30, {}),
    ]
    results = {}
    for label, coin, is_short, max_cap, cfg in strategies:
        sym = f'{coin}USDT_4000_1609434000000'
        da = data.get(sym, [])
        res = backtest_coin(coin, da, btc_da, is_short, max_cap, None, cfg)
        if res[1]:
            results[label] = res[1]

    assert len(results) >= 1
    for label, r in results.items():
        ts_curve = r['ts_curve']
        assert len(ts_curve) > 100  # at least some data
        for ts, eq in ts_curve:
            assert ts > 0
            assert eq > 0  # equity always positive
