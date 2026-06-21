"""
Unit tests for crypto_trading.py
Coverage: Position sizing, indicators, cooldown, coin profiles
"""
import pytest
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from crypto_trading import (
    get_allocation_multiplier,
    get_position_size,
    get_snowball_size,
    _fib_cooldown_bars,
    compute_adx,
    compute_sideway_score,
    sma,
    compute_atr,
    compute_rsi,
    _coin_lev,
    _coin_sl_roi,
    _coin_trail,
    _entry_margin,
    _coin_cap,
    get_coin_profile
)


class TestPositionSizing:
    """Test position sizing functions"""
    
    def test_get_allocation_multiplier_high_score_bull(self):
        """High score in bull regime should return max multiplier"""
        mult = get_allocation_multiplier(80, bull_regime=True)
        assert mult == 1.0
    
    def test_get_allocation_multiplier_low_score_bull(self):
        """Low score in bull regime should return reduced multiplier"""
        mult = get_allocation_multiplier(60, bull_regime=True)
        assert mult == 0.5
    
    def test_get_allocation_multiplier_high_score_bear(self):
        """High score in bear regime should return reduced multiplier"""
        mult = get_allocation_multiplier(80, bull_regime=False)
        assert mult == 0.7
    
    def test_get_allocation_multiplier_low_score_bear(self):
        """Low score in bear regime should return min multiplier"""
        mult = get_allocation_multiplier(60, bull_regime=False)
        assert mult == 0.35
    
    def test_get_position_size_strong_trend(self):
        """Strong trend should return larger position"""
        size = get_position_size(3, coin="BTC")
        assert size > 0
    
    def test_get_position_size_weak_trend(self):
        """Weak trend should return smaller position"""
        size_strong = get_position_size(3, coin="BTC")
        size_weak = get_position_size(1, coin="BTC")
        assert size_weak < size_strong
    
    def test_get_snowball_size_first_entry(self):
        """First entry should return base size"""
        size = get_snowball_size(1, entry_score=80)
        assert size > 0
    
    def test_get_snowball_size_second_entry(self):
        """Second entry should return reduced size"""
        size1 = get_snowball_size(1, entry_score=80)
        size2 = get_snowball_size(2, entry_score=80)
        assert size2 < size1


class TestCooldown:
    """Test cooldown functions"""
    
    def test_fib_cooldown_no_losses(self):
        """No losses should return 0 cooldown"""
        bars = _fib_cooldown_bars(0, shift=0)
        assert bars == 0
    
    def test_fib_cooldown_one_loss(self):
        """One loss should return 0 cooldown"""
        bars = _fib_cooldown_bars(1, shift=0)
        assert bars == 0
    
    def test_fib_cooldown_two_losses(self):
        """Two losses should return 3 bars (Fibonacci)"""
        bars = _fib_cooldown_bars(2, shift=0)
        assert bars == 3
    
    def test_fib_cooldown_three_losses(self):
        """Three losses should return 5 bars (Fibonacci)"""
        bars = _fib_cooldown_bars(3, shift=0)
        assert bars == 5
    
    def test_fib_cooldown_four_losses(self):
        """Four losses should return 8 bars (Fibonacci)"""
        bars = _fib_cooldown_bars(4, shift=0)
        assert bars == 8
    
    def test_fib_cooldown_with_shift(self):
        """Shift should increase cooldown"""
        bars_no_shift = _fib_cooldown_bars(3, shift=0)
        bars_shift = _fib_cooldown_bars(3, shift=1)
        assert bars_shift > bars_no_shift


class TestIndicators:
    """Test technical indicator functions"""
    
    def test_sma_basic(self, sample_candles):
        """SMA should calculate correctly"""
        closes = [c['close'] for c in sample_candles]
        sma_values = sma(closes, period=10)
        assert len(sma_values) == len(closes)
        # First 9 values should be None
        assert all(v is None for v in sma_values[:9])
        # 10th value should be average of first 10 closes
        expected = sum(closes[:10]) / 10
        assert abs(sma_values[9] - expected) < 0.01
    
    def test_compute_atr(self, sample_candles):
        """ATR should calculate correctly"""
        atr = compute_atr(sample_candles, period=14)
        assert atr > 0
        # ATR should be reasonable (between 0 and 50 for sample data)
        assert 0 < atr < 50
    
    def test_compute_rsi_bullish(self):
        """RSI should be high for bullish trend"""
        # Bullish trend: consistent gains
        closes = [100 + i*2 for i in range(50)]
        rsi = compute_rsi(closes, period=14)
        assert rsi > 50
    
    def test_compute_rsi_bearish(self):
        """RSI should be low for bearish trend"""
        # Bearish trend: consistent losses
        closes = [100 - i*2 for i in range(50)]
        rsi = compute_rsi(closes, period=14)
        assert rsi < 50
    
    def test_compute_adx_trending(self, sample_candles):
        """ADX should be high for trending market"""
        adx = compute_adx(sample_candles, period=14)
        # Trending market should have ADX > 25
        assert adx > 20
    
    def test_compute_sideway_score_trending(self, sample_candles):
        """Sideway score should be low for trending market"""
        score = compute_sideway_score(sample_candles, sf=1.0)
        # Trending market should have low sideway score (0-2)
        assert 0 <= score <= 4


class TestCoinProfiles:
    """Test coin profile functions"""
    
    def test_coin_lev_btc(self):
        """BTC should have correct leverage"""
        lev = _coin_lev("BTC")
        assert lev > 0
        assert lev <= 10  # Reasonable leverage
    
    def test_coin_sl_roi_btc(self):
        """BTC should have reasonable stop loss"""
        sl = _coin_sl_roi("BTC")
        assert 0 < sl < 1  # Between 0 and 100%
    
    def test_coin_trail_btc(self):
        """BTC should have reasonable trailing stop"""
        trail = _coin_trail("BTC")
        assert 0 < trail < 1
    
    def test_entry_margin_strong(self):
        """Strong entry should have larger margin"""
        margin_strong = _entry_margin("BTC", strong=True)
        margin_weak = _entry_margin("BTC", strong=False)
        assert margin_strong > margin_weak
    
    def test_coin_cap_btc(self):
        """BTC should have reasonable cap"""
        cap = _coin_cap("BTC")
        assert cap > 0
    
    def test_get_coin_profile_btc(self):
        """Should return valid profile for BTC"""
        profile = get_coin_profile("BTC")
        assert isinstance(profile, dict)
        assert 'leverage' in profile
        assert 'sl_roi' in profile
        assert 'trail' in profile


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_sma_empty_list(self):
        """SMA with empty list should handle gracefully"""
        result = sma([], period=10)
        assert result == []
    
    def test_sma_short_list(self):
        """SMA with short list should return None for first values"""
        result = sma([1, 2, 3], period=10)
        assert len(result) == 3
        assert all(v is None for v in result)
    
    def test_compute_atr_insufficient_data(self):
        """ATR with insufficient data should return 0"""
        candles = [
            {'timestamp': i, 'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 1000}
            for i in range(5)
        ]
        atr = compute_atr(candles, period=14)
        assert atr == 0
    
    def test_compute_rsi_insufficient_data(self):
        """RSI with insufficient data should return 50"""
        closes = [100, 101, 102]
        rsi = compute_rsi(closes, period=14)
        assert rsi == 50  # Default value
    
    def test_compute_adx_insufficient_data(self):
        """ADX with insufficient data should return 25"""
        candles = [
            {'timestamp': i, 'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 1000}
            for i in range(5)
        ]
        adx = compute_adx(candles, period=14)
        assert adx == 25  # Default value
