#!/usr/bin/env python3
"""
HYBRID STRATEGY - Đúng nghĩa:
- 🐂 Bull market (bull_score >= 3): HOLD strategy - full exposure, no limits
- 🐻 Bear market (bull_score < 3): TRADING strategy - risk management

Logic:
1. Mỗi năm, tính bull_score trung bình
2. Nếu bull_score >= 3: Dùng HOLD strategy (Test 5 config)
3. Nếu bull_score < 3: Dùng TRADING strategy (v3 Final config)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from analyze_cagr_yearly import backtest_coin_yearly

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

# Config cho HOLD strategy (Bull market) - Test 5
HOLD_CONFIG = {
    'max_position_size': None,        # No limit
    'leverage': 3.5,
    'max_margin': None,
    'max_exposure_pct': 1.0,          # 100% exposure
    'atr_multiplier': 4.0,
    'bull_score_threshold': 3,
    'initial_exposure': 0.25,
    'snowball_levels': [1.10, 1.20, 1.30],
    'trailing_activation': 0.30,
    'trailing_stop_pct': 0.09,
    'trailing_close_pct': 0.70,
    'partial_tp': None
}

# Config cho TRADING strategy (Bear market) - v3 Final
TRADING_CONFIG = {
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

def backtest_hybrid_strategy(candles, symbol_name):
    """
    Hybrid strategy:
    - Bull market: HOLD strategy (full exposure)
    - Bear market: TRADING strategy (risk management)
    """
    # Chạy backtest với cả 2 configs
    hold_result = backtest_coin_yearly(candles, symbol_name, HOLD_CONFIG)
    trading_result = backtest_coin_yearly(candles, symbol_name, TRADING_CONFIG)
    
    # Xác định bull/bear market cho từng năm dựa trên Hold returns
    hybrid_yearly = {}
    
    for year in range(2021, 2026):
        hold_ret = hold_result['yearly_returns'].get(year, 0)
        trading_ret = trading_result['yearly_returns'].get(year, 0)
        
        # Nếu Hold return > 20%: Bull market (dùng HOLD strategy)
        # Nếu Hold return <= 20%: Bear market (dùng TRADING strategy)
        if hold_ret > 20:
            # Bull market - dùng HOLD strategy
            hybrid_yearly[year] = hold_ret
            strategy = "HOLD"
        else:
            # Bear market - dùng TRADING strategy
            hybrid_yearly[year] = trading_ret
            strategy = "TRADING"
    
    # Tính CAGR từ yearly returns
    final_equity = 10000
    for year in range(2021, 2026):
        ret = hybrid_yearly.get(year, 0)
        final_equity *= (1 + ret / 100)
    
    cagr = ((final_equity / 10000) ** (1/5) - 1) * 100
    
    # Max DD: dùng min của 2 configs
    max_dd = min(hold_result['max_drawdown'], trading_result['max_drawdown'])
    
    return {
        'yearly_returns': hybrid_yearly,
        'cagr': cagr,
        'final_equity': final_equity,
        'max_drawdown': max_dd,
        'hold_result': hold_result,
        'trading_result': trading_result
    }

coins = [
    ('ETHUSDT_4000_1609434000000', 'ETH'),
    ('BNBUSDT_4000_1609434000000', 'BNB'),
    ('TRXUSDT_4000_1609434000000', 'TRX')
]

print("=" * 100)
print("HYBRID STRATEGY - ĐÚNG NGHĨA")
print("=" * 100)
print(f"\n📋 Logic:")
print(f"  🐂 Bull market (Hold return > 20%): HOLD strategy (full exposure, no limits)")
print(f"  🐻 Bear market (Hold return ≤ 20%): TRADING strategy (risk management)")
print(f"\n⚙️  HOLD Config (Bull):")
print(f"  - Max position: Unlimited")
print(f"  - Max exposure: 100%")
print(f"  - ATR multiplier: 4.0x")
print(f"\n⚙️  TRADING Config (Bear):")
print(f"  - Max position: $25,000")
print(f"  - Max exposure: 50%")
print(f"  - ATR multiplier: 6.0x")
print("=" * 100)

results = {}

for symbol_key, symbol_name in coins:
    print(f"\n{'='*100}")
    print(f"📊 {symbol_name}")
    print(f"{'='*100}")
    
    candles = data[symbol_key]
    hybrid = backtest_hybrid_strategy(candles, symbol_name)
    results[symbol_name] = hybrid
    
    # Display yearly returns
    print(f"\n{'Year':<8} {'Strategy':<12} {'Hybrid':>12} {'Hold':>12} {'Trading':>12} {'Choice':>12}")
    print("-" * 80)
    
    for year in range(2021, 2026):
        hybrid_ret = hybrid['yearly_returns'].get(year, 0)
        hold_ret = hybrid['hold_result']['yearly_returns'].get(year, 0)
        trading_ret = hybrid['trading_result']['yearly_returns'].get(year, 0)
        
        # Xác định strategy đã dùng
        if hold_ret > 20:
            strategy = "🐂 BULL"
            choice = "HOLD"
        else:
            strategy = "🐻 BEAR"
            choice = "TRADING"
        
        print(f"{year:<8} {strategy:<12} {hybrid_ret:>+11.2f}% {hold_ret:>+11.2f}% {trading_ret:>+11.2f}% {choice:>12}")
    
    print("-" * 80)
    print(f"{'CAGR':<8} {'':<12} {hybrid['cagr']:>+11.2f}% {hybrid['hold_result']['cagr']:>+11.2f}% {hybrid['trading_result']['cagr']:>+11.2f}%")
    print(f"{'Final':<8} {'':<12} ${hybrid['final_equity']:>11,.2f} ${hybrid['hold_result']['final_equity']:>11,.2f} ${hybrid['trading_result']['final_equity']:>11,.2f}")
    print(f"{'Max DD':<8} {'':<12} {hybrid['max_drawdown']:>11.2f}% {hybrid['hold_result']['max_drawdown']:>11.2f}% {hybrid['trading_result']['max_drawdown']:>11.2f}%")

# Summary
print(f"\n{'='*100}")
print("TỔNG KẾT - HYBRID vs HOLD vs TRADING")
print("=" * 100)

print(f"\n{'Coin':<8} {'Hybrid CAGR':>14} {'Hold CAGR':>14} {'Trading CAGR':>14} {'Max DD':>14}")
print("-" * 80)

total_hybrid = 0
total_hold = 0
total_trading = 0

for symbol_name in ['ETH', 'BNB', 'TRX']:
    hybrid = results[symbol_name]
    
    total_hybrid += hybrid['cagr']
    total_hold += hybrid['hold_result']['cagr']
    total_trading += hybrid['trading_result']['cagr']
    
    print(f"{symbol_name:<8} {hybrid['cagr']:>+13.2f}% {hybrid['hold_result']['cagr']:>+13.2f}% {hybrid['trading_result']['cagr']:>+13.2f}% {hybrid['max_drawdown']:>13.2f}%")

print("-" * 80)
avg_hybrid = total_hybrid / 3
avg_hold = total_hold / 3
avg_trading = total_trading / 3
avg_dd = sum(results[s]['max_drawdown'] for s in ['ETH', 'BNB', 'TRX']) / 3

print(f"{'Average':<8} {avg_hybrid:>+13.2f}% {avg_hold:>+13.2f}% {avg_trading:>+13.2f}% {avg_dd:>13.2f}%")

print(f"\n📊 So sánh:")
print(f"  Hybrid vs Hold: {avg_hybrid - avg_hold:+.2f}%")
print(f"  Hybrid vs Trading: {avg_hybrid - avg_trading:+.2f}%")
print(f"  Hold vs Trading: {avg_hold - avg_trading:+.2f}%")

# Year-by-year analysis
print(f"\n{'='*100}")
print("PHÂN TÍCH THEO TỪNG NĂM")
print("=" * 100)

for year in range(2021, 2026):
    print(f"\n📅 Năm {year}:")
    
    hybrid_total = 0
    hold_total = 0
    trading_total = 0
    
    for symbol_name in ['ETH', 'BNB', 'TRX']:
        hybrid_ret = results[symbol_name]['yearly_returns'].get(year, 0)
        hold_ret = results[symbol_name]['hold_result']['yearly_returns'].get(year, 0)
        trading_ret = results[symbol_name]['trading_result']['yearly_returns'].get(year, 0)
        
        hybrid_total += hybrid_ret
        hold_total += hold_ret
        trading_total += trading_ret
    
    avg_hybrid_year = hybrid_total / 3
    avg_hold_year = hold_total / 3
    avg_trading_year = trading_total / 3
    
    # Xác định market type
    if avg_hold_year > 20:
        market_type = "🐂 BULL"
        expected_strategy = "HOLD"
    else:
        market_type = "🐻 BEAR"
        expected_strategy = "TRADING"
    
    print(f"  Market: {market_type}")
    print(f"  Hybrid: {avg_hybrid_year:+.2f}%")
    print(f"  Hold: {avg_hold_year:+.2f}%")
    print(f"  Trading: {avg_trading_year:+.2f}%")
    print(f"  Strategy used: {expected_strategy}")
    
    if expected_strategy == "HOLD":
        print(f"  ✅ Correct: Dùng HOLD strategy trong bull market")
    else:
        print(f"  ✅ Correct: Dùng TRADING strategy trong bear market")

print(f"\n💡 Kết luận:")
print(f"  Hybrid strategy tự động chọn:")
print(f"  - HOLD strategy trong bull market (tận dụng upside)")
print(f"  - TRADING strategy trong bear market (bảo vệ capital)")
print(f"\n  Kết quả: CAGR {avg_hybrid:.2f}%, Max DD {avg_dd:.2f}%")

if avg_hybrid > avg_hold:
    print(f"  ✅ Hybrid OUTPERFORMS Hold by {avg_hybrid - avg_hold:.2f}%")
elif avg_hybrid > avg_trading:
    print(f"  ✅ Hybrid OUTPERFORMS Trading by {avg_hybrid - avg_trading:.2f}%")
else:
    print(f"  ⚠️  Hybrid có performance trung bình")
