#!/usr/bin/env python3
"""
Backtest: Test thêm BNB vào danh sách short
So sánh:
- Baseline: SHORT_ALLOWED = {"ETH", "TRX"}
- Test: SHORT_ALLOWED = {"ETH", "TRX", "BNB"}
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backtest_optimal import backtest_hybrid_strategy, load_cache_data
import json

print("=" * 100)
print("BACKTEST: THÊM BNB VÀO DANH SÁCH SHORT")
print("=" * 100)

# Load cache
cache = load_cache_data()

# Baseline: Chỉ short ETH và TRX
print("\n" + "=" * 100)
print("📊 BASELINE: SHORT_ALLOWED = {ETH, TRX}")
print("=" * 100)

baseline_results = {}
for symbol in ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']:
    print(f"\n🔍 Backtesting {symbol}...")
    candles = cache[symbol]
    result = backtest_hybrid_strategy(
        candles=candles,
        symbol=symbol,
        short_allowed={"ETH", "TRX"}
    )
    baseline_results[symbol] = result
    
    print(f"  CAGR: {result['cagr']:.2f}%")
    print(f"  Max DD: {result['max_drawdown']:.2f}%")
    print(f"  Final Equity: ${result['final_equity']:,.2f}")
    print(f"  Total Trades: {result['total_trades']}")

# Tính trung bình baseline
avg_cagr_baseline = sum(r['cagr'] for r in baseline_results.values()) / len(baseline_results)
avg_dd_baseline = sum(r['max_drawdown'] for r in baseline_results.values()) / len(baseline_results)
avg_equity_baseline = sum(r['final_equity'] for r in baseline_results.values()) / len(baseline_results)

print("\n" + "-" * 100)
print("📊 BASELINE SUMMARY:")
print(f"  Average CAGR: {avg_cagr_baseline:.2f}%")
print(f"  Average Max DD: {avg_dd_baseline:.2f}%")
print(f"  Average Final Equity: ${avg_equity_baseline:,.2f}")

# Test: Thêm BNB vào short
print("\n" + "=" * 100)
print("📊 TEST: SHORT_ALLOWED = {ETH, TRX, BNB}")
print("=" * 100)

test_results = {}
for symbol in ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']:
    print(f"\n🔍 Backtesting {symbol}...")
    candles = cache[symbol]
    result = backtest_hybrid_strategy(
        candles=candles,
        symbol=symbol,
        short_allowed={"ETH", "TRX", "BNB"}
    )
    test_results[symbol] = result
    
    print(f"  CAGR: {result['cagr']:.2f}%")
    print(f"  Max DD: {result['max_drawdown']:.2f}%")
    print(f"  Final Equity: ${result['final_equity']:,.2f}")
    print(f"  Total Trades: {result['total_trades']}")

# Tính trung bình test
avg_cagr_test = sum(r['cagr'] for r in test_results.values()) / len(test_results)
avg_dd_test = sum(r['max_drawdown'] for r in test_results.values()) / len(test_results)
avg_equity_test = sum(r['final_equity'] for r in test_results.values()) / len(test_results)

print("\n" + "-" * 100)
print("📊 TEST SUMMARY:")
print(f"  Average CAGR: {avg_cagr_test:.2f}%")
print(f"  Average Max DD: {avg_dd_test:.2f}%")
print(f"  Average Final Equity: ${avg_equity_test:,.2f}")

# So sánh
print("\n" + "=" * 100)
print("📊 SO SÁNH")
print("=" * 100)

print("\n📈 Chi tiết từng coin:")
print(f"{'Symbol':<12} {'Baseline CAGR':>15} {'Test CAGR':>15} {'Diff':>10} {'Baseline DD':>15} {'Test DD':>15} {'Diff':>10}")
print("-" * 100)

for symbol in ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']:
    b_cagr = baseline_results[symbol]['cagr']
    t_cagr = test_results[symbol]['cagr']
    diff_cagr = t_cagr - b_cagr
    
    b_dd = baseline_results[symbol]['max_drawdown']
    t_dd = test_results[symbol]['max_drawdown']
    diff_dd = t_dd - b_dd
    
    print(f"{symbol:<12} {b_cagr:>14.2f}% {t_cagr:>14.2f}% {diff_cagr:>+9.2f}% {b_dd:>14.2f}% {t_dd:>14.2f}% {diff_dd:>+9.2f}%")

print("-" * 100)
diff_avg_cagr = avg_cagr_test - avg_cagr_baseline
diff_avg_dd = avg_dd_test - avg_dd_baseline
print(f"{'AVERAGE':<12} {avg_cagr_baseline:>14.2f}% {avg_cagr_test:>14.2f}% {diff_avg_cagr:>+9.2f}% {avg_dd_baseline:>14.2f}% {avg_dd_test:>14.2f}% {diff_avg_dd:>+9.2f}%")

# Kết luận
print("\n" + "=" * 100)
print("💡 KẾT LUẬN")
print("=" * 100)

if diff_avg_cagr > 0 and diff_avg_dd <= 0:
    print(f"✅ NÊN THÊM BNB VÀO SHORT")
    print(f"   - CAGR tăng {diff_avg_cagr:+.2f}%")
    print(f"   - Max DD giảm {abs(diff_avg_dd):.2f}% (hoặc không đổi)")
elif diff_avg_cagr > 0 and diff_avg_dd > 0:
    print(f"⚠️  CÂN NHẮC THÊM BNB VÀO SHORT")
    print(f"   - CAGR tăng {diff_avg_cagr:+.2f}% (tốt)")
    print(f"   - Nhưng Max DD tăng {diff_avg_dd:+.2f}% (rủi ro cao hơn)")
elif diff_avg_cagr < 0:
    print(f"❌ KHÔNG NÊN THÊM BNB VÀO SHORT")
    print(f"   - CAGR giảm {diff_avg_cagr:+.2f}% (xấu)")
    print(f"   - Max DD {'giảm' if diff_avg_dd < 0 else 'tăng'} {abs(diff_avg_dd):.2f}%")

print("\n" + "=" * 100)
