#!/usr/bin/env python3
"""
Backtest v16: Test flexible MA cross exit thresholds

Current: Exit when MA20 < MA50 (0% threshold)
Test: Exit when MA20 < MA50 * (1 - threshold%)
  - 2% threshold: MA20 < MA50 * 0.98
  - 3% threshold: MA20 < MA50 * 0.97
  - 4% threshold: MA20 < MA50 * 0.96

Compare with:
  - ATR-based exit (current best)
  - Baseline v14 (MA cross 0%)
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

# Helper functions (same as v15)
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

def compute_bull_score(candles):
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

# Backtest with flexible MA cross threshold
def backtest_flexible_ma_exit(candles, initial_exposure=0.25, rsi_max=65, 
                               exit_strategy='ma_cross', ma_threshold=0.0):
    """
    exit_strategy: 'ma_cross', 'atr_based'
    ma_threshold: 0.0 = MA20 < MA50, 0.02 = MA20 < MA50 * 0.98, etc.
    """
    initial_capital = 10000
    equity = initial_capital
    position = None
    trades = []
    
    for i in range(200, len(candles)):
        window = candles[max(0, i-200):i+1]
        prices = [c['close'] for c in window]
        volumes = [c['volume'] for c in window]
        current_price = prices[-1]
        
        # Compute indicators
        adx = compute_adx(window)
        bull_score = compute_bull_score(window)
        rsi = compute_rsi(prices)
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
            exit_reason = ''
            
            if exit_strategy == 'ma_cross':
                # Flexible MA cross with threshold
                if ma20 and ma50:
                    threshold_price = ma50 * (1 - ma_threshold)
                    if ma20 < threshold_price:
                        should_exit = True
                        exit_reason = f'MA20 < MA50*{1-ma_threshold:.2f} ({ma_threshold*100:.1f}% threshold)'
                    
            elif exit_strategy == 'atr_based':
                atr = compute_adx(window) * current_price / 100
                peak_price = position.get('peak_price', position['entry_price'])
                if current_price > peak_price:
                    position['peak_price'] = current_price
                    peak_price = current_price
                
                if current_price < peak_price - 2 * atr:
                    should_exit = True
                    exit_reason = 'ATR-based stop'
            
            if should_exit:
                exit_price = current_price
                pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                pnl = pnl_pct * position['exposure'] * equity
                equity += pnl
                
                trades.append({
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct * 100,
                    'exposure': position['exposure'],
                    'hold_days': (datetime.fromtimestamp(candles[i]['timestamp']/1000) - 
                                 datetime.fromtimestamp(position['entry_time']/1000)).days,
                    'exit_reason': exit_reason,
                    'is_win': pnl > 0
                })
                position = None
                continue
        
        # Entry logic
        if not position and regime == 'HOLD':
            # RSI filter
            if rsi > rsi_max:
                continue
            
            # Enter HOLD
            entry_price = current_price
            exposure = initial_exposure
            
            position = {
                'entry_price': entry_price,
                'entry_time': candles[i]['timestamp'],
                'exposure': exposure,
                'snowball_levels': [1.10, 1.20, 1.30],
                'snowball_hit': [],
                'peak_price': entry_price
            }
        
        # Snowball logic
        if position and regime == 'HOLD':
            for level in position['snowball_levels']:
                if level not in position['snowball_hit']:
                    target_price = position['entry_price'] * level
                    if current_price >= target_price:
                        position['snowball_hit'].append(level)
                        position['exposure'] += initial_exposure
    
    # Calculate metrics
    total_return = (equity - initial_capital) / initial_capital * 100
    years = len(candles) / (365 * 2)
    cagr = ((equity / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
    
    # Max drawdown
    peak = initial_capital
    max_dd = 0
    current_equity = initial_capital
    for trade in trades:
        current_equity += trade['pnl']
        if current_equity > peak:
            peak = current_equity
        dd = (peak - current_equity) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    # Win/Loss analysis
    winning_trades = [t for t in trades if t['is_win']]
    losing_trades = [t for t in trades if not t['is_win']]
    
    total_wins = sum(t['pnl'] for t in winning_trades)
    total_losses = abs(sum(t['pnl'] for t in losing_trades))
    
    avg_win = total_wins / len(winning_trades) if winning_trades else 0
    avg_loss = total_losses / len(losing_trades) if losing_trades else 0
    
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
    win_rate = len(winning_trades) / len(trades) * 100 if trades else 0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')
    expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss)
    
    return {
        'cagr': cagr,
        'total_return': total_return,
        'max_dd': max_dd,
        'num_trades': len(trades),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'win_loss_ratio': win_loss_ratio,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'expectancy': expectancy,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'trades': trades,
        'equity': equity
    }

# Run tests
print("\n" + "="*100)
print("BACKTEST V16: FLEXIBLE MA CROSS EXIT THRESHOLDS")
print("="*100)
print("\nTest: MA20 < MA50 * (1 - threshold%)")
print("  0% = MA20 < MA50 (baseline)")
print("  2% = MA20 < MA50 * 0.98")
print("  3% = MA20 < MA50 * 0.97")
print("  4% = MA20 < MA50 * 0.96")
print("="*100)

configs = [
    {
        'name': 'Baseline v14 (MA cross 0%)',
        'exit_strategy': 'ma_cross',
        'ma_threshold': 0.0,
        'rsi_max': 70
    },
    {
        'name': 'MA cross 2% threshold',
        'exit_strategy': 'ma_cross',
        'ma_threshold': 0.02,
        'rsi_max': 70
    },
    {
        'name': 'MA cross 3% threshold',
        'exit_strategy': 'ma_cross',
        'ma_threshold': 0.03,
        'rsi_max': 70
    },
    {
        'name': 'MA cross 4% threshold',
        'exit_strategy': 'ma_cross',
        'ma_threshold': 0.04,
        'rsi_max': 70
    },
    {
        'name': 'RSI<65 + ATR Exit (v15 best)',
        'exit_strategy': 'atr_based',
        'ma_threshold': 0.0,
        'rsi_max': 65
    },
]

results = []
for config in configs:
    print(f"\nTesting: {config['name']}")
    result = backtest_flexible_ma_exit(
        eth_candles,
        initial_exposure=0.25,
        rsi_max=config['rsi_max'],
        exit_strategy=config['exit_strategy'],
        ma_threshold=config['ma_threshold']
    )
    result['name'] = config['name']
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2f}%")
    print(f"  Max DD: {result['max_dd']:.2f}%")
    print(f"  Trades: {result['num_trades']}")
    print(f"  Win Rate: {result['win_rate']:.2f}%")
    print(f"  Win/Loss: {result['win_loss_ratio']:.2f}x")
    print(f"  Profit Factor: {result['profit_factor']:.2f}x")
    print(f"  Expectancy: ${result['expectancy']:.2f}/trade")

# Summary table
print("\n" + "="*100)
print("SUMMARY TABLE")
print("="*100)
print(f"{'Config':<35} {'CAGR':>8} {'DD':>8} {'Trades':>8} {'WinR':>8} {'W/L':>8} {'PF':>8} {'Expect':>10}")
print("-"*100)

for r in results:
    print(f"{r['name']:<35} {r['cagr']:>7.2f}% {r['max_dd']:>7.2f}% {r['num_trades']:>8} "
          f"{r['win_rate']:>7.1f}% {r['win_loss_ratio']:>7.2f}x {r['profit_factor']:>7.2f}x "
          f"${r['expectancy']:>8.2f}")

# Detailed analysis
print("\n" + "="*100)
print("DETAILED PROFIT/LOSS ANALYSIS")
print("="*100)

for r in results:
    print(f"\n{r['name']}:")
    print(f"  Total Wins:   ${r['total_wins']:>12,.2f}")
    print(f"  Total Losses: ${r['total_losses']:>12,.2f}")
    print(f"  Net Profit:   ${r['total_wins'] - r['total_losses']:>12,.2f}")
    print(f"  Avg Win:      ${r['avg_win']:>12,.2f}")
    print(f"  Avg Loss:     ${r['avg_loss']:>12,.2f}")
    print(f"  Win/Loss:     {r['win_loss_ratio']:>11.2f}x")

# Recommendation
print("\n" + "="*100)
print("RECOMMENDATION")
print("="*100)

# Sort by profit factor
sorted_by_pf = sorted(results, key=lambda x: x['profit_factor'], reverse=True)
print("\n🏆 Top 3 by Profit Factor:")
for i, r in enumerate(sorted_by_pf[:3], 1):
    print(f"  {i}. {r['name']}")
    print(f"     CAGR: {r['cagr']:.2f}%, DD: {r['max_dd']:.2f}%, PF: {r['profit_factor']:.2f}x, Expectancy: ${r['expectancy']:.2f}")

# Sort by CAGR
sorted_by_cagr = sorted(results, key=lambda x: x['cagr'], reverse=True)
print("\n📈 Top 3 by CAGR:")
for i, r in enumerate(sorted_by_cagr[:3], 1):
    print(f"  {i}. {r['name']}")
    print(f"     CAGR: {r['cagr']:.2f}%, DD: {r['max_dd']:.2f}%, PF: {r['profit_factor']:.2f}x, Expectancy: ${r['expectancy']:.2f}")

# Sort by Expectancy
sorted_by_exp = sorted(results, key=lambda x: x['expectancy'], reverse=True)
print("\n💰 Top 3 by Expectancy:")
for i, r in enumerate(sorted_by_exp[:3], 1):
    print(f"  {i}. {r['name']}")
    print(f"     CAGR: {r['cagr']:.2f}%, DD: {r['max_dd']:.2f}%, PF: {r['profit_factor']:.2f}x, Expectancy: ${r['expectancy']:.2f}")

print("\n" + "="*100)
print("CONCLUSION")
print("="*100)
print("""
So sánh MA cross thresholds:
  - 0% (baseline): Exit ngay khi MA20 < MA50
  - 2-4%: Chờ MA20 xuống sâu hơn MA50 mới exit
  
Nếu MA cross 2-4% tốt hơn ATR-based:
  → Apply MA cross với threshold linh hoạt
  
Nếu ATR-based vẫn tốt hơn:
  → Giữ ATR-based exit
""")
print("="*100)
