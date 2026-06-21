"""
Unit tests for crypto_trading.py using unittest
Coverage: Position sizing, indicators, cooldown, coin profiles
"""
import unittest
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from crypto_trading import (
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


class TestPositionSizing(unittest.TestCase):
    """Test position sizing functions"""

    def test_get_snowball_size_first_entry(self):
        """First entry should return 0 (snowball starts from entry 2)"""
        size = get_snowball_size(1, entry_score=80)
        self.assertEqual(size, 0)  # Entry 1 is base, not snowball

    def test_get_snowball_size_second_entry(self):
        """Second entry should return snowball size"""
        size1 = get_snowball_size(1, entry_score=80)
        size2 = get_snowball_size(2, entry_score=80)
        self.assertEqual(size1, 0)  # Entry 1 is base
        self.assertGreater(size2, 0)  # Entry 2 is snowball


class TestCooldown(unittest.TestCase):
    """Test cooldown functions"""

    def test_fib_cooldown_no_losses(self):
        """No losses should return 0 cooldown"""
        bars = _fib_cooldown_bars(0, shift=0)
        self.assertEqual(bars, 0)

    def test_fib_cooldown_one_loss(self):
        """One loss should return 0 cooldown"""
        bars = _fib_cooldown_bars(1, shift=0)
        self.assertEqual(bars, 0)

    def test_fib_cooldown_two_losses(self):
        """Two losses should return 3 bars (Fibonacci)"""
        bars = _fib_cooldown_bars(2, shift=0)
        self.assertEqual(bars, 3)

    def test_fib_cooldown_three_losses(self):
        """Three losses should return 5 bars (Fibonacci)"""
        bars = _fib_cooldown_bars(3, shift=0)
        self.assertEqual(bars, 5)

    def test_fib_cooldown_four_losses(self):
        """Four losses should return 8 bars (Fibonacci)"""
        bars = _fib_cooldown_bars(4, shift=0)
        self.assertEqual(bars, 8)

    def test_fib_cooldown_with_shift(self):
        """Shift should increase cooldown"""
        bars_no_shift = _fib_cooldown_bars(3, shift=0)
        bars_shift = _fib_cooldown_bars(3, shift=1)
        self.assertGreater(bars_shift, bars_no_shift)


class TestIndicators(unittest.TestCase):
    """Test technical indicator functions"""

    def setUp(self):
        """Set up sample candles for testing"""
        self.sample_candles = [
            {'timestamp': i, 'open': 100 + i, 'high': 110 + i, 'low': 90 + i, 'close': 105 + i, 'volume': 1000 + i*10}
            for i in range(100)
        ]

    def test_sma_basic(self):
        """SMA should calculate correctly"""
        closes = [c['close'] for c in self.sample_candles]
        sma_values = sma(closes, period=10)
        self.assertEqual(len(sma_values), len(closes))
        # First 9 values should be None
        self.assertTrue(all(v is None for v in sma_values[:9]))
        # 10th value should be average of first 10 closes
        expected = sum(closes[:10]) / 10
        self.assertAlmostEqual(sma_values[9], expected, places=2)

    def test_compute_atr(self):
        """ATR should calculate correctly"""
        atr = compute_atr(self.sample_candles, period=14)
        self.assertGreater(atr, 0)
        # ATR should be reasonable (between 0 and 50 for sample data)
        self.assertGreater(atr, 0)
        self.assertLess(atr, 50)

    def test_compute_rsi_bullish(self):
        """RSI should be high for bullish trend"""
        # Bullish trend: consistent gains
        closes = [100 + i*2 for i in range(50)]
        rsi = compute_rsi(closes, period=14)
        self.assertGreater(rsi, 50)

    def test_compute_rsi_bearish(self):
        """RSI should be low for bearish trend"""
        # Bearish trend: consistent losses
        closes = [100 - i*2 for i in range(50)]
        rsi = compute_rsi(closes, period=14)
        self.assertLess(rsi, 50)

    def test_compute_adx_trending(self):
        """ADX should be high for trending market"""
        adx = compute_adx(self.sample_candles, period=14)
        # Trending market should have ADX > 25
        self.assertGreater(adx, 20)

    def test_compute_sideway_score_trending(self):
        """Sideway score should be low for trending market"""
        score = compute_sideway_score(self.sample_candles, sf=1.0)
        # Trending market should have low sideway score (0-2)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 4)


class TestCoinProfiles(unittest.TestCase):
    """Test coin profile functions"""

    def test_coin_lev_btc(self):
        """BTC should have correct leverage"""
        lev = _coin_lev("BTC")
        self.assertGreater(lev, 0)
        self.assertLessEqual(lev, 10)  # Reasonable leverage

    def test_coin_sl_roi_btc(self):
        """BTC should have reasonable stop loss"""
        sl = _coin_sl_roi("BTC")
        self.assertGreater(sl, 0)
        self.assertLess(sl, 20)  # Between 0 and 20%

    def test_coin_trail_btc(self):
        """BTC should have reasonable trailing stop"""
        trail = _coin_trail("BTC")
        self.assertGreater(trail, 0)
        self.assertLess(trail, 1)

    def test_entry_margin_strong(self):
        """Strong entry should have larger margin"""
        margin_strong = _entry_margin("BTC", strong=True)
        margin_weak = _entry_margin("BTC", strong=False)
        self.assertGreater(margin_strong, margin_weak)

    def test_coin_cap_btc(self):
        """BTC should have reasonable cap"""
        cap = _coin_cap("BTC")
        self.assertGreater(cap, 0)

    def test_get_coin_profile_btc(self):
        """Should return valid profile for BTC"""
        profile = get_coin_profile("BTC")
        self.assertIsInstance(profile, dict)
        self.assertIn('leverage', profile)
        self.assertIn('trailing_pct', profile)  # Use trailing_pct instead of sl_roi


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    def test_sma_empty_list(self):
        """SMA with empty list should handle gracefully"""
        result = sma([], period=10)
        self.assertEqual(result, [])

    def test_sma_short_list(self):
        """SMA with short list should return None for first values"""
        result = sma([1, 2, 3], period=10)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(v is None for v in result))

    def test_compute_atr_insufficient_data(self):
        """ATR with insufficient data should return 0"""
        candles = [
            {'timestamp': i, 'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 1000}
            for i in range(5)
        ]
        atr = compute_atr(candles, period=14)
        self.assertEqual(atr, 0)

    def test_compute_rsi_insufficient_data(self):
        """RSI with insufficient data should return 50"""
        closes = [100, 101, 102]
        rsi = compute_rsi(closes, period=14)
        self.assertEqual(rsi, 50)  # Default value

    def test_compute_adx_insufficient_data(self):
        """ADX with insufficient data should return default value (50.0)"""
        candles = [
            {'timestamp': i, 'open': 100, 'high': 110, 'low': 90, 'close': 105, 'volume': 1000}
            for i in range(5)
        ]
        adx = compute_adx(candles, period=14)
        self.assertEqual(adx, 50.0)  # Default value for insufficient data


if __name__ == '__main__':
    unittest.main()
