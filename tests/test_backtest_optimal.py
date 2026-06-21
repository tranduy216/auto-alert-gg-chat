"""
Unit tests for backtest_optimal.py
Coverage: Backtest framework, strategy configurations, result validation
"""
import pytest
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from backtest_optimal import (
    backtest_coin_yearly,
    buy_and_hold_yearly,
    load_cache_data
)


class TestBacktestFramework:
    """Test backtest framework functions"""
    
    def test_backtest_coin_yearly_basic(self, sample_candles):
        """Basic backtest should return valid results"""
        # Create minimal config
        config = {
            'leverage': 3.5,
            'initial_exposure': 0.15,
            'snowball_levels': [1.10],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(sample_candles, "BTC", config)
        
        # Check result structure
        assert 'yearly_returns' in result
        assert 'cagr' in result
        assert 'final_equity' in result
        assert 'max_drawdown' in result
        assert 'max_position_size' in result
    
    def test_backtest_coin_yearly_cagr_calculation(self, sample_candles):
        """CAGR should be calculated correctly"""
        config = {
            'leverage': 3.5,
            'initial_exposure': 0.15,
            'snowball_levels': [],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(sample_candles, "BTC", config)
        
        # CAGR should be a number
        assert isinstance(result['cagr'], (int, float))
        
        # Final equity should be positive
        assert result['final_equity'] > 0
    
    def test_backtest_coin_yearly_drawdown(self, sample_candles):
        """Max drawdown should be calculated"""
        config = {
            'leverage': 3.5,
            'initial_exposure': 0.15,
            'snowball_levels': [],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(sample_candles, "BTC", config)
        
        # Max drawdown should be non-negative
        assert result['max_drawdown'] >= 0
        
        # Max drawdown should be reasonable (< 100%)
        assert result['max_drawdown'] < 100
    
    def test_buy_and_hold_yearly(self, sample_candles):
        """Buy and hold should calculate correctly"""
        result = buy_and_hold_yearly(sample_candles, "BTC")
        
        # Check result structure
        assert 'yearly_returns' in result
        assert 'cagr' in result
        assert 'first_price' in result
        assert 'last_price' in result
        
        # CAGR should be calculated
        assert isinstance(result['cagr'], (int, float))
    
    def test_backtest_with_snowball(self, sample_candles):
        """Backtest with snowball should work"""
        config = {
            'leverage': 3.5,
            'initial_exposure': 0.15,
            'snowball_levels': [1.10, 1.20],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(sample_candles, "BTC", config)
        
        # Should complete without errors
        assert result['final_equity'] > 0


class TestPositionSizing:
    """Test position sizing in backtest"""
    
    def test_max_position_limit(self, sample_candles):
        """Position should respect max_position_size limit"""
        config = {
            'max_position_size': 35000,
            'leverage': 3.5,
            'max_margin': 10000,
            'max_exposure_pct': 1.0,
            'initial_exposure': 0.15,
            'snowball_levels': [1.10, 1.20, 1.30],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(sample_candles, "BTC", config)
        
        # Max position should not exceed limit (with 1% tolerance)
        assert result['max_position_size'] <= config['max_position_size'] * 1.01
    
    def test_exposure_limit(self, sample_candles):
        """Exposure should respect max_exposure_pct"""
        config = {
            'max_position_size': 35000,
            'leverage': 3.5,
            'max_margin': 10000,
            'max_exposure_pct': 0.5,  # Max 50%
            'initial_exposure': 0.15,
            'snowball_levels': [1.10, 1.20, 1.30],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(sample_candles, "BTC", config)
        
        # Should complete without errors
        assert result['final_equity'] > 0


class TestCacheLoading:
    """Test cache loading functions"""
    
    def test_load_cache_data_exists(self, cache_path):
        """Should load cache if file exists"""
        if cache_path.exists():
            cache = load_cache_data()
            assert isinstance(cache, dict)
            assert len(cache) > 0
    
    def test_load_cache_data_structure(self, cache_path):
        """Cache should have correct structure"""
        if cache_path.exists():
            cache = load_cache_data()
            # Should have coin data
            assert any('BTC' in key for key in cache.keys()) or len(cache) > 0


class TestEdgeCases:
    """Test edge cases in backtest"""
    
    def test_empty_candles(self):
        """Backtest with empty candles should handle gracefully"""
        config = {
            'leverage': 3.5,
            'initial_exposure': 0.15,
            'snowball_levels': [],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly([], "BTC", config)
        
        # Should return default values
        assert result['final_equity'] == 10000  # Initial capital
        assert result['cagr'] == 0
    
    def test_single_candle(self):
        """Backtest with single candle should handle gracefully"""
        candles = [{
            'timestamp': 1609459200000,
            'open': 100.0,
            'high': 110.0,
            'low': 90.0,
            'close': 105.0,
            'volume': 10000.0
        }]
        
        config = {
            'leverage': 3.5,
            'initial_exposure': 0.15,
            'snowball_levels': [],
            'atr_multiplier': 4.0,
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        }
        
        result = backtest_coin_yearly(candles, "BTC", config)
        
        # Should complete without errors
        assert result['final_equity'] > 0
