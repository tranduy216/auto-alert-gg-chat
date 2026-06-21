#!/usr/bin/env python3
"""
Phân tích chi tiết Profit/Loss ratio cho RSI<65 + ATR Exit config

Metrics:
- Average win size vs average loss size
- Profit factor (total profit / total loss)
- Win rate
- Risk/reward ratio
- Expectancy per trade
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

def compute_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return 0, 0
    fast_ema = prices[-fast]
    for price in prices[-(fast-1):]:
        fast_ema = price * (2 / (fast + 1)) + fast_ema * (1 - 2 / (fast + 1))
    
    slow_ema = prices[-slow]
    for price in prices[-(slow-1):]:
        slow_ema = price * (2 / (slow + 1)) + slow_ema * (1 - 2 / (slow + 1))
    
    macd_line = fast_ema - slow_ema
    
    # Simplified signal line
    signal_line = macd_line * 0.8  # Approximation
    
    return macd_line, signal_line

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

# Detailed backtest with trade tracking
def backtest_detailed(candles, initial_exposure=0.25, rsi_max=65, exit_strategy='atr_based'):
    """
    Detailed backtest with full trade tracking
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
            
            if exit_strategy == 'ma50_cross':
                if ma20 and ma50 and ma20 < ma50:
                    should_exit = True
                    exit_reason = 'MA20 < MA50'
                    
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
    
    # Calculate detailed metrics
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
    
    # Expectancy per trade
    expectancy = (win_rate/100 * avg_win) - ((100-win_rate)/100 * avg_loss)
    
    # Risk/reward ratio
    risk_reward = avg_win / avg_loss if avg_loss > 0 else float('inf')
    
    return {
        'cagr': cagr,
        'total_return': total_return,
        'max_dd': max_dd,
        'num_trades': len(trades),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'risk_reward': risk_reward,
        'expectancy': expectancy,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'trades': trades,
        'equity': equity
    }

# Run analysis
print("\n" + "="*100)
print("DETAILED PROFIT/LOSS ANALYSIS")
print("="*100)

configs = [
    {
        'name': 'Baseline (v14 Hybrid)',
        'initial_exposure': 0.25,
        'rsi_max': 70,
        'exit_strategy': 'ma50_cross'
    },
    {
        'name': 'RSI<65 + ATR Exit',
        'initial_exposure': 0.25,
        'rsi_max': 65,
        'exit_strategy': 'atr_based'
    },
    {
        'name': 'Exposure 15% + RSI<65 + ATR',
        'initial_exposure': 0.15,
        'rsi_max': 65,
        'exit_strategy': 'atr_based'
    },
]

for config in configs:
    print(f"\n{'='*100}")
    print(f"Config: {config['name']}")
    print(f"{'='*100}")
    
    result = backtest_detailed(
        eth_candles,
        initial_exposure=config['initial_exposure'],
        rsi_max=config['rsi_max'],
        exit_strategy=config['exit_strategy']
    )
    
    print(f"\n📊 OVERALL PERFORMANCE")
    print(f"  CAGR:           {result['cagr']:.2f}%")
    print(f"  Total Return:   {result['total_return']:.2f}%")
    print(f"  Max Drawdown:   {result['max_dd']:.2f}%")
    print(f"  Final Equity:   ${result['equity']:.2f}")
    
    print(f"\n🎯 TRADE STATISTICS")
    print(f"  Total Trades:   {result['num_trades']}")
    print(f"  Win Rate:       {result['win_rate']:.2f}%")
    print(f"  Winning Trades: {len([t for t in result['trades'] if t['is_win']])}")
    print(f"  Losing Trades:  {len([t for t in result['trades'] if not t['is_win']])}")
    
    print(f"\n💰 PROFIT/LOSS ANALYSIS")
    print(f"  Total Wins:     ${result['total_wins']:.2f}")
    print(f"  Total Losses:   ${result['total_losses']:.2f}")
    print(f"  Net Profit:     ${result['total_wins'] - result['total_losses']:.2f}")
    
    print(f"\n📈 AVERAGE TRADE SIZE")
    print(f"  Average Win:    ${result['avg_win']:.2f}")
    print(f"  Average Loss:   ${result['avg_loss']:.2f}")
    print(f"  Win/Loss Ratio: {result['avg_win']/result['avg_loss']:.2f}x" if result['avg_loss'] > 0 else "  Win/Loss Ratio: ∞")
    
    print(f"\n⚖️  QUALITY METRICS")
    print(f"  Profit Factor:  {result['profit_factor']:.2f}x" if result['profit_factor'] != float('inf') else "  Profit Factor:  ∞")
    print(f"  Risk/Reward:    {result['risk_reward']:.2f}x" if result['risk_reward'] != float('inf') else "  Risk/Reward:    ∞")
    print(f"  Expectancy:     ${result['expectancy']:.2f} per trade")
    
    # Interpretation
    print(f"\n💡 INTERPRETATION")
    if result['profit_factor'] > 2:
        print(f"  ✅ Profit Factor {result['profit_factor']:.2f}x > 2 → Excellent (thắng gấp đôi thua)")
    elif result['profit_factor'] > 1.5:
        print(f"  ✅ Profit Factor {result['profit_factor']:.2f}x > 1.5 → Good (thắng nhiều hơn thua)")
    elif result['profit_factor'] > 1:
        print(f"  ⚠️  Profit Factor {result['profit_factor']:.2f}x > 1 → Marginal (thắng ít hơn thua)")
    else:
        print(f"  ❌ Profit Factor {result['profit_factor']:.2f}x < 1 → Poor (thua nhiều hơn thắng)")
    
    if result['expectancy'] > 50:
        print(f"  ✅ Expectancy ${result['expectancy']:.2f} > $50 → Mỗi trade kỳ vọng lãi ${result['expectancy']:.2f}")
    elif result['expectancy'] > 0:
        print(f"  ⚠️  Expectancy ${result['expectancy']:.2f} > $0 → Có lãi nhưng ít")
    else:
        print(f"  ❌ Expectancy ${result['expectancy']:.2f} < $0 → Mỗi trade kỳ vọng lỗ")
    
    # Show sample trades
    print(f"\n📋 SAMPLE TRADES (first 10)")
    print(f"  {'#':<3} {'Entry':<10} {'Exit':<10} {'PnL %':<10} {'PnL $':<10} {'Days':<6} {'Win?':<5}")
    print(f"  {'-'*60}")
    for i, trade in enumerate(result['trades'][:10], 1):
        win_mark = "✅" if trade['is_win'] else "❌"
        print(f"  {i:<3} ${trade['entry_price']:<9.2f} ${trade['exit_price']:<9.2f} {trade['pnl_pct']:>+8.2f}% ${trade['pnl']:>+8.2f} {trade['hold_days']:<6} {win_mark}")

print("\n" + "="*100)
print("RECOMMENDATION")
print("="*100)
print("""
✅ Nếu Profit Factor > 1.5 và Expectancy > $50:
   - Strategy tốt, SL Rate 50% vẫn acceptable
   - Quan trọng là thắng lớn hơn thua

✅ Config tốt nhất: RSI<65 + ATR Exit
   - CAGR: ~45%
   - Profit Factor: cần kiểm tra
   - Expectancy: cần kiểm tra

💡 Nguyên tắc: "Thắng đem về 10 USD, thua mất 3 USD"
   - Win/Loss ratio nên > 3x
   - Profit Factor nên > 2x
   - Expectancy nên > $50 per trade
""")
print("="*100)
