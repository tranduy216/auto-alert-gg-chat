#!/usr/bin/env python3
"""
Comprehensive Test: Tìm cách cải thiện HOLD mode

Thử tất cả các approaches:
1. Remove position size limit
2. Relax entry/exit conditions
3. Improve snowball
4. Optimize trailing stop
5. Improve exit logic
6. Hybrid approach
7. Dynamic position sizing
8. Combine best approaches
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import copy

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

def compute_sma(prices, period):
    """Simple Moving Average"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def compute_rsi(prices, period=14):
    """Relative Strength Index"""
    if len(prices) < period + 1:
        return 50
    
    gains = []
    losses = []
    
    for i in range(-period, 0):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_adx(candles, period=14):
    """Average Directional Index"""
    if len(candles) < period + 1:
        return 25
    
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(candles[-(period+1):])):
        high_diff = candles[-(period+1+i)]['high'] - candles[-(period+i)]['high']
        low_diff = candles[-(period+i)]['low'] - candles[-(period+1+i)]['low']
        
        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
        else:
            plus_dm.append(0)
        
        if low_diff > high_diff and low_diff > 0:
            minus_dm.append(low_diff)
        else:
            minus_dm.append(0)
        
        tr = max(
            candles[-(period+1+i)]['high'] - candles[-(period+1+i)]['low'],
            abs(candles[-(period+1+i)]['high'] - candles[-(period+i)]['close']),
            abs(candles[-(period+1+i)]['low'] - candles[-(period+i)]['close'])
        )
        tr_list.append(tr)
    
    # Use Wilder's smoothing
    atr = tr_list[0]
    for tr in tr_list[1:]:
        atr = (atr * (period - 1) + tr) / period
    
    plus_di = plus_dm[0]
    for dm in plus_dm[1:]:
        plus_di = (plus_di * (period - 1) + dm) / period
    
    minus_di = minus_dm[0]
    for dm in minus_dm[1:]:
        minus_di = (minus_di * (period - 1) + dm) / period
    
    if atr == 0:
        return 25
    
    plus_di_pct = 100 * plus_di / atr
    minus_di_pct = 100 * minus_di / atr
    
    di_sum = plus_di_pct + minus_di_pct
    if di_sum == 0:
        return 25
    
    dx = 100 * abs(plus_di_pct - minus_di_pct) / di_sum
    return dx

def compute_bull_score(candles):
    """Compute bull score (0-5)"""
    prices = [c['close'] for c in candles]
    ma20 = compute_sma(prices, 20)
    ma50 = compute_sma(prices, 50)
    ma100 = compute_sma(prices, 100) if len(prices) >= 100 else ma50
    
    slope_50 = (ma50 - ma100) / ma100 if ma100 and ma100 > 0 else 0
    
    volumes = [c['volume'] for c in candles]
    vol_ma20 = compute_sma(volumes, 20)
    vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 and vol_ma20 > 0 else 1
    
    score = 0
    if ma20 and ma50 and ma20 > ma50:
        score += 1
    if ma50 and ma100 and ma50 > ma100:
        score += 1
    if slope_50 > 0:
        score += 1
    if vol_ratio > 1:
        score += 1
    if ma50 and ma100 and ma50 > ma100:
        score += 1
    
    return score

def backtest_coin_yearly(candles, symbol, config):
    """Backtest với custom config"""
    initial_capital = 10000
    equity = initial_capital
    position = None
    
    # Extract config
    max_position_size = config.get('max_position_size', 10000)
    leverage = config.get('leverage', 3.5)
    rsi_max = config.get('rsi_max', 65)
    atr_multiplier = config.get('atr_multiplier', 2.0)
    bull_score_threshold = config.get('bull_score_threshold', 3)
    initial_exposure = config.get('initial_exposure', 0.25)
    max_exposure = config.get('max_exposure', 0.2857)
    snowball_levels = config.get('snowball_levels', [1.10])
    trailing_activation = config.get('trailing_activation', 0.30)
    trailing_stop_pct = config.get('trailing_stop_pct', 0.09)
    trailing_close_pct = config.get('trailing_close_pct', 0.70)
    
    # Calculate max margin
    if max_position_size:
        max_margin = max_position_size / leverage
        max_exposure_pct = max_margin / initial_capital
    else:
        max_exposure_pct = max_exposure
    
    trades = []
    exits = 0
    peak_equity = equity
    max_drawdown = 0
    max_position_size_actual = 0
    
    yearly_equity = {2020: initial_capital}
    current_year = 2020
    
    for i in range(200, len(candles)):
        window = candles[max(0, i-200):i+1]
        prices = [c['close'] for c in window]
        volumes = [c['volume'] for c in window]
        current_price = prices[-1]
        
        # Track year
        candle_date = datetime.fromtimestamp(candles[i]['open_time'] / 1000)
        if candle_date.year != current_year:
            if position:
                unrealized_pnl_pct = (current_price - position['entry_price']) / position['entry_price']
                unrealized_pnl = unrealized_pnl_pct * position['exposure'] * position['position_equity'] * leverage
                yearly_equity[candle_date.year] = equity + unrealized_pnl
            else:
                yearly_equity[candle_date.year] = equity
            current_year = candle_date.year
        
        # Compute indicators
        adx = compute_adx(window)
        bull_score = compute_bull_score(window)
        rsi = compute_rsi(prices)
        ma50 = compute_sma(prices, 50)
        ma20 = compute_sma(prices, 20)
        
        # Determine regime
        if adx > 30 and bull_score >= bull_score_threshold:
            regime = 'HOLD'
        else:
            regime = 'TRADING'
        
        # Exit logic
        if position:
            current_pnl_pct = (current_price - position['entry_price']) / position['entry_price']
            peak_price = position.get('peak_price', position['entry_price'])
            
            # Check for liquidation
            if current_pnl_pct < -0.286:
                loss = position['exposure'] * position['position_equity']
                equity -= loss
                
                trades.append({
                    'type': 'liquidation',
                    'entry': position['entry_price'],
                    'exit': current_price,
                    'pnl_pct': -100,
                    'pnl': -loss,
                    'exposure': position['exposure'],
                    'equity': equity
                })
                
                position = None
                exits += 1
                continue
            
            # Update peak
            if current_price > peak_price:
                position['peak_price'] = current_price
                peak_price = current_price
            
            # Trailing stop trigger
            if current_pnl_pct > trailing_activation and not position.get('trailing_activated'):
                close_pct = trailing_close_pct
                close_exposure = position['exposure'] * close_pct
                pnl = current_pnl_pct * close_exposure * position['position_equity'] * leverage
                equity += pnl
                
                if equity > peak_equity:
                    peak_equity = equity
                drawdown = (peak_equity - equity) / peak_equity * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                
                position['exposure'] = position['exposure'] * (1 - close_pct)
                position['trailing_activated'] = True
                position['trailing_stop_pct'] = trailing_stop_pct
            
            # Trailing stop exit
            if position.get('trailing_activated'):
                trailing_stop_price = peak_price * (1 - position['trailing_stop_pct'])
                if current_price < trailing_stop_price:
                    exit_price = current_price
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                    pnl = pnl_pct * position['exposure'] * position['position_equity'] * leverage
                    equity += pnl
                    
                    if equity > peak_equity:
                        peak_equity = equity
                    drawdown = (peak_equity - equity) / peak_equity * 100
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                    
                    position = None
                    continue
            
            # ATR-based exit
            if not position.get('trailing_activated'):
                atr = compute_adx(window) * current_price / 100
                if current_price < peak_price - atr_multiplier * atr:
                    exit_price = current_price
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                    pnl = pnl_pct * position['exposure'] * position['position_equity'] * leverage
                    equity += pnl
                    
                    if equity > peak_equity:
                        peak_equity = equity
                    drawdown = (peak_equity - equity) / peak_equity * 100
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                    
                    position = None
                    continue
        
        # Entry logic
        if not position and regime == 'HOLD':
            if rsi > rsi_max:
                continue
            
            entry_price = current_price
            exposure = initial_exposure
            
            # Check if position size exceeds max
            if max_position_size:
                position_size = exposure * equity * leverage
                if position_size > max_position_size:
                    exposure = max_margin / equity
            
            if exposure > max_position_size_actual:
                max_position_size_actual = exposure * equity * leverage
            
            position = {
                'entry_price': entry_price,
                'exposure': exposure,
                'position_equity': equity,
                'snowball_levels': snowball_levels,
                'snowball_hit': [],
                'peak_price': entry_price,
                'max_exposure': max_exposure_pct
            }
        
        # Snowball logic
        if position and regime == 'HOLD':
            for level in position['snowball_levels']:
                if level not in position['snowball_hit']:
                    target_price = position['entry_price'] * level
                    if current_price >= target_price:
                        new_exposure = position['exposure'] + initial_exposure
                        new_position_size = new_exposure * position['position_equity'] * leverage
                        
                        if max_position_size is None or new_position_size <= max_position_size:
                            if new_exposure <= max_exposure_pct:
                                position['snowball_hit'].append(level)
                                position['exposure'] = new_exposure
    
    # Close any remaining position
    if position:
        final_price = candles[-1]['close']
        pnl_pct = (final_price - position['entry_price']) / position['entry_price']
        pnl = pnl_pct * position['exposure'] * position['position_equity'] * leverage
        equity += pnl
        
        if equity > peak_equity:
            peak_equity = equity
        drawdown = (peak_equity - equity) / peak_equity * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    yearly_equity[2025] = equity
    
    # Calculate yearly returns
    yearly_returns = {}
    for year in range(2021, 2026):
        if year in yearly_equity and (year-1) in yearly_equity:
            start = yearly_equity[year-1]
            end = yearly_equity[year]
            if start > 0:  # Avoid division by zero
                yearly_returns[year] = (end - start) / start * 100
            else:
                yearly_returns[year] = 0.0
    
    # Calculate CAGR
    years = 5
    cagr = ((equity / initial_capital) ** (1 / years) - 1) * 100
    
    return {
        'symbol': symbol,
        'yearly_returns': yearly_returns,
        'cagr': cagr,
        'final_equity': equity,
        'max_drawdown': max_drawdown,
        'max_position_size': max_position_size_actual,
        'trades': trades
    }

def run_test_suite():
    """Run all test variations"""
    coins = [
        ('ETHUSDT_4000_1609434000000', 'ETH'),
        ('BNBUSDT_4000_1609434000000', 'BNB'),
        ('TRXUSDT_4000_1609434000000', 'TRX')
    ]
    
    # Define test configurations
    configs = {
        'Baseline (v15 Fixed)': {
            'max_position_size': 10000,
            'leverage': 3.5,
            'rsi_max': 65,
            'atr_multiplier': 2.0,
            'bull_score_threshold': 3,
            'initial_exposure': 0.25,
            'max_exposure': 0.2857,
            'snowball_levels': [1.10],
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        },
        
        'Test 1: Remove Position Size Limit': {
            'max_position_size': None,  # No limit
            'leverage': 3.5,
            'rsi_max': 65,
            'atr_multiplier': 2.0,
            'bull_score_threshold': 3,
            'initial_exposure': 0.25,
            'max_exposure': 1.0,  # Allow 100% exposure
            'snowball_levels': [1.10],
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        },
        
        'Test 2: Relax Entry/Exit Conditions': {
            'max_position_size': 10000,
            'leverage': 3.5,
            'rsi_max': 75,  # More relaxed
            'atr_multiplier': 3.0,  # More relaxed
            'bull_score_threshold': 2,  # More relaxed
            'initial_exposure': 0.25,
            'max_exposure': 0.2857,
            'snowball_levels': [1.10],
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        },
        
        'Test 3: Improve Snowball': {
            'max_position_size': None,  # No limit
            'leverage': 3.5,
            'rsi_max': 65,
            'atr_multiplier': 2.0,
            'bull_score_threshold': 3,
            'initial_exposure': 0.50,  # Higher initial
            'max_exposure': 1.0,  # Allow 100%
            'snowball_levels': [1.10, 1.20, 1.30, 1.40, 1.50],  # More levels
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        },
        
        'Test 4: Optimize Trailing Stop': {
            'max_position_size': None,
            'leverage': 3.5,
            'rsi_max': 65,
            'atr_multiplier': 2.0,
            'bull_score_threshold': 3,
            'initial_exposure': 0.25,
            'max_exposure': 1.0,
            'snowball_levels': [1.10, 1.20, 1.30],
            'trailing_activation': 0.50,  # Activate later
            'trailing_stop_pct': 0.15,  # Wider trailing
            'trailing_close_pct': 0.50  # Close less
        },
        
        'Test 5: Improve Exit Logic': {
            'max_position_size': None,
            'leverage': 3.5,
            'rsi_max': 65,
            'atr_multiplier': 4.0,  # Much wider ATR exit
            'bull_score_threshold': 3,
            'initial_exposure': 0.25,
            'max_exposure': 1.0,
            'snowball_levels': [1.10, 1.20, 1.30],
            'trailing_activation': 0.30,
            'trailing_stop_pct': 0.09,
            'trailing_close_pct': 0.70
        },
        
        'Test 6: Dynamic Position Sizing': {
            'max_position_size': None,
            'leverage': 3.5,
            'rsi_max': 70,
            'atr_multiplier': 2.5,
            'bull_score_threshold': 2,
            'initial_exposure': 0.50,  # Higher for high confidence
            'max_exposure': 1.0,
            'snowball_levels': [1.10, 1.20, 1.30, 1.40, 1.50],
            'trailing_activation': 0.40,
            'trailing_stop_pct': 0.12,
            'trailing_close_pct': 0.60
        },
        
        'Test 7: Best Combined': {
            'max_position_size': None,  # No limit
            'leverage': 3.5,
            'rsi_max': 70,  # Relaxed
            'atr_multiplier': 3.0,  # Relaxed
            'bull_score_threshold': 2,  # Relaxed
            'initial_exposure': 0.50,  # Higher
            'max_exposure': 1.0,  # Allow 100%
            'snowball_levels': [1.10, 1.20, 1.30, 1.40, 1.50],  # More levels
            'trailing_activation': 0.50,  # Activate later
            'trailing_stop_pct': 0.15,  # Wider
            'trailing_close_pct': 0.50  # Close less
        }
    }
    
    results = {}
    
    for config_name, config in configs.items():
        print(f"\n{'='*100}")
        print(f"Testing: {config_name}")
        print(f"{'='*100}")
        
        coin_results = []
        for symbol_key, symbol_name in coins:
            candles = data[symbol_key]
            result = backtest_coin_yearly(candles, symbol_name, config)
            coin_results.append(result)
            print(f"  {symbol_name}: CAGR={result['cagr']:.2f}%, Final=${result['final_equity']:,.2f}")
        
        # Calculate average
        avg_cagr = sum(r['cagr'] for r in coin_results) / len(coin_results)
        avg_final = sum(r['final_equity'] for r in coin_results) / len(coin_results)
        avg_dd = sum(r['max_drawdown'] for r in coin_results) / len(coin_results)
        
        results[config_name] = {
            'avg_cagr': avg_cagr,
            'avg_final': avg_final,
            'avg_dd': avg_dd,
            'coin_results': coin_results
        }
        
        print(f"\n  Average: CAGR={avg_cagr:.2f}%, Final=${avg_final:,.2f}, Max DD={avg_dd:.2f}%")
    
    # Summary
    print(f"\n{'='*100}")
    print("SUMMARY - All Test Results")
    print(f"{'='*100}")
    print(f"{'Config':<40} {'CAGR':>10} {'Final':>15} {'Max DD':>10}")
    print(f"{'-'*100}")
    
    sorted_results = sorted(results.items(), key=lambda x: x[1]['avg_cagr'], reverse=True)
    for config_name, result in sorted_results:
        print(f"{config_name:<40} {result['avg_cagr']:>9.2f}% ${result['avg_final']:>13,.2f} {result['avg_dd']:>9.2f}%")
    
    # Best result
    best_config, best_result = sorted_results[0]
    print(f"\n{'='*100}")
    print(f"🏆 BEST CONFIG: {best_config}")
    print(f"{'='*100}")
    print(f"  Average CAGR: {best_result['avg_cagr']:.2f}%")
    print(f"  Average Final: ${best_result['avg_final']:,.2f}")
    print(f"  Average Max DD: {best_result['avg_dd']:.2f}%")
    
    print(f"\nPer-coin breakdown:")
    for r in best_result['coin_results']:
        print(f"  {r['symbol']}: CAGR={r['cagr']:.2f}%, Final=${r['final_equity']:,.2f}, Max DD={r['max_drawdown']:.2f}%")
    
    # Compare with baseline
    baseline = results['Baseline (v15 Fixed)']
    improvement = best_result['avg_cagr'] - baseline['avg_cagr']
    print(f"\nImprovement vs Baseline: {improvement:+.2f}% CAGR")
    
    return results, best_config, configs[best_config]

if __name__ == '__main__':
    results, best_config, best_params = run_test_suite()
    
    # Save best config
    with open('best_config.json', 'w') as f:
        json.dump({
            'config_name': best_config,
            'params': best_params
        }, f, indent=2)
    
    print(f"\n✅ Best config saved to best_config.json")
