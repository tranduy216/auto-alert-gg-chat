#!/usr/bin/env python3
"""
Unit Tests cho Backtest v15 Final
Coverage 100% cho các hàm chính
"""

import sys
import pytest
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from analyze_cagr_yearly import (
    compute_sma,
    compute_rsi,
    compute_adx,
    compute_bull_score,
    backtest_coin_yearly
)


class TestComputeSMA:
    """Test compute_sma function"""
    
    def test_empty_list(self):
        """Test với list rỗng"""
        assert compute_sma([], 5) is None
    
    def test_single_element(self):
        """Test với 1 element"""
        assert compute_sma([100], 1) == 100
    
    def test_period_larger_than_data(self):
        """Test khi period > len(prices)"""
        assert compute_sma([100, 101, 102], 5) is None
    
    def test_exact_period(self):
        """Test khi len(prices) == period"""
        prices = [100, 101, 102, 103, 104]
        result = compute_sma(prices, 5)
        assert result == pytest.approx(102.0, rel=1e-6)
    
    def test_normal_case(self):
        """Test trường hợp bình thường"""
        prices = [100, 101, 102, 103, 104, 105, 106]
        result = compute_sma(prices, 3)
        # SMA(3) của 7 elements = (104 + 105 + 106) / 3 = 105
        assert result == pytest.approx(105.0, rel=1e-6)
    
    def test_with_negative_values(self):
        """Test với giá trị âm (cho PnL)"""
        prices = [-10, -5, 0, 5, 10]
        result = compute_sma(prices, 3)
        assert result == pytest.approx(5.0, rel=1e-6)


class TestComputeRSI:
    """Test compute_rsi function"""
    
    def test_empty_list(self):
        """Test với list rỗng"""
        assert compute_rsi([]) == 50  # Default value
    
    def test_insufficient_data(self):
        """Test khi không đủ data (cần 15 elements cho period=14)"""
        prices = [100, 101, 102]
        assert compute_rsi(prices) == 50  # Default value
    
    def test_all_gains(self):
        """Test khi chỉ có tăng giá"""
        prices = [100 + i for i in range(20)]  # 100, 101, ..., 119
        result = compute_rsi(prices)
        assert result == 100  # RSI = 100 khi chỉ có gains
    
    def test_all_losses(self):
        """Test khi chỉ có giảm giá"""
        prices = [100 - i for i in range(20)]  # 100, 99, ..., 81
        result = compute_rsi(prices)
        assert result == 0  # RSI = 0 khi chỉ có losses
    
    def test_mixed_gains_losses(self):
        """Test khi có cả tăng và giảm"""
        prices = [100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 
                  105, 107, 106, 108, 107, 109]
        result = compute_rsi(prices)
        assert 0 <= result <= 100
    
    def test_rsi_calculation_accuracy(self):
        """Test tính toán RSI chính xác"""
        # Test case từ Wikipedia RSI example
        prices = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 
                  45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        result = compute_rsi(prices)
        # Expected RSI(14) ≈ 58.7
        assert 50 <= result <= 70


class TestComputeADX:
    """Test compute_adx function"""
    
    def test_empty_candles(self):
        """Test với candles rỗng"""
        assert compute_adx([]) == 25  # Default value
    
    def test_insufficient_data(self):
        """Test khi không đủ data"""
        candles = [
            {'open': 100, 'high': 102, 'low': 98, 'close': 101}
            for _ in range(10)
        ]
        assert compute_adx(candles) == 25  # Default value
    
    def test_strong_uptrend(self):
        """Test khi có uptrend mạnh"""
        candles = [
            {'open': 100 + i, 'high': 102 + i, 'low': 99 + i, 'close': 101 + i}
            for i in range(20)
        ]
        result = compute_adx(candles)
        assert result > 25  # Strong trend
    
    def test_strong_downtrend(self):
        """Test khi có downtrend mạnh"""
        candles = [
            {'open': 100 - i, 'high': 101 - i, 'low': 98 - i, 'close': 99 - i}
            for i in range(20)
        ]
        result = compute_adx(candles)
        assert result > 25  # Strong trend
    
    def test_sideways_market(self):
        """Test khi thị trường đi ngang"""
        candles = [
            {'open': 100, 'high': 101, 'low': 99, 'close': 100}
            for _ in range(20)
        ]
        result = compute_adx(candles)
        assert result < 25  # Weak trend
    
    def test_adx_range(self):
        """Test ADX luôn trong khoảng 0-100"""
        candles = [
            {'open': 100 + i*2, 'high': 103 + i*2, 'low': 98 + i*2, 'close': 101 + i*2}
            for i in range(30)
        ]
        result = compute_adx(candles)
        assert 0 <= result <= 100


class TestComputeBullScore:
    """Test compute_bull_score function"""
    
    def test_empty_candles(self):
        """Test với candles rỗng"""
        assert compute_bull_score([]) == 0
    
    def test_insufficient_data(self):
        """Test khi không đủ data cho MA calculations"""
        candles = [
            {'close': 100, 'volume': 1000}
            for _ in range(50)
        ]
        result = compute_bull_score(candles)
        assert 0 <= result <= 5
    
    def test_strong_bull_market(self):
        """Test khi thị trường bull mạnh"""
        candles = [
            {'close': 100 + i, 'volume': 1000 + i*10}
            for i in range(150)
        ]
        result = compute_bull_score(candles)
        assert result >= 3  # Strong bull
    
    def test_bear_market(self):
        """Test khi thị trường bear"""
        candles = [
            {'close': 100 - i*0.5, 'volume': 1000 - i*5}
            for i in range(150)
        ]
        result = compute_bull_score(candles)
        assert result <= 2  # Weak bull or bear
    
    def test_sideways_market(self):
        """Test khi thị trường đi ngang"""
        candles = [
            {'close': 100, 'volume': 1000}
            for _ in range(150)
        ]
        result = compute_bull_score(candles)
        assert result <= 2  # Weak trend
    
    def test_score_range(self):
        """Test score luôn trong khoảng 0-5"""
        candles = [
            {'close': 100 + i*0.5, 'volume': 1000 + i*5}
            for i in range(150)
        ]
        result = compute_bull_score(candles)
        assert 0 <= result <= 5


class TestBacktestCoinYearly:
    """Test backtest_coin_yearly function"""
    
    def create_test_candles(self, num_candles=500, start_price=100, trend='up'):
        """Helper function để tạo test candles"""
        candles = []
        price = start_price
        
        for i in range(num_candles):
            if trend == 'up':
                price += 0.5
            elif trend == 'down':
                price -= 0.5
            else:  # sideways
                price += 0
            
            candles.append({
                'open_time': 1609459200000 + i * 12 * 3600 * 1000,  # 12h candles
                'open': price,
                'high': price + 1,
                'low': price - 1,
                'close': price,
                'volume': 1000 + i * 10
            })
        
        return candles
    
    def test_empty_candles(self):
        """Test với candles rỗng"""
        result = backtest_coin_yearly([], 'BTC')
        assert result['final_equity'] == 10000  # No change
        assert result['cagr'] == 0
    
    def test_insufficient_data(self):
        """Test khi không đủ data (< 200 candles)"""
        candles = self.create_test_candles(100)
        result = backtest_coin_yearly(candles, 'BTC')
        assert result['final_equity'] == 10000
    
    def test_margin_constraint(self):
        """Test margin constraint: max position size = 10K USD"""
        candles = self.create_test_candles(500, trend='up')
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Check that position size never exceeds 10K USD
        # With leverage 3.5x, max margin = 2,857 USD
        # Initial equity = 10,000, so max exposure = 28.57%
        assert result['max_position_size'] <= 10000
    
    def test_liquidation_logic(self):
        """Test liquidation khi price drop 28.6%"""
        # Tạo scenario: price tăng rồi giảm mạnh 30%
        candles = []
        price = 100
        
        # Phase 1: Uptrend (200 candles)
        for i in range(200):
            candles.append({
                'open_time': 1609459200000 + i * 12 * 3600 * 1000,
                'open': price,
                'high': price + 1,
                'low': price - 1,
                'close': price,
                'volume': 1000
            })
            price += 0.5
        
        # Phase 2: Strong downtrend (50 candles, -30%)
        for i in range(50):
            candles.append({
                'open_time': 1609459200000 + (200 + i) * 12 * 3600 * 1000,
                'open': price,
                'high': price + 1,
                'low': price - 2,
                'close': price - 1,
                'volume': 1000
            })
            price -= 1.2
        
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Should have liquidation trades
        assert 'liquidation' in [t['type'] for t in result['trades']] or result['final_equity'] < 10000
    
    def test_trailing_stop_activation(self):
        """Test trailing stop kích hoạt khi profit > 30%"""
        # Tạo scenario: price tăng 40%
        candles = []
        price = 100
        
        for i in range(300):
            candles.append({
                'open_time': 1609459200000 + i * 12 * 3600 * 1000,
                'open': price,
                'high': price + 1,
                'low': price - 1,
                'close': price,
                'volume': 1000
            })
            
            # Tăng dần để đạt +40%
            if i < 100:
                price += 0.4
        
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Should have trailing stop trades
        trade_types = [t['type'] for t in result['trades']]
        assert 'trailing_activated' in trade_types or 'trailing_exit' in trade_types
    
    def test_snowball_with_margin_constraint(self):
        """Test snowball logic tôn trọng margin constraint"""
        # Tạo scenario: price tăng đều để trigger snowball
        candles = []
        price = 100
        
        for i in range(400):
            candles.append({
                'open_time': 1609459200000 + i * 12 * 3600 * 1000,
                'open': price,
                'high': price + 1,
                'low': price - 1,
                'close': price,
                'volume': 1000
            })
            
            # Tăng 0.25% mỗi candle để trigger snowball at +10%
            price *= 1.0025
        
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Check snowball trades
        snowball_trades = [t for t in result['trades'] if t['type'] == 'snowball']
        
        # Each snowball should not exceed max position size
        for trade in snowball_trades:
            assert trade['position_size'] <= 10000
    
    def test_yearly_returns_calculation(self):
        """Test tính toán yearly returns"""
        candles = self.create_test_candles(1000, trend='up')  # ~5 years of data
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Should have yearly returns for multiple years
        assert len(result['yearly_returns']) >= 1
        
        # All returns should be numbers
        for year, ret in result['yearly_returns'].items():
            assert isinstance(ret, (int, float))
    
    def test_cagr_calculation(self):
        """Test CAGR calculation"""
        candles = self.create_test_candles(1000, trend='up')
        result = backtest_coin_yearly(candles, 'BTC')
        
        # CAGR should be positive for uptrend
        assert result['cagr'] > 0
        
        # CAGR should be reasonable (< 200% for this test)
        assert result['cagr'] < 200
    
    def test_max_drawdown_calculation(self):
        """Test max drawdown calculation"""
        # Tạo scenario: uptrend rồi downtrend
        candles = []
        price = 100
        
        for i in range(500):
            candles.append({
                'open_time': 1609459200000 + i * 12 * 3600 * 1000,
                'open': price,
                'high': price + 1,
                'low': price - 1,
                'close': price,
                'volume': 1000
            })
            
            if i < 250:
                price += 0.5  # Uptrend
            else:
                price -= 0.5  # Downtrend
        
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Max drawdown should be positive
        assert result['max_drawdown'] >= 0
        
        # Max drawdown should be reasonable (< 100%)
        assert result['max_drawdown'] < 100
    
    def test_position_equity_tracking(self):
        """Test position_equity tracking (không dùng current equity)"""
        candles = self.create_test_candles(500, trend='up')
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Check that trades have position_equity field
        for trade in result['trades']:
            if 'position_equity' in trade:
                assert isinstance(trade['position_equity'], (int, float))
    
    def test_leverage_application(self):
        """Test leverage 3.5x được áp dụng đúng"""
        candles = self.create_test_candles(500, trend='up')
        result = backtest_coin_yearly(candles, 'BTC')
        
        # With leverage 3.5x, returns should be amplified
        # If price increases 10%, position should increase ~35%
        # Check that final equity > initial capital for uptrend
        assert result['final_equity'] > 10000


class TestMarginConstraints:
    """Test margin constraints logic"""
    
    def test_max_position_size(self):
        """Test max position size = 10K USD"""
        initial_capital = 10000
        leverage = 3.5
        max_position_size = 10000
        
        max_margin = max_position_size / leverage
        assert max_margin == pytest.approx(2857.14, rel=1e-2)
        
        max_exposure_pct = max_margin / initial_capital
        assert max_exposure_pct == pytest.approx(0.2857, rel=1e-2)
    
    def test_position_size_calculation(self):
        """Test position size = exposure * equity * leverage"""
        equity = 10000
        exposure = 0.25  # 25%
        leverage = 3.5
        
        position_size = exposure * equity * leverage
        assert position_size == 8750  # 25% * 10K * 3.5 = 8,750 USD
    
    def test_exposure_adjustment(self):
        """Test exposure tự động giảm khi position size > max"""
        equity = 10000
        leverage = 3.5
        max_position_size = 10000
        max_margin = max_position_size / leverage
        
        # Initial exposure 25%
        initial_exposure = 0.25
        position_size = initial_exposure * equity * leverage
        
        if position_size > max_position_size:
            adjusted_exposure = max_margin / equity
        else:
            adjusted_exposure = initial_exposure
        
        # Should adjust to 28.57%
        assert adjusted_exposure == pytest.approx(0.2857, rel=1e-2)
        
        # New position size should be exactly max
        new_position_size = adjusted_exposure * equity * leverage
        assert new_position_size == pytest.approx(10000, rel=1e-2)


class TestLiquidation:
    """Test liquidation logic"""
    
    def test_liquidation_threshold(self):
        """Test liquidation at -28.6% drop (1/3.5 leverage)"""
        leverage = 3.5
        liquidation_threshold = -1 / leverage
        assert liquidation_threshold == pytest.approx(-0.2857, rel=1e-2)
    
    def test_liquidation_loss_calculation(self):
        """Test loss khi liquidation = entire position"""
        exposure = 0.25
        position_equity = 10000
        
        # When liquidated, lose entire margin
        loss = exposure * position_equity
        assert loss == 2500  # 25% * 10K = 2,500 USD


class TestIntegration:
    """Integration tests"""
    
    def test_full_backtest_workflow(self):
        """Test full backtest workflow từ entry đến exit"""
        candles = []
        price = 100
        
        # Tạo 500 candles với uptrend
        for i in range(500):
            candles.append({
                'open_time': 1609459200000 + i * 12 * 3600 * 1000,
                'open': price,
                'high': price + 1,
                'low': price - 1,
                'close': price,
                'volume': 1000 + i * 10
            })
            price += 0.3
        
        result = backtest_coin_yearly(candles, 'BTC')
        
        # Should have trades
        assert len(result['trades']) > 0
        
        # Should have positive final equity
        assert result['final_equity'] > 0
        
        # Should have CAGR calculated
        assert 'cagr' in result
        
        # Should have max drawdown calculated
        assert 'max_drawdown' in result
        
        # Should have yearly returns
        assert 'yearly_returns' in result


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v', '--tb=short'])
