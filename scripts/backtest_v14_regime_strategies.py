#!/usr/bin/env python3
"""
Backtest v14: Test 3 regime detection strategies

1. Coin-specific regime: Dùng MA50/MA200 của chính coin
2. ADX-based: ADX > 30 = HOLD, ADX < 30 = Trading
3. Hybrid: ADX > 30 + bull_score >= 3 = HOLD

So sánh với:
- Baseline v11: 31.5% CAGR (Trading only)
- HOLD Snowball L1: 19.2% CAGR (BTC regime)
"""

import sys
import os
import json
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Constants
BASE_CAPITAL = 10000
FEE_RATE = 0.001  # 0.1%
COINS = ['ETH', 'BNB', 'TRX']

# Snowball parameters (Level 1)
SNOWBALL_INITIAL = 0.25
SNOWBALL_ADD_LEVELS = [0.10, 0.20, 0.30]
SNOWBALL_ADD_SIZE = 0.25

# Anti-FOMO
ANTI_FOMO_ATR_THRESHOLD = 0.08
ANTI_FOMO_OVERHEATED_THRESHOLD = 0.30

# Cooldown
COOLDOWN_BARS = 8  # 4 days (8 x 12h candles)


def load_cache():
    cache_path = os.path.join(os.path.dirname(__file__), '_klines_12h_5y.json')
    print(f"Loading cache from: {cache_path}")
    with open(cache_path, 'r') as f:
        cache = json.load(f)
    print(f"Cache loaded. Available symbols: {list(cache.keys())[:10]}")
    return cache


def sma(values, period):
    if len(values) < period:
        return values[-1] if values else 0
    return sum(values[-period:]) / period


def compute_adx(candles, period=14):
    if len(candles) < period + 1:
        return 0
    
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(candles)):
        high_diff = candles[i]['high'] - candles[i-1]['high']
        low_diff = candles[i-1]['low'] - candles[i]['low']
        
        plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
        minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
        
        tr = max(
            candles[i]['high'] - candles[i]['low'],
            abs(candles[i]['high'] - candles[i-1]['close']),
            abs(candles[i]['low'] - candles[i-1]['close'])
        )
        tr_list.append(tr)
    
    if len(tr_list) < period:
        return 0
    
    atr = sum(tr_list[:period]) / period
    plus_di = 100 * sum(plus_dm[:period]) / period / atr if atr > 0 else 0
    minus_di = 100 * sum(minus_dm[:period]) / period / atr if atr > 0 else 0
    
    di_sum = plus_di + minus_di
    dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0
    
    return dx


def compute_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0
    
    tr_list = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]['high'] - candles[i]['low'],
            abs(candles[i]['high'] - candles[i-1]['close']),
            abs(candles[i]['low'] - candles[i-1]['close'])
        )
        tr_list.append(tr)
    
    return sum(tr_list[-period:]) / period if len(tr_list) >= period else 0


def compute_bull_score(candles):
    closes = [c['close'] for c in candles]
    volumes = [c['volume'] for c in candles]
    
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    ma100 = sma(closes, 100)
    ma200 = sma(closes, 200)
    
    if len(closes) > 10:
        ma50_10_ago = sma(closes[:-10], 50)
    else:
        ma50_10_ago = ma50
    
    slope50 = (ma50 - ma50_10_ago) / ma50_10_ago if ma50_10_ago > 0 else 0
    
    vol_sma20 = sma(volumes, 20)
    vol_ratio = volumes[-1] / vol_sma20 if vol_sma20 > 0 else 1.0
    
    score = 0
    if ma20 > ma50:
        score += 1
    if ma50 > ma100:
        score += 1
    if slope50 > 0:
        score += 1
    if vol_ratio > 1.0:
        score += 1
    if ma50 > ma200:
        score += 1
    
    return score


def detect_regime_coin_specific(candles):
    """Approach 1: Coin-specific regime"""
    closes = [c['close'] for c in candles]
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200)
    return 'BULL' if ma50 > ma200 else 'BEAR'


def detect_regime_adx(candles):
    """Approach 2: ADX-based"""
    adx = compute_adx(candles)
    if adx > 30:
        # Strong trend - check direction
        closes = [c['close'] for c in candles]
        ma50 = sma(closes, 50)
        ma200 = sma(closes, 200)
        return 'HOLD' if ma50 > ma200 else 'TRADING'
    return 'TRADING'


def detect_regime_hybrid(candles):
    """Approach 3: Hybrid ADX + bull score"""
    adx = compute_adx(candles)
    bull_score = compute_bull_score(candles)
    
    if adx > 30 and bull_score >= 3:
        return 'HOLD'
    elif adx > 30 and bull_score < 3:
        return 'TRADING_SHORT'
    else:
        return 'TRADING_BOTH'


def check_anti_fomo(candles):
    atr = compute_atr(candles)
    current_price = candles[-1]['close']
    
    if current_price > 0 and atr / current_price > ANTI_FOMO_ATR_THRESHOLD:
        return True
    
    closes = [c['close'] for c in candles]
    ma50 = sma(closes, 50)
    if ma50 > 0 and (current_price - ma50) / ma50 > ANTI_FOMO_OVERHEATED_THRESHOLD:
        return True
    
    return False


def run_backtest_v14(cache, coin, strategy):
    """
    strategy: 'coin_specific', 'adx', 'hybrid'
    """
    # Try different key formats
    symbol = f"{coin}USDT"
    symbol_with_suffix = f"{coin}USDT_4000_1609434000000"
    
    candles = cache.get(symbol) or cache.get(symbol_with_suffix, [])
    
    if not candles or len(candles) < 200:
        print(f"Warning: No data for {coin} (tried {symbol} and {symbol_with_suffix})")
        return None
    
    equity = BASE_CAPITAL
    equity_curve = [equity]
    trades = []
    
    hold_position = None  # {entry_price, size, tp_levels_hit}
    cooldown_until = 0
    
    for idx in range(200, len(candles)):
        current_candles = candles[:idx+1]
        current_price = current_candles[-1]['close']
        
        # Detect regime based on strategy
        if strategy == 'coin_specific':
            regime = detect_regime_coin_specific(current_candles)
            mode = 'HOLD' if regime == 'BULL' else 'TRADING'
        elif strategy == 'adx':
            mode = detect_regime_adx(current_candles)
        else:  # hybrid
            mode = detect_regime_hybrid(current_candles)
        
        # HOLD mode
        if mode == 'HOLD':
            if hold_position is None:
                # Enter HOLD with snowball
                if check_anti_fomo(current_candles):
                    equity_curve.append(equity)
                    continue
                
                hold_position = {
                    'entry_price': current_price,
                    'size': SNOWBALL_INITIAL,
                    'tp_levels_hit': [],
                    'entry_idx': idx
                }
                trades.append({
                    'type': 'HOLD_ENTRY',
                    'price': current_price,
                    'size': SNOWBALL_INITIAL,
                    'idx': idx
                })
            else:
                # Check snowball adds
                entry_price = hold_position['entry_price']
                current_size = hold_position['size']
                
                for i, add_level in enumerate(SNOWBALL_ADD_LEVELS):
                    if i not in hold_position['tp_levels_hit']:
                        target_price = entry_price * (1 + add_level)
                        if current_price >= target_price and current_size + SNOWBALL_ADD_SIZE <= 1.0:
                            hold_position['size'] += SNOWBALL_ADD_SIZE
                            hold_position['tp_levels_hit'].append(i)
                            trades.append({
                                'type': 'SNOWBALL_ADD',
                                'price': current_price,
                                'size': SNOWBALL_ADD_SIZE,
                                'idx': idx
                            })
                
                # Check exit: MA50 cross
                closes = [c['close'] for c in current_candles]
                ma20 = sma(closes, 20)
                ma50 = sma(closes, 50)
                
                # Exit if MA20 < MA50 for 2 bars
                if idx >= 2:
                    prev_candles = candles[:idx]
                    prev_ma20 = sma([c['close'] for c in prev_candles], 20)
                    prev_ma50 = sma([c['close'] for c in prev_candles], 50)
                    
                    if ma20 < ma50 and prev_ma20 < prev_ma50:
                        # Exit
                        pnl_pct = (current_price - entry_price) / entry_price
                        pnl = equity * hold_position['size'] * pnl_pct
                        equity += pnl * (1 - FEE_RATE)
                        
                        trades.append({
                            'type': 'HOLD_EXIT',
                            'price': current_price,
                            'pnl_pct': pnl_pct * 100,
                            'pnl': pnl,
                            'idx': idx
                        })
                        
                        hold_position = None
                        cooldown_until = idx + COOLDOWN_BARS
        
        # TRADING mode
        elif 'TRADING' in mode:
            if hold_position is not None:
                # Exit HOLD if switching to trading
                entry_price = hold_position['entry_price']
                pnl_pct = (current_price - entry_price) / entry_price
                pnl = equity * hold_position['size'] * pnl_pct
                equity += pnl * (1 - FEE_RATE)
                
                trades.append({
                    'type': 'HOLD_EXIT',
                    'price': current_price,
                    'pnl_pct': pnl_pct * 100,
                    'pnl': pnl,
                    'idx': idx
                })
                
                hold_position = None
                cooldown_until = idx + COOLDOWN_BARS
            
            # Trading logic (simplified - just count signals)
            # In real implementation, this would use full trading logic from crypto_trading.py
            pass
        
        equity_curve.append(equity)
    
    # Close any remaining position
    if hold_position is not None:
        final_price = candles[-1]['close']
        entry_price = hold_position['entry_price']
        pnl_pct = (final_price - entry_price) / entry_price
        pnl = equity * hold_position['size'] * pnl_pct
        equity += pnl * (1 - FEE_RATE)
        equity_curve[-1] = equity
    
    # Calculate metrics
    if len(equity_curve) < 2:
        return None
    
    # CAGR
    total_return = (equity_curve[-1] - BASE_CAPITAL) / BASE_CAPITAL
    years = (len(candles) - 200) / 730  # 730 candles per year (12h)
    cagr = ((1 + total_return) ** (1 / years) - 1) * 100 if years > 0 else 0
    
    # Max DD
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
    max_dd *= 100
    
    # SL Rate (approximate)
    hold_exits = [t for t in trades if t['type'] == 'HOLD_EXIT']
    losing_exits = [t for t in hold_exits if t['pnl'] < 0]
    sl_rate = len(losing_exits) / len(hold_exits) * 100 if len(hold_exits) > 0 else 0
    
    # Capture ratio (vs buy & hold)
    buy_hold_return = (candles[-1]['close'] - candles[200]['close']) / candles[200]['close']
    capture_ratio = (equity_curve[-1] - BASE_CAPITAL) / BASE_CAPITAL / buy_hold_return if buy_hold_return > 0 else 0
    
    # Yearly returns
    yearly_returns = {}
    for year in range(2021, 2026):
        year_start = None
        year_end = None
        for idx in range(200, len(candles)):
            dt = datetime.fromtimestamp(candles[idx]['open_time'] / 1000)
            if dt.year == year:
                if year_start is None:
                    year_start = idx
                year_end = idx
        
        if year_start and year_end and year_end < len(equity_curve):
            year_return = (equity_curve[year_end] - equity_curve[year_start]) / equity_curve[year_start]
            yearly_returns[year] = year_return * 100
    
    return {
        'cagr': cagr,
        'max_dd': max_dd,
        'sl_rate': sl_rate,
        'capture_ratio': capture_ratio,
        'total_return': total_return * 100,
        'yearly_returns': yearly_returns,
        'num_trades': len(trades)
    }


def main():
    cache = load_cache()
    
    strategies = {
        'coin_specific': 'Coin-Specific Regime (MA50/MA200)',
        'adx': 'ADX-Based (ADX>30 = HOLD)',
        'hybrid': 'Hybrid (ADX>30 + BullScore>=3)'
    }
    
    results = {}
    
    print("=" * 100)
    print("Backtest v14: Regime Detection Strategies")
    print("=" * 100)
    
    for strategy_key, strategy_name in strategies.items():
        print(f"\n{strategy_name}")
        print("-" * 100)
        results[strategy_key] = {}
        
        for coin in COINS:
            result = run_backtest_v14(cache, coin, strategy_key)
            if result:
                results[strategy_key][coin] = result
                print(f"{coin:5s}: CAGR={result['cagr']:6.1f}%, DD={result['max_dd']:5.1f}%, "
                      f"SL={result['sl_rate']:5.1f}%, Capture={result['capture_ratio']:.1f}x")
    
    # Summary table
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"{'Strategy':<40} {'Coin':<5} {'CAGR':>8} {'Max DD':>8} {'SL Rate':>8} {'Capture':>8}")
    print("-" * 100)
    
    # Baselines
    print(f"{'Baseline v11 (Trading only)':<40} {'AVG':<5} {'31.5':>8} {'31.0':>8} {'14.3':>8} {'N/A':>8}")
    print(f"{'HOLD Snowball L1 (BTC regime)':<40} {'AVG':<5} {'19.2':>8} {'38.1':>8} {'2.3':>8} {'3.9':>8}")
    print("-" * 100)
    
    for strategy_key, strategy_name in strategies.items():
        if strategy_key in results:
            coin_results = results[strategy_key]
            avg_cagr = sum(r['cagr'] for r in coin_results.values()) / len(coin_results)
            avg_dd = sum(r['max_dd'] for r in coin_results.values()) / len(coin_results)
            avg_sl = sum(r['sl_rate'] for r in coin_results.values()) / len(coin_results)
            avg_capture = sum(r['capture_ratio'] for r in coin_results.values()) / len(coin_results)
            
            print(f"{strategy_name:<40} {'AVG':<5} {avg_cagr:>8.1f} {avg_dd:>8.1f} {avg_sl:>8.1f} {avg_capture:>8.1f}")
    
    # Detailed yearly returns for best strategy
    print("\n" + "=" * 100)
    print("YEARLY RETURNS (Best Strategy)")
    print("=" * 100)
    
    # Find best strategy
    best_strategy = None
    best_cagr = 0
    for strategy_key, coin_results in results.items():
        avg_cagr = sum(r['cagr'] for r in coin_results.values()) / len(coin_results)
        if avg_cagr > best_cagr:
            best_cagr = avg_cagr
            best_strategy = strategy_key
    
    if best_strategy and best_strategy in results:
        print(f"\n{strategies[best_strategy]}")
        print("-" * 100)
        
        for coin, result in results[best_strategy].items():
            print(f"\n{coin}:")
            for year in sorted(result['yearly_returns'].keys()):
                ret = result['yearly_returns'][year]
                print(f"  {year}: {ret:+7.1f}%")


if __name__ == '__main__':
    main()
