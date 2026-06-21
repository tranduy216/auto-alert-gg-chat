"""
Test: So sánh Bear market với và không có snowball
Chỉ sửa code nếu new config tốt hơn baseline
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_optimal import run_backtest

print("=" * 80)
print("TEST: Bear Market Snowball vs No Snowball")
print("=" * 80)

# Test 1: Baseline (có snowball trong bear)
print("\n1. Baseline: Có snowball trong bear market")
print("-" * 80)
baseline_results = run_backtest(
    bear_snowball=True,
    verbose=False
)

baseline_cagr = sum(r['cagr'] for r in baseline_results.values()) / len(baseline_results)
baseline_dd = sum(r['max_drawdown'] for r in baseline_results.values()) / len(baseline_results)

print(f"Average CAGR: {baseline_cagr:.2f}%")
print(f"Average Max DD: {baseline_dd:.2f}%")
print(f"Risk-Adjusted: {baseline_cagr / baseline_dd if baseline_dd > 0 else 0:.2f}")

print("\nPer-coin:")
for coin, result in baseline_results.items():
    print(f"  {coin}: CAGR={result['cagr']:.2f}%, DD={result['max_drawdown']:.2f}%")

# Test 2: New (không có snowball trong bear)
print("\n2. New: KHÔNG có snowball trong bear market")
print("-" * 80)
new_results = run_backtest(
    bear_snowball=False,
    verbose=False
)

new_cagr = sum(r['cagr'] for r in new_results.values()) / len(new_results)
new_dd = sum(r['max_drawdown'] for r in new_results.values()) / len(new_results)

print(f"Average CAGR: {new_cagr:.2f}%")
print(f"Average Max DD: {new_dd:.2f}%")
print(f"Risk-Adjusted: {new_cagr / new_dd if new_dd > 0 else 0:.2f}")

print("\nPer-coin:")
for coin, result in new_results.items():
    print(f"  {coin}: CAGR={result['cagr']:.2f}%, DD={result['max_drawdown']:.2f}%")

# So sánh
print("\n" + "=" * 80)
print("SO SÁNH")
print("=" * 80)
cagr_diff = new_cagr - baseline_cagr
dd_diff = new_dd - baseline_dd
ra_baseline = baseline_cagr / baseline_dd if baseline_dd > 0 else 0
ra_new = new_cagr / new_dd if new_dd > 0 else 0
ra_diff = ra_new - ra_baseline

print(f"CAGR: {baseline_cagr:.2f}% → {new_cagr:.2f}% ({cagr_diff:+.2f}%)")
print(f"Max DD: {baseline_dd:.2f}% → {new_dd:.2f}% ({dd_diff:+.2f}%)")
print(f"Risk-Adjusted: {ra_baseline:.2f} → {ra_new:.2f} ({ra_diff:+.2f})")

# Kết luận
print("\n" + "=" * 80)
print("KẾT LUẬN")
print("=" * 80)

if cagr_diff > 0 and dd_diff <= 0:
    print("✅ New config TỐT HƠN: CAGR tăng, DD giảm hoặc không đổi")
    print("→ NÊN sửa code để disable snowball trong bear market")
elif cagr_diff > 0 and dd_diff > 0:
    if ra_diff > 0:
        print("✅ New config TỐT HƠN: Risk-adjusted return cao hơn")
        print("→ NÊN sửa code để disable snowball trong bear market")
    else:
        print("⚠️  New config KHÔNG RÕ RÀNG: CAGR tăng nhưng DD cũng tăng")
        print("→ GIỮ NGUYÊN baseline (có snowball trong bear)")
elif cagr_diff < 0 and dd_diff < 0:
    if ra_diff > 0:
        print("✅ New config TỐT HƠN: Risk-adjusted return cao hơn")
        print("→ NÊN sửa code để disable snowball trong bear market")
    else:
        print("⚠️  New config KHÔNG RÕ RÀNG: DD giảm nhưng CAGR cũng giảm")
        print("→ GIỮ NGUYÊN baseline (có snowball trong bear)")
else:
    print("❌ New config TỆ HƠN: CAGR giảm hoặc DD tăng")
    print("→ GIỮ NGUYÊN baseline (có snowball trong bear)")
