#!/usr/bin/env python3
"""
Chi tiết CAGR từng năm cho Risk Management v3 Final (Hybrid Strategy)
So sánh với Buy & Hold để xem gap
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from analyze_cagr_yearly import backtest_coin_yearly, buy_and_hold_yearly

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

# Risk Management v3 Final Config
RISK_CONFIG = {
    'max_position_size': 25000,
    'leverage': 3.5,
    'max_margin': 25000 / 3.5,
    'max_exposure_pct': 0.50,
    'atr_multiplier': 6.0,
    'bull_score_threshold': 3,
    'initial_exposure': 0.10,
    'snowball_levels': [1.25, 1.50],
    'trailing_activation': 0.60,
    'trailing_stop_pct': 0.25,
    'trailing_close_pct': 0.70,
    'partial_tp': [
        (0.30, 0.10),
        (0.50, 0.10),
    ]
}

coins = [
    ('ETHUSDT_4000_1609434000000', 'ETH'),
    ('BNBUSDT_4000_1609434000000', 'BNB'),
    ('TRXUSDT_4000_1609434000000', 'TRX')
]

print("=" * 100)
print("CHI TIẾT CAGR TỪNG NĂM - RISK MANAGEMENT V3 FINAL (HYBRID STRATEGY)")
print("=" * 100)
print(f"\nConfig:")
print(f"  Max position size: ${RISK_CONFIG['max_position_size']:,.0f}")
print(f"  Max exposure per coin: {RISK_CONFIG['max_exposure_pct']*100:.0f}%")
print(f"  Leverage: {RISK_CONFIG['leverage']}x")
print(f"  Initial exposure: {RISK_CONFIG['initial_exposure']*100:.0f}%")
print(f"  ATR multiplier: {RISK_CONFIG['atr_multiplier']}x")
print(f"  Trailing activation: {RISK_CONFIG['trailing_activation']*100:.0f}% ROI")
print("=" * 100)

results = {}
hold_results = {}

for symbol_key, symbol_name in coins:
    print(f"\n{'='*100}")
    print(f"📊 {symbol_name}")
    print(f"{'='*100}")
    
    candles = data[symbol_key]
    
    # Trading results
    trading = backtest_coin_yearly(candles, symbol_name, RISK_CONFIG)
    results[symbol_name] = trading
    
    # Hold results
    hold = buy_and_hold_yearly(candles, symbol_name)
    hold_results[symbol_name] = hold
    
    # Display yearly returns
    print(f"\n{'Year':<8} {'Trading':>12} {'Hold':>12} {'Gap':>12} {'Status':>10}")
    print("-" * 60)
    
    for year in range(2021, 2026):
        trading_ret = trading['yearly_returns'].get(year, 0)
        hold_ret = hold['yearly_returns'].get(year, 0)
        gap = trading_ret - hold_ret
        
        if gap > 0:
            status = "✅ WIN"
        elif gap > -10:
            status = "⚠️ CLOSE"
        else:
            status = "❌ LOSE"
        
        print(f"{year:<8} {trading_ret:>+11.2f}% {hold_ret:>+11.2f}% {gap:>+11.2f}% {status:>10}")
    
    print("-" * 60)
    print(f"{'CAGR':<8} {trading['cagr']:>+11.2f}% {hold['cagr']:>+11.2f}% {trading['cagr'] - hold['cagr']:>+11.2f}%")
    print(f"{'Final':<8} ${trading['final_equity']:>11,.2f} ${hold['last_price']:>11,.2f}")
    print(f"{'Max DD':<8} {trading['max_drawdown']:>11.2f}%")

# Summary
print(f"\n{'='*100}")
print("TỔNG KẾT - SO SÁNH TRADING vs HOLD")
print("=" * 100)

print(f"\n{'Coin':<8} {'Trading CAGR':>14} {'Hold CAGR':>14} {'Gap':>14} {'Max DD':>14} {'Status':>12}")
print("-" * 90)

total_trading_cagr = 0
total_hold_cagr = 0
win_count = 0

for symbol_name in ['ETH', 'BNB', 'TRX']:
    trading = results[symbol_name]
    hold = hold_results[symbol_name]
    gap = trading['cagr'] - hold['cagr']
    
    total_trading_cagr += trading['cagr']
    total_hold_cagr += hold['cagr']
    
    if gap > 0:
        status = "✅ WIN"
        win_count += 1
    elif gap > -10:
        status = "⚠️ CLOSE"
    else:
        status = "❌ LOSE"
    
    print(f"{symbol_name:<8} {trading['cagr']:>+13.2f}% {hold['cagr']:>+13.2f}% {gap:>+13.2f}% {trading['max_drawdown']:>13.2f}% {status:>12}")

print("-" * 90)
avg_trading = total_trading_cagr / 3
avg_hold = total_hold_cagr / 3
avg_gap = avg_trading - avg_hold

print(f"{'Average':<8} {avg_trading:>+13.2f}% {avg_hold:>+13.2f}% {avg_gap:>+13.2f}%")

print(f"\n📊 Kết luận:")
print(f"  - Trading win: {win_count}/3 coins")
print(f"  - Average gap: {avg_gap:+.2f}%")

if avg_gap > 0:
    print(f"  ✅ Trading OUTPERFORMS Hold by {avg_gap:.2f}%")
elif avg_gap > -10:
    print(f"  ⚠️  Trading gần bằng Hold (gap {avg_gap:.2f}%)")
else:
    print(f"  ❌ Trading UNDERPERFORMS Hold by {abs(avg_gap):.2f}%")

# Year-by-year analysis
print(f"\n{'='*100}")
print("PHÂN TÍCH THEO TỪNG NĂM")
print("=" * 100)

for year in range(2021, 2026):
    print(f"\n📅 Năm {year}:")
    
    trading_wins = 0
    total_gap = 0
    
    for symbol_name in ['ETH', 'BNB', 'TRX']:
        trading_ret = results[symbol_name]['yearly_returns'].get(year, 0)
        hold_ret = hold_results[symbol_name]['yearly_returns'].get(year, 0)
        gap = trading_ret - hold_ret
        total_gap += gap
        
        if gap > 0:
            trading_wins += 1
    
    avg_gap_year = total_gap / 3
    
    print(f"  Trading wins: {trading_wins}/3 coins")
    print(f"  Average gap: {avg_gap_year:+.2f}%")
    
    if avg_gap_year > 0:
        print(f"  ✅ Trading OUTPERFORMS Hold")
    else:
        print(f"  ❌ Trading UNDERPERFORMS Hold")

# Bull vs Bear market analysis
print(f"\n{'='*100}")
print("PHÂN TÍCH BULL vs BEAR MARKET")
print("=" * 100)

bull_years = []
bear_years = []

for year in range(2021, 2026):
    # Check if it's bull or bear based on average Hold return
    total_hold = sum(hold_results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
    avg_hold_year = total_hold / 3
    
    if avg_hold_year > 20:
        bull_years.append(year)
    elif avg_hold_year < -20:
        bear_years.append(year)

print(f"\n🐂 Bull Market Years ({len(bull_years)}):")
for year in bull_years:
    total_trading = sum(results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
    total_hold = sum(hold_results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
    avg_trading_year = total_trading / 3
    avg_hold_year = total_hold / 3
    gap = avg_trading_year - avg_hold_year
    
    print(f"  {year}: Trading {avg_trading_year:+.2f}% vs Hold {avg_hold_year:+.2f}% (gap {gap:+.2f}%)")

print(f"\n🐻 Bear Market Years ({len(bear_years)}):")
for year in bear_years:
    total_trading = sum(results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
    total_hold = sum(hold_results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
    avg_trading_year = total_trading / 3
    avg_hold_year = total_hold / 3
    gap = avg_trading_year - avg_hold_year
    
    print(f"  {year}: Trading {avg_trading_year:+.2f}% vs Hold {avg_hold_year:+.2f}% (gap {gap:+.2f}%)")

print(f"\n💡 Kết luận:")
if len(bull_years) > 0 and len(bear_years) > 0:
    bull_gaps = []
    bear_gaps = []
    
    for year in bull_years:
        total_trading = sum(results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
        total_hold = sum(hold_results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
        bull_gaps.append(total_trading/3 - total_hold/3)
    
    for year in bear_years:
        total_trading = sum(results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
        total_hold = sum(hold_results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX'])
        bear_gaps.append(total_trading/3 - total_hold/3)
    
    avg_bull_gap = sum(bull_gaps) / len(bull_gaps)
    avg_bear_gap = sum(bear_gaps) / len(bear_gaps)
    
    print(f"  - Bull market: Trading {'outperforms' if avg_bull_gap > 0 else 'underperforms'} Hold by {abs(avg_bull_gap):.2f}%")
    print(f"  - Bear market: Trading {'outperforms' if avg_bear_gap > 0 else 'underperforms'} Hold by {abs(avg_bear_gap):.2f}%")
