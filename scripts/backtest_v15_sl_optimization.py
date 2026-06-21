#!/usr/bin/env python3
"""
Backtest v15: Giảm SL Rate cho Hybrid Strategy

Approaches:
1. Reduce initial exposure (10%, 15%, 20% vs 25%)
2. Signal quality filters (RSI, Volume, MACD, etc.)
3. Entry timing (wait for pullback, confirmation)
4. Exit logic (trailing stop, ATR-based)

Target: SL Rate < 25%
Current: SL Rate 47.6% (Hybrid v14)
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

# Get ETH data
eth_data = data["ETHUSDT_4000_1609434000000"]
eth_candles = [{"timestamp": k['open_time'], "open": k['open'], "high": k['high'], 
                "low": k['low'], "close": k['close'], "volume": k['volume']} 
               for k in eth_data]

print(f"Loaded {len(eth_candles)} ETH candles")

# Helper functions
def compute_sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def compute_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices[-(period+1):]))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_adx(candles, period=14):
    if len(candles) < period + 1:
        return 25
    highs = [c['high'] for c in candles[-(period+1):]]
    lows = [c['low'] for c in candles[-(period+1):]]
    closes = [c['close'] for c in candles[-(period+1):]]
    
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(candles[-(period+1):])):
        high_diff = highs[i] - highs[i-1]
        low_diff = lows[i-1] - lows[i]
        
        if high_diff > low_diff and high_diff > 0:
            plus_dm.append(high_diff)
        else:
            plus_dm.append(0)
            
        if low_diff > high_diff and low_diff > 0:
            minus_dm.append(low_diff)
        else:
            minus_dm.append(0)
            
        tr = max(highs[i] - lows[i], 
                 abs(highs[i] - closes[i-1]), 
                 abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return 25
        
    atr = sum(tr_list[-period:]) / period
    plus_di = sum(plus_dm[-period:]) / period
    minus_di = sum(minus_dm[-period:]) / period
    
    if atr == 0:
        return 25
        
    plus_di_pct = 100 * plus_di / atr
    minus_di_pct = 100 * minus_di / atr
    
    di_sum = plus_di_pct + minus_di_pct
    if di_sum == 0:
        return 25
        
    dx = 100 * abs(plus_di_pct - minus_di_pct) / di_sum
    return dx

def compute_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return 0, 0, 0
    fast_ema = compute_ema(prices, fast)
    slow_ema = compute_ema(prices, slow)
    macd_line = fast_ema - slow_ema
    signal_line = compute_ema([macd_line], signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_ema(prices, period):
    if len(prices) < period:
        return prices[-1]
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def compute_bull_score(candles):
    prices = [c['close'] for c in candles]
    ma20 = compute_sma(prices, 20)
    ma50 = compute_sma(prices, 50)
    ma100 = compute_sma(prices, 100) if len(prices) >= 100 else ma50
    
    slope_50 = (ma50 - ma100) / ma100 if ma100 else 0
    volumes = [c['volume'] for c in candles]
    vol_ma20 = compute_sma(volumes, 20)
    vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 else 1
    
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

# Backtest function
def backtest_hybrid(candles, initial_exposure=0.25, signal_filters=None, exit_strategy='ma50_cross'):
    """
    signal_filters: dict with keys like 'rsi_max', 'min_volume_ratio', 'require_macd_bullish'
    exit_strategy: 'ma50_cross', 'trailing_stop', 'atr_based'
    """
    initial_capital = 10000
    equity = initial_capital
    position = None
    trades = []
    
    signal_filters = signal_filters or {}
    rsi_max = signal_filters.get('rsi_max', 70)
    min_volume_ratio = signal_filters.get('min_volume_ratio', 1.0)
    require_macd_bullish = signal_filters.get('require_macd_bullish', False)
    require_pullback = signal_filters.get('require_pullback', False)
    
    for i in range(200, len(candles)):
        window = candles[max(0, i-200):i+1]
        prices = [c['close'] for c in window]
        volumes = [c['volume'] for c in window]
        current_price = prices[-1]
        
        # Compute indicators
        adx = compute_adx(window)
        bull_score = compute_bull_score(window)
        rsi = compute_rsi(prices)
        vol_ma20 = compute_sma(volumes, 20)
        vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 else 1
        macd_line, signal_line, histogram = compute_macd(prices)
        ma50 = compute_sma(prices, 50)
        ma20 = compute_sma(prices, 20)
        
        # Determine regime
        if adx > 30 and bull_score >= 3:
            regime = 'HOLD'
        elif adx > 30 and bull_score < 3:
            regime = 'TRADING_SHORT'
        else:
            regime = 'TRADING_BOTH'
        
        # Exit logic
        if position:
            should_exit = False
            
            if exit_strategy == 'ma50_cross':
                # Exit when MA20 crosses below MA50
                if ma20 and ma50 and ma20 < ma50:
                    should_exit = True
                    
            elif exit_strategy == 'trailing_stop':
                # 15% trailing stop from peak
                peak_price = position.get('peak_price', position['entry_price'])
                if current_price > peak_price:
                    position['peak_price'] = current_price
                    peak_price = current_price
                
                if current_price < peak_price * 0.85:
                    should_exit = True
                    
            elif exit_strategy == 'atr_based':
                # Exit if price drops 2x ATR from peak
                atr = compute_adx(window) * current_price / 100  # Approximate ATR
                peak_price = position.get('peak_price', position['entry_price'])
                if current_price > peak_price:
                    position['peak_price'] = current_price
                    peak_price = current_price
                
                if current_price < peak_price - 2 * atr:
                    should_exit = True
            
            if should_exit:
                exit_price = current_price
                pnl = (exit_price - position['entry_price']) / position['entry_price'] * position['exposure'] * equity
                equity += pnl
                trades.append({
                    'type': 'exit',
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'exposure': position['exposure'],
                    'hold_days': (datetime.fromtimestamp(candles[i]['timestamp']/1000) - 
                                 datetime.fromtimestamp(position['entry_time']/1000)).days
                })
                position = None
                continue
        
        # Entry logic
        if not position and regime == 'HOLD':
            # Check signal filters
            if rsi > rsi_max:
                continue
            if vol_ratio < min_volume_ratio:
                continue
            if require_macd_bullish and histogram <= 0:
                continue
            if require_pullback and current_price > ma20:
                continue
            
            # Enter HOLD
            entry_price = current_price
            exposure = initial_exposure
            
            # Snowball: add at +10%, +20%, +30%
            position = {
                'entry_price': entry_price,
                'entry_time': candles[i]['timestamp'],
                'exposure': exposure,
                'snowball_levels': [1.10, 1.20, 1.30],
                'snowball_hit': [],
                'peak_price': entry_price
            }
            trades.append({
                'type': 'entry',
                'entry_price': entry_price,
                'exposure': exposure
            })
        
        # Snowball logic
        if position and regime == 'HOLD':
            for level in position['snowball_levels']:
                if level not in position['snowball_hit']:
                    target_price = position['entry_price'] * level
                    if current_price >= target_price:
                        position['snowball_hit'].append(level)
                        position['exposure'] += initial_exposure  # Add same amount
                        trades.append({
                            'type': 'snowball',
                            'price': current_price,
                            'level': level,
                            'exposure': position['exposure']
                        })
    
    # Calculate metrics
    total_return = (equity - initial_capital) / initial_capital * 100
    years = len(candles) / (365 * 2)  # 12h candles
    cagr = ((equity / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
    
    # Max drawdown
    peak = initial_capital
    max_dd = 0
    current_equity = initial_capital
    for trade in trades:
        if trade['type'] in ['exit']:
            current_equity += trade['pnl']
            if current_equity > peak:
                peak = current_equity
            dd = (peak - current_equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
    
    # SL rate
    exit_trades = [t for t in trades if t['type'] == 'exit']
    losing_trades = [t for t in exit_trades if t['pnl'] < 0]
    sl_rate = len(losing_trades) / len(exit_trades) * 100 if exit_trades else 0
    
    # Average PnL
    avg_pnl = sum([t['pnl'] for t in exit_trades]) / len(exit_trades) if exit_trades else 0
    
    return {
        'cagr': cagr,
        'total_return': total_return,
        'max_dd': max_dd,
        'sl_rate': sl_rate,
        'num_trades': len(exit_trades),
        'avg_pnl': avg_pnl,
        'equity': equity
    }

# Test configurations
configs = [
    # Baseline
    {
        'name': 'Baseline (v14 Hybrid)',
        'initial_exposure': 0.25,
        'signal_filters': {},
        'exit_strategy': 'ma50_cross'
    },
    # Reduce exposure
    {
        'name': 'Exposure 10%',
        'initial_exposure': 0.10,
        'signal_filters': {},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'Exposure 15%',
        'initial_exposure': 0.15,
        'signal_filters': {},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'Exposure 20%',
        'initial_exposure': 0.20,
        'signal_filters': {},
        'exit_strategy': 'ma50_cross'
    },
    # Signal quality filters
    {
        'name': 'RSI < 60',
        'initial_exposure': 0.25,
        'signal_filters': {'rsi_max': 60},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'RSI < 65',
        'initial_exposure': 0.25,
        'signal_filters': {'rsi_max': 65},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'Volume > 1.5x',
        'initial_exposure': 0.25,
        'signal_filters': {'min_volume_ratio': 1.5},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'MACD Bullish',
        'initial_exposure': 0.25,
        'signal_filters': {'require_macd_bullish': True},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'Wait for Pullback',
        'initial_exposure': 0.25,
        'signal_filters': {'require_pullback': True},
        'exit_strategy': 'ma50_cross'
    },
    # Combined filters
    {
        'name': 'RSI<65 + Vol>1.5x',
        'initial_exposure': 0.25,
        'signal_filters': {'rsi_max': 65, 'min_volume_ratio': 1.5},
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'RSI<65 + MACD + Pullback',
        'initial_exposure': 0.25,
        'signal_filters': {'rsi_max': 65, 'require_macd_bullish': True, 'require_pullback': True},
        'exit_strategy': 'ma50_cross'
    },
    # Exit strategies
    {
        'name': 'Trailing Stop 15%',
        'initial_exposure': 0.25,
        'signal_filters': {},
        'exit_strategy': 'trailing_stop'
    },
    {
        'name': 'RSI<65 + Trailing Stop',
        'initial_exposure': 0.25,
        'signal_filters': {'rsi_max': 65},
        'exit_strategy': 'trailing_stop'
    },
    {
        'name': 'Exp15% + RSI<65 + Trailing',
        'initial_exposure': 0.15,
        'signal_filters': {'rsi_max': 65},
        'exit_strategy': 'trailing_stop'
    },
    # ATR-based exit
    {
        'name': 'ATR-based Exit',
        'initial_exposure': 0.25,
        'signal_filters': {},
        'exit_strategy': 'atr_based'
    },
    {
        'name': 'RSI<65 + ATR Exit',
        'initial_exposure': 0.25,
        'signal_filters': {'rsi_max': 65},
        'exit_strategy': 'atr_based'
    },
]

print("\n" + "="*100)
print("BACKTEST V15: SL RATE OPTIMIZATION")
print("="*100)
print(f"\nTarget: SL Rate < 25%")
print(f"Current baseline: SL Rate 47.6% (Hybrid v14)")
print("\n" + "="*100)

results = []
for config in configs:
    print(f"\nTesting: {config['name']}")
    result = backtest_hybrid(
        eth_candles,
        initial_exposure=config['initial_exposure'],
        signal_filters=config['signal_filters'],
        exit_strategy=config['exit_strategy']
    )
    result['name'] = config['name']
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2f}%, DD: {result['max_dd']:.2f}%, "
          f"SL Rate: {result['sl_rate']:.2f}%, Trades: {result['num_trades']}")

# Sort by SL rate
results_sorted = sorted(results, key=lambda x: x['sl_rate'])

print("\n" + "="*100)
print("RESULTS SORTED BY SL RATE")
print("="*100)
print(f"{'Name':<40} {'CAGR':>8} {'Max DD':>8} {'SL Rate':>8} {'Trades':>8}")
print("-"*100)

for r in results_sorted:
    marker = "⭐" if r['sl_rate'] < 25 else ""
    print(f"{r['name']:<40} {r['cagr']:>7.2f}% {r['max_dd']:>7.2f}% {r['sl_rate']:>7.2f}% {r['num_trades']:>8} {marker}")

print("\n" + "="*100)
print("RECOMMENDATIONS")
print("="*100)

# Find best configs
low_sl = [r for r in results_sorted if r['sl_rate'] < 25]
if low_sl:
    print(f"\n✅ Found {len(low_sl)} configs with SL Rate < 25%:")
    for r in low_sl[:5]:
        print(f"  - {r['name']}: CAGR {r['cagr']:.2f}%, DD {r['max_dd']:.2f}%, SL {r['sl_rate']:.2f}%")
else:
    print("\n❌ No configs achieved SL Rate < 25%")
    print("\nBest 3 configs:")
    for r in results_sorted[:3]:
        print(f"  - {r['name']}: CAGR {r['cagr']:.2f}%, DD {r['max_dd']:.2f}%, SL {r['sl_rate']:.2f}%")

print("\n" + "="*100)
