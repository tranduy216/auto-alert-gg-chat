#!/usr/bin/env python3
"""
Validation script - Tính toán manual để kiểm tra logic

Mục tiêu: So sánh kết quả backtest với tính toán manual cho 1-2 trades cụ thể
"""

import json
from pathlib import Path
from datetime import datetime

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

def manual_calculation_example():
    """
    Tính toán manual cho 1 trade đơn giản
    
    Scenario:
    - Initial capital: $10,000
    - Entry: 25% exposure = $2,500
    - Leverage: 3.5x
    - Position size: $2,500 * 3.5 = $8,750
    - Entry price: $100
    - Exit price: $130 (+30%)
    
    Expected PnL:
    - PnL % = (130 - 100) / 100 = 0.30 (30%)
    - PnL $ = 0.30 * $2,500 * 3.5 = $2,625
    - Final equity = $10,000 + $2,625 = $12,625
    """
    initial_capital = 10000
    exposure = 0.25  # 25%
    leverage = 3.5
    entry_price = 100
    exit_price = 130  # +30%
    
    # Calculate PnL
    pnl_pct = (exit_price - entry_price) / entry_price
    position_equity = initial_capital * exposure  # $2,500
    pnl = pnl_pct * position_equity * leverage  # 0.30 * 2500 * 3.5 = $2,625
    final_equity = initial_capital + pnl
    
    print("="*80)
    print("MANUAL CALCULATION - Single Trade Example")
    print("="*80)
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Exposure: {exposure*100:.0f}% = ${position_equity:,.2f}")
    print(f"Leverage: {leverage}x")
    print(f"Position Size: ${position_equity * leverage:,.2f}")
    print(f"Entry Price: ${entry_price}")
    print(f"Exit Price: ${exit_price} (+{pnl_pct*100:.0f}%)")
    print(f"PnL %: {pnl_pct*100:.2f}%")
    print(f"PnL $: ${pnl:,.2f}")
    print(f"Final Equity: ${final_equity:,.2f}")
    print(f"Return: {(final_equity/initial_capital - 1)*100:.2f}%")
    print()
    
    return final_equity

def manual_trailing_stop_example():
    """
    Tính toán manual cho trailing stop logic
    
    Scenario:
    - Initial capital: $10,000
    - Entry: 25% exposure = $2,500
    - Leverage: 3.5x
    - Entry price: $100
    - Price tăng 40% → $140
    - Trailing stop activated at +30% → Close 70%
    - Price tiếp tục tăng 50% → $150
    - Trailing stop hit (9% from peak) → Exit at $136.50
    
    Expected:
    Step 1: Close 70% at +30%
    - PnL 70% = 0.30 * ($2,500 * 0.70) * 3.5 = $1,837.50
    - Exposure còn lại = $2,500 * 0.30 = $750
    
    Step 2: Close 30% at trailing stop
    - Exit price = $150 * 0.91 = $136.50
    - PnL % = (136.50 - 100) / 100 = 0.365 (36.5%)
    - PnL 30% = 0.365 * $750 * 3.5 = $958.13
    
    Total PnL = $1,837.50 + $958.13 = $2,795.63
    Final equity = $10,000 + $2,795.63 = $12,795.63
    """
    initial_capital = 10000
    exposure = 0.25
    leverage = 3.5
    entry_price = 100
    
    print("="*80)
    print("MANUAL CALCULATION - Trailing Stop Example")
    print("="*80)
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Exposure: {exposure*100:.0f}% = ${initial_capital * exposure:,.2f}")
    print(f"Leverage: {leverage}x")
    print(f"Entry Price: ${entry_price}")
    print()
    
    # Step 1: Price tăng 30% → Trigger trailing stop
    price_at_trigger = entry_price * 1.30
    pnl_pct_1 = 0.30
    exposure_70 = initial_capital * exposure * 0.70  # 70% of $2,500 = $1,750
    pnl_1 = pnl_pct_1 * exposure_70 * leverage
    
    print(f"Step 1: Price +{pnl_pct_1*100:.0f}% → ${price_at_trigger}")
    print(f"  Close 70% position")
    print(f"  Exposure 70%: ${exposure_70:,.2f}")
    print(f"  PnL 70%: ${pnl_1:,.2f}")
    print()
    
    # Step 2: Price tiếp tục tăng 50% → $150
    peak_price = entry_price * 1.50
    trailing_stop_pct = 0.09
    exit_price = peak_price * (1 - trailing_stop_pct)
    
    pnl_pct_2 = (exit_price - entry_price) / entry_price
    exposure_30 = initial_capital * exposure * 0.30  # 30% of $2,500 = $750
    pnl_2 = pnl_pct_2 * exposure_30 * leverage
    
    print(f"Step 2: Price tăng tiếp → Peak ${peak_price}")
    print(f"  Trailing stop: 9% from peak = ${exit_price:.2f}")
    print(f"  Close 30% còn lại")
    print(f"  Exit price: ${exit_price:.2f} (+{pnl_pct_2*100:.2f}%)")
    print(f"  Exposure 30%: ${exposure_30:,.2f}")
    print(f"  PnL 30%: ${pnl_2:,.2f}")
    print()
    
    total_pnl = pnl_1 + pnl_2
    final_equity = initial_capital + total_pnl
    
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"PnL 70%: ${pnl_1:,.2f}")
    print(f"PnL 30%: ${pnl_2:,.2f}")
    print(f"Total PnL: ${total_pnl:,.2f}")
    print(f"Final Equity: ${final_equity:,.2f}")
    print(f"Return: {(final_equity/initial_capital - 1)*100:.2f}%")
    print()
    
    return final_equity

def check_backtest_logic():
    """
    Kiểm tra logic trong backtest code
    
    Vấn đề tiềm ẩn:
    1. Leverage 3.5x được áp dụng ở đâu?
    2. Snowball có tăng exposure không giới hạn không?
    3. Trailing stop có dùng position_equity đúng không?
    """
    print("="*80)
    print("CHECK BACKTEST LOGIC")
    print("="*80)
    print()
    print("Đọc file analyze_cagr_yearly.py để kiểm tra...")
    print()
    
    # Đọc file
    with open("scripts/analyze_cagr_yearly.py", "r") as f:
        content = f.read()
    
    # Kiểm tra các pattern nguy hiểm
    issues = []
    
    # Issue 1: Check nếu leverage được áp dụng nhiều lần
    if content.count("* 3.5") > 10:
        issues.append("⚠️  Leverage 3.5x được áp dụng quá nhiều lần (>10)")
    
    # Issue 2: Check nếu snowball tăng exposure không giới hạn
    if "position['exposure'] +=" in content and "max_exposure" not in content:
        issues.append("⚠️  Snowball tăng exposure không có giới hạn max")
    
    # Issue 3: Check nếu position_equity được dùng đúng
    if "position['position_equity']" not in content:
        issues.append("❌ Không dùng position_equity - có thể gây compounding error")
    
    # Issue 4: Check nếu có update equity trong middle of trade
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'equity +=' in line and 'position' in lines[max(0, i-5):i+1]:
            # Kiểm tra xem có update equity khi close partial position không
            if 'close_pct' in lines[max(0, i-5):i+1] or 'trailing' in lines[max(0, i-5):i+1]:
                issues.append(f"⚠️  Line {i+1}: Update equity khi close partial - có thể gây compounding")
    
    if issues:
        print("ISSUES FOUND:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("✅ No obvious issues found")
    
    print()
    
    return issues

def main():
    print()
    print("="*80)
    print("BACKTEST VALIDATION SCRIPT")
    print("="*80)
    print()
    
    # Manual calculations
    manual_calculation_example()
    manual_trailing_stop_example()
    
    # Check backtest logic
    issues = check_backtest_logic()
    
    # Summary
    print("="*80)
    print("CONCLUSION")
    print("="*80)
    print()
    print("Manual calculation cho thấy:")
    print("  - Single trade +30%: Return = 26.25%")
    print("  - Trailing stop: Return = 27.96%")
    print()
    print("Backtest result: 283% CAGR (5 years)")
    print()
    print("Nếu average trade return = 27%, thì sau 5 năm:")
    print("  - 10 trades/year = 50 trades total")
    print("  - Compound: (1.27)^50 = ???")
    print()
    print("⚠️  283% CAGR có vẻ KHÔNG THỰC TẾ!")
    print()
    print("Recommendation:")
    print("  1. Review lại logic leverage application")
    print("  2. Kiểm tra snowball exposure limit")
    print("  3. Validate với manual calculation cho 5-10 trades thực tế")
    print("  4. So sánh với production code (crypto_trading.py)")
    print()

if __name__ == "__main__":
    main()
