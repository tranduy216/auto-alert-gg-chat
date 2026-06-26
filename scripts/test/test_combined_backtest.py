"""
Unit tests for combined_backtest (via shared module).
Run: python3 -B scripts/test/test_combined_backtest.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_shared import sma
from backtest_shared import (
    winner_mult, load_data, TP_SCHEDULE,
)


# ── sma() ──

def test_sma_basic():
    r = sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert r == [None, None, 2.0, 3.0, 4.0]


def test_sma_period_larger_than_data():
    assert all(v is None for v in sma([1, 2, 3], 5))


def test_sma_single_value():
    assert sma([5.0], 1) == [5.0]


def test_sma_empty():
    assert sma([], 5) == []


# ── winner_mult() ──

def test_winner_mult_no_entries():
    assert winner_mult([], 100, False, 1.5) == 1.0


def test_winner_mult_positive_roi():
    entries = [{'ep': 90}, {'ep': 80}]
    assert winner_mult(entries, 100, False, 1.5) == 2.5


def test_winner_mult_negative_roi():
    assert winner_mult([{'ep': 100}], 95, False, 1.5) == 0.5


def test_winner_mult_moderate_loss():
    assert winner_mult([{'ep': 100}], 97, False, 1.5) == 0.75


def test_winner_mult_deep_negative():
    assert winner_mult([{'ep': 100}], 85, False, 1.5) == 0.5


def test_winner_mult_short():
    assert winner_mult([{'ep': 100}], 90, True, 1.5) == 2.0


def test_winner_mult_leverage_effect():
    assert winner_mult([{'ep': 80}], 84, False, 2.0) == 1.5


# ── TP_SCHEDULE invariant ──

def test_tp_schedule_sums_to_one():
    assert sum(cf for _, cf in TP_SCHEDULE) == 1.0


# ── load_data() ──

def test_load_data_returns_dict():
    data = load_data()
    assert isinstance(data, dict)
    assert len(data) > 0
    for k, v in data.items():
        assert isinstance(v, list)
        if v:
            entry = v[0]
            assert 'close' in entry and 'high' in entry
            assert 'low' in entry and 'volume' in entry and 'time' in entry
