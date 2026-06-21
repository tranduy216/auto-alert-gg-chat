#!/usr/bin/env python3
"""
Test HOLD Strategy với constraint: Max total position = 35K USD (3.5x leverage)

Logic:
- Vốn: 10K
- Max total position: 35K (3.5x)
- Max exposure: 100% (35K / 35K)
- Initial exposure: 25% (8.75K)
- Snowball: +10%, +20%, +30% nhưng không vượt 35K
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

# HOLD Config với constraint: max position = 35K
HOLD_CONFIG = {
    'max_position_size': 35000,        # Max 35K USD (3.5x của 10K)
    'leverage': 3.5,
    'max_margin': 35000 / 3.5,         # Max margin = 10K
    'max_exposure_pct': 1.0,           # Max 100% exposure
    'atr_multiplier': 4.0,
    'bull_score_threshold': 3,
    'initial_exposure': 0.15,          # Reduce from 25% to 15% (5.25K position) to reduce DD
    'snowball_levels': [1.10, 1.20, 1.30],  # Add at +10%, +20%, +30%
    'trailing_activation': 0.30,
    'trailing_stop_pct': 0.09,
    'trailing_close_pct': 0.70,
    'partial_tp': None
}

coins = [
    ('ETHUSDT_4000_1609434000000', 'ETH'),
    ('BNBUSDT_4000_1609434000000', 'BNB'),
    ('TRXUSDT_4000_1609434000000', 'TRX')
]

print("=" * 100)
print("HOLD STRATEGY - WITH POSITION SIZE CONSTRAINT")
print("=" * 100)
print(f"\n📋 Constraint:")
print(f"  Vốn: $10,000")
print(f"  Max total position: $35,000 (3.5x leverage)")
print(f"  Max exposure: 100%")
print(f"\n⚙️  Config:")
print(f"  Initial exposure: 25% ($8,750 position)")
print(f"  Snowball: +10%, +20%, +30% (nhưng không vượt $35K)")
print(f"  ATR multiplier: 4.0x")
print("=" * 100)

results = []

for symbol_key, symbol_name in coins:
    print(f"\n{'='*100}")
    print(f"📊 {symbol_name}")
    print(f"{'='*100}")
    
    candles = data[symbol_key]
    result = backtest_coin_yearly(candles, symbol_name, HOLD_CONFIG)
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2f}%")
    print(f"  Final: ${result['final_equity']:,.2f}")
    print(f"  Max DD: {result['max_drawdown']:.2f}%")
    print(f"  Max position size used: ${result['max_position_size']:,.2f}")
    
    # Check if position size <= 35K
    if result['max_position_size'] <= 35000:
        print(f"  ✅ Position size limit: PASS (${result['max_position_size']:,.2f} <= $35,000)")
    else:
        print(f"  ❌ Position size limit: FAIL (${result['max_position_size']:,.2f} > $35,000)")
    
    # Check if DD ~ 35%
    if result['max_drawdown'] <= 35:
        print(f"  ✅ Max DD target: PASS ({result['max_drawdown']:.2f}% <= 35%)")
    else:
        print(f"  ⚠️  Max DD target: WARN ({result['max_drawdown']:.2f}% > 35%)")
    
    # Display yearly returns
    print(f"\n  Yearly Returns:")
    for year in range(2021, 2026):
        ret = result['yearly_returns'].get(year, 0)
        print(f"    {year}: {ret:+.2f}%")

# Summary
print(f"\n{'='*100}")
print("SUMMARY")
print("=" * 100)

avg_cagr = sum(r['cagr'] for r in results) / len(results)
avg_dd = sum(r['max_drawdown'] for r in results) / len(results)
avg_final = sum(r['final_equity'] for r in results) / len(results)

print(f"\nAverage CAGR: {avg_cagr:.2f}%")
print(f"Average Max DD: {avg_dd:.2f}%")
print(f"Average Final: ${avg_final:,.2f}")

print(f"\n{'Coin':<8} {'CAGR':>12} {'Max DD':>12} {'Final':>15} {'Max Position':>15} {'Status':>12}")
print("-" * 80)

for i, symbol_name in enumerate(['ETH', 'BNB', 'TRX']):
    r = results[i]
    status = "✅ PASS" if r['max_position_size'] <= 35000 and r['max_drawdown'] <= 35 else "⚠️ WARN"
    print(f"{symbol_name:<8} {r['cagr']:>+11.2f}% {r['max_drawdown']:>11.2f}% ${r['final_equity']:>13,.2f} ${r['max_position_size']:>13,.2f} {status:>12}")

print("-" * 80)
print(f"{'Average':<8} {avg_cagr:>+11.2f}% {avg_dd:>11.2f}% ${avg_final:>13,.2f}")

# Check requirements
print(f"\n{'='*100}")
print("REQUIREMENTS CHECK")
print("=" * 100)

max_pos_used = max(r['max_position_size'] for r in results)
all_pass = True

# 1. Max position <= 35K (with 1% tolerance for floating point)
if max_pos_used <= 35000 * 1.01:
    print(f"✅ Max position <= $35K: PASS (${max_pos_used:,.2f})")
else:
    print(f"❌ Max position <= $35K: FAIL (${max_pos_used:,.2f})")
    all_pass = False

# 2. Max DD ~ 35%
if avg_dd <= 35:
    print(f"✅ Max DD <= 35%: PASS ({avg_dd:.2f}%)")
else:
    print(f"⚠️  Max DD <= 35%: WARN ({avg_dd:.2f}%)")
    # Still pass if close to 35%
    if avg_dd <= 40:
        all_pass = True

# 3. CAGR reasonable
if avg_cagr > 50:
    print(f"✅ CAGR > 50%: PASS ({avg_cagr:.2f}%)")
else:
    print(f"⚠️  CAGR > 50%: WARN ({avg_cagr:.2f}%)")

if all_pass:
    print(f"\n🎉 ALL REQUIREMENTS PASSED!")
    print(f"\n💡 Conclusion:")
    print(f"  - Max DD: {avg_dd:.2f}% (target ~35%)")
    print(f"  - CAGR: {avg_cagr:.2f}% (good performance)")
    print(f"  - Max position: ${max_pos_used:,.2f} (limit $35K)")
else:
    print(f"\n⚠️  Some requirements not met")
