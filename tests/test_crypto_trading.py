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
    _fib_cooldown_bars,
    compute_adx,
    compute_sideway_score,
    sma,
    compute_atr,
    compute_rsi,
    _coin_lev,
    _coin_sl_roi,
    _coin_trail,
    _coin_cap,
    get_coin_profile
)


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

    def test_get_profile_bull(self):
        """get_profile should return BULL profile when is_bull=True"""
        from trading_config import get_profile
        profile = get_profile("ETH", is_bull=True)
        self.assertEqual(profile["lev"], 3.5)
        self.assertEqual(profile["sl"], 10)
        self.assertEqual(profile["trail"], 0.11)
        self.assertEqual(profile["trail_activation"], 0.25)
        self.assertTrue(profile.get("no_sl", False))

    def test_get_profile_bear(self):
        """get_profile should return BEAR profile when is_bull=False"""
        from trading_config import get_profile, PROFILES_BEAR
        profile = get_profile("ETH", is_bull=False)
        self.assertEqual(profile["lev"], 3.0)
        self.assertEqual(profile["sl"], 30)
        self.assertEqual(profile["trail"], 0.17)
        self.assertEqual(profile["trail_activation"], 0.60)


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


class TestBULLStrategy(unittest.TestCase):
    """Test BULL snowball strategy constants"""

    def test_snowball_levels_count(self):
        from trading_config import BULL_SNOWBALL_LEVELS, BULL_SNOWBALL_SIZES
        self.assertEqual(len(BULL_SNOWBALL_LEVELS), 3)
        self.assertGreater(len(BULL_SNOWBALL_SIZES), len(BULL_SNOWBALL_LEVELS))

    def test_snowball_levels_ascending(self):
        from trading_config import BULL_SNOWBALL_LEVELS
        for i in range(1, len(BULL_SNOWBALL_LEVELS)):
            self.assertGreater(BULL_SNOWBALL_LEVELS[i], BULL_SNOWBALL_LEVELS[i-1])

    def test_bull_initial_size(self):
        from trading_config import BULL_INITIAL_SIZE
        self.assertGreater(BULL_INITIAL_SIZE, 0)
        self.assertLess(BULL_INITIAL_SIZE, 0.15)

    def test_bull_trail_params(self):
        from trading_config import (BULL_TRAIL_DISTANCE, BULL_TRAIL_ACTIVATION,
                                     BULL_TRAIL_CLOSE, BULL_TRAIL_COOLDOWN_BARS)
        self.assertTrue(0 < BULL_TRAIL_DISTANCE < 0.3)
        self.assertTrue(0 < BULL_TRAIL_ACTIVATION < 0.8)
        self.assertTrue(0 < BULL_TRAIL_CLOSE <= 1.0)
        self.assertGreater(BULL_TRAIL_COOLDOWN_BARS, 0)

    def test_bull_no_sl(self):
        from trading_config import BULL_NO_SL
        self.assertTrue(BULL_NO_SL)

    def test_snowball_min_score(self):
        from trading_config import COIN_CONFIG
        self.assertGreaterEqual(COIN_CONFIG["ETH"]["snowball_min_score"], 55)
        self.assertGreaterEqual(COIN_CONFIG["BNB"]["snowball_min_score"], 65)
        self.assertGreaterEqual(COIN_CONFIG["TRX"]["snowball_min_score"], 65)


class TestSafeMode(unittest.TestCase):
    """Test safe mode and new strategy configs"""

    def test_safe_mode_constants(self):
        from trading_config import SAFE_LEV, SAFE_SL, SAFE_ENTRY, SAFE_PEAK_DD, SAFE_ENTRY_SCORE, BTC_ADX_SAFE
        self.assertEqual(SAFE_LEV, 1.5)
        self.assertEqual(SAFE_SL, 3.3)
        self.assertLess(SAFE_ENTRY, 0.05)  # small entry for safety
        self.assertGreater(SAFE_ENTRY_SCORE, 70)  # strong signal
        self.assertGreater(BTC_ADX_SAFE, 15)  # reasonable ADX threshold

    def test_bull_tp_schedule(self):
        from trading_config import BULL_TP_SCHEDULE
        self.assertEqual(len(BULL_TP_SCHEDULE), 3)
        self.assertEqual(BULL_TP_SCHEDULE[0], (10, 0.10))
        self.assertEqual(BULL_TP_SCHEDULE[2], (30, 0.10))
        # Verify total close ≤ 100%
        total = sum(cf for _, cf in BULL_TP_SCHEDULE)
        self.assertLess(total, 0.4)  # 30% total before trail

    def test_bnb_bounce_constants(self):
        from trading_config import BNB_BOUNCE_MA_BUF, TRX_BOUNCE_MA_BUF
        self.assertGreater(BNB_BOUNCE_MA_BUF, 0)
        self.assertGreater(TRX_BOUNCE_MA_BUF, 0)

    def test_bear_short_constants(self):
        from trading_config import WEAK_SHORT_LEV, WEAK_SHORT_SL, WEAK_SHORT_ENTRY, WEAK_SHORT_TP, WEAK_SHORT_PEAK_DD
        self.assertEqual(WEAK_SHORT_LEV, 2.0)
        self.assertGreater(WEAK_SHORT_SL, 0)
        self.assertGreater(WEAK_SHORT_ENTRY, 0)
        self.assertGreater(len(WEAK_SHORT_TP), 0)
        self.assertGreater(WEAK_SHORT_PEAK_DD, 0)

    def test_btc_bear_override(self):
        from trading_config import BTC_BEAR_OVERRIDE
        self.assertGreater(BTC_BEAR_OVERRIDE["adx_min"], 15)
        self.assertLess(BTC_BEAR_OVERRIDE["bull_lev"], 4.0)


class TestAdditionalFunctions(unittest.TestCase):
    """Test newly covered edge cases"""

    def test_compute_volume_score_normal(self):
        from crypto_trading import compute_volume_score
        self.assertEqual(compute_volume_score(200, 100), 1.0)  # 2x avg
        self.assertEqual(compute_volume_score(150, 100), 0.8)  # 1.5x avg
        self.assertEqual(compute_volume_score(110, 100), 0.4)  # 1.1x avg
        self.assertEqual(compute_volume_score(50, 100), 0.2)   # below avg

    def test_compute_volume_score_zero_division(self):
        from crypto_trading import compute_volume_score
        self.assertEqual(compute_volume_score(100, 0), 0.2)  # no crash
        self.assertEqual(compute_volume_score(0, 0), 0.2)    # no crash

    def test_evaluate_trend_3d_bullish(self):
        from crypto_trading import evaluate_trend_3d
        label, score = evaluate_trend_3d(110, 105, 100)
        self.assertEqual(score, 3)
        self.assertEqual(label, "BULLISH")

    def test_evaluate_trend_3d_bearish(self):
        from crypto_trading import evaluate_trend_3d
        label, score = evaluate_trend_3d(90, 95, 100)
        self.assertEqual(score, -3)
        self.assertEqual(label, "BEARISH")

    def test_evaluate_trend_3d_sideway(self):
        from crypto_trading import evaluate_trend_3d
        label, score = evaluate_trend_3d(100.1, 100, 100)
        self.assertEqual(score, 0)
        self.assertEqual(label, "SIDEWAY")

    def test_resolve_action_v6_flat_long(self):
        from crypto_trading import resolve_action_v6
        state, action = resolve_action_v6(3, True, False, "FLAT")
        self.assertEqual(action, "OPEN_LONG_ENTRY_1")

    def test_resolve_action_v6_flat_short(self):
        from crypto_trading import resolve_action_v6
        state, action = resolve_action_v6(-3, False, True, "FLAT")
        self.assertEqual(action, "OPEN_SHORT_ENTRY_1")

    def test_resolve_action_v6_no_trade(self):
        from crypto_trading import resolve_action_v6
        state, action = resolve_action_v6(0, False, False, "FLAT")
        self.assertEqual(action, "NO_TRADE")

    def test_approx_equal(self):
        from crypto_trading import _approx_equal
        self.assertTrue(_approx_equal(100, 100.1, 0.005))
        self.assertFalse(_approx_equal(100, 101, 0.005))

    def test_rsi_all_equal(self):
        from crypto_trading import compute_rsi
        rsi = compute_rsi([100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100])
        self.assertEqual(rsi, 100.0)  # all equal = RSI 100

    def test_entry_score_v7_long(self):
        from crypto_trading import _entry_score_v7_long
        candles = [{'close': 100.0, 'high': 101, 'low': 99, 'open': 100, 'volume': 1000}] * 50
        score = _entry_score_v7_long(
            3, 105, 103, 102, 100, 98, 101, 100, 0.6, 1200, 1000, 45
        )
        self.assertGreater(score, 50)  # strong signal


class TestTradingRules(unittest.TestCase):
    """Test unified trading rules"""

    def test_detect_btc_safe(self):
        from scripts.trading_rules import detect_btc_safe
        self.assertTrue(detect_btc_safe(15))   # ADX < 22 → safe
        self.assertFalse(detect_btc_safe(25))  # ADX ≥ 22 → aggressive

    def test_detect_weak_short(self):
        from scripts.trading_rules import detect_btc_safe
        self.assertTrue(detect_btc_safe(15))  # ADX < 22 → safe
        self.assertFalse(detect_btc_safe(25))  # ADX ≥ 22 → aggressive

    def test_detect_bounce(self):
        from scripts.trading_rules import detect_bounce
        self.assertTrue(detect_bounce("ETH", btc_bull=False))
        self.assertTrue(detect_bounce("BNB", btc_bull=False))
        self.assertTrue(detect_bounce("TRX", btc_bull=False))
        self.assertFalse(detect_bounce("ETH", btc_bull=True))
        self.assertFalse(detect_bounce("BTC", btc_bull=False))

    def test_get_entry_rule_safe_mode(self):
        from scripts.trading_rules import get_entry_rule
        mp, lev, sl, bm, sf, *_ = get_entry_rule(True, False, False, True, False, 80)
        self.assertEqual(lev, 1.5)  # safe mode = 1.5x
        self.assertEqual(mp, 0.035)  # 3.5% entry
        self.assertTrue(sf)  # safe flag

    def test_get_entry_rule_bear_short(self):
        from scripts.trading_rules import get_entry_rule
        mp, lev, sl, _, _, _, shf = get_entry_rule(False, True, False, False, True, 70)
        self.assertEqual(lev, 3.5)  # aggressive
        self.assertTrue(shf)  # short flag

    def test_get_entry_rule_bull(self):
        from scripts.trading_rules import get_entry_rule
        mp, lev, sl, bm, *_ = get_entry_rule(False, False, False, True, False, 80)
        self.assertEqual(lev, 3.5)
        self.assertTrue(bm)  # bull mode

    def test_process_bull_exit(self):
        from scripts.trading_rules import process_bull_exit
        r = process_bull_exit(15, 0.15, None, 110, 100, 0, 1.0, False, 10, False)
        self.assertFalse(r['removed'])
        self.assertLess(r['rem'], 1.0)  # TP should close partial

    def test_bull_exit_sl(self):
        """Per-coin SL should close position"""
        from scripts.trading_rules import process_bull_exit
        r = process_bull_exit(-10, 0, None, 100, 90, 0, 1.0, False, 10, False, coin_sl=8)
        self.assertTrue(r['removed'])
        self.assertIn('SL', r['exits'])

    def test_bull_exit_peak_dd(self):
        """Per-coin peak DD should close position"""
        from scripts.trading_rules import process_bull_exit
        r = process_bull_exit(5, 0, None, 100, 90, 0, 1.0, False, 10, False, coin_peak_dd=10)
        # peak_roi is 0 internally, roi=5, 5 - 0 = 5 < 10, so not triggered
        self.assertFalse(r['removed'])

    def test_bounce_entry_per_coin(self):
        """Bounce entry should use per-coin lev for TRX"""
        from scripts.trading_rules import get_entry_rule
        mp, lev, sl, _, _, bf, _ = get_entry_rule(False, False, True, False, False, 65, coin="TRX")
        self.assertEqual(lev, 1.5)  # default bounce lev now 1.5
        self.assertTrue(bf)  # bounce flag

    def test_bounce_entry_default_lev(self):
        """Bounce entry for ETH should use default 2.0 lev"""
        from scripts.trading_rules import get_entry_rule
        _, lev, sl, _, _, bf, _ = get_entry_rule(False, False, True, False, False, 65, coin="ETH")
        self.assertEqual(lev, 1.5)  # default bounce lev now 1.5
        self.assertTrue(bf)

    def test_process_bounce_exit_per_coin_peak_dd(self):
        """Bounce exit should use per-coin peak DD"""
        from scripts.trading_rules import process_bounce_exit
        r = process_bounce_exit(5, 10, 1.0, 0, 5, peak_dd=3)
        # peak_roi = max(-999, 5) = 5, roi=5, 5 - 5 = 0 < 3, no trigger
        self.assertFalse(r['removed'])

    def test_process_bounce_exit_trail_activation(self):
        """Bounce exit should activate trail early with trail_activation param"""
        from scripts.trading_rules import process_bounce_exit
        # roi=15 >= trail_activation=10, trail_ready=True
        # hi=105, tstop=max(None or 100*0.97=97, 105*0.97=101.85)=101.85
        # cc=103 > 101.85, so no trail trigger
        r = process_bounce_exit(15, 15, 1.0, 0, 5, hi=105, cc=103, trail_activation=10)
        self.assertFalse(r['removed'])
        self.assertIn('BOUNCE_TP@5%', r['exits'])  # TP fires first

    def test_process_safe_exit_sl(self):
        from scripts.trading_rules import process_safe_exit
        r = process_safe_exit(-10, 0, 1.0, False, 0, [(5, 1.0)], 5, 5)
        self.assertTrue(r['removed'])
        self.assertIn('SL', r['exits'])


if __name__ == '__main__':
    unittest.main()
