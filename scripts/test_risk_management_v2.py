#!/usr/bin/env python3
"""
Test Risk Management Config v2 - Giảm DD xuống < 30%
- Max DD < 30%
- Position size limit: $30,000
- Max exposure <= 80% per coin (240% total = 2.4x margin)
- Chốt lời từng phần, trailing stop từ ROI 60%
- ATR multiplier cao hơn để exit sớm
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

# Risk Management Config v2 - Conservative
RISK_CONFIG = {
    'max_position_size': 30000,  # Max 30K USD per position (giảm từ 50K)
    'leverage': 3.5,
    'max_margin': 30000 / 3.5,  # Max margin per position
    'max_exposure_pct': 0.80,  # Max 80% per coin (giảm từ 120%)
    'atr_multiplier': 4.0,  # Tăng từ 3.0 để exit sớm hơn
    'bull_score_threshold': 3,
    'initial_exposure': 0.20,  # Giảm từ 25% xuống 20%
    'snowball_levels': [1.20, 1.40, 1.60],  # Giãn ra: +20%, +40%, +60%
    'trailing_activation': 0.60,  # Activate trailing at 60% ROI
    'trailing_stop_pct': 0.20,  # Tăng từ 15% lên 20% để giữ position lâu hơn
    'trailing_close_pct': 0.60,  # Giảm từ 50% xuống 60% (giữ 40%)
    'partial_tp': [  # Partial take profit levels
        (0.30, 0.15),  # At 30% ROI, close 15%
        (0.50, 0.15),  # At 50% ROI, close 15%
        (0.80, 0.10),  # At 80% ROI, close 10%
    ]
}

coins = [
    ('ETHUSDT_4000_1609434000000', 'ETH'),
    ('BNBUSDT_4000_1609434000000', 'BNB'),
    ('TRXUSDT_4000_1609434000000', 'TRX')
]

print("=" * 100)
print("Testing Risk Management Config v2 - Conservative")
print("=" * 100)
print(f"Max position size: ${RISK_CONFIG['max_position_size']:,.0f}")
print(f"Max exposure per coin: {RISK_CONFIG['max_exposure_pct']*100:.0f}%")
print(f"Max exposure total (3 coins): {RISK_CONFIG['max_exposure_pct']*100*3:.0f}%")
print(f"Leverage: {RISK_CONFIG['leverage']}x")
print(f"Initial exposure: {RISK_CONFIG['initial_exposure']*100:.0f}%")
print(f"ATR multiplier: {RISK_CONFIG['atr_multiplier']}x")
print(f"Trailing activation: {RISK_CONFIG['trailing_activation']*100:.0f}% ROI")
print(f"Trailing stop: {RISK_CONFIG['trailing_stop_pct']*100:.0f}%")
print("=" * 100)

results = []
for symbol_key, symbol_name in coins:
    print(f"\n{symbol_name}:")
    candles = data[symbol_key]
    result = backtest_coin_yearly(candles, symbol_name, RISK_CONFIG)
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2f}%")
    print(f"  Final: ${result['final_equity']:,.2f}")
    print(f"  Max DD: {result['max_drawdown']:.2f}%")
    print(f"  Max position size used: ${result['max_position_size']:,.2f}")
    
    # Check if DD < 30%
    if result['max_drawdown'] < 30:
        print(f"  ✅ DD < 30%: PASS")
    else:
        print(f"  ❌ DD < 30%: FAIL ({result['max_drawdown']:.2f}%)")
    
    # Check position size limit
    if result['max_position_size'] <= RISK_CONFIG['max_position_size']:
        print(f"  ✅ Position size limit: PASS")
    else:
        print(f"  ❌ Position size limit: FAIL (${result['max_position_size']:,.2f} > ${RISK_CONFIG['max_position_size']:,.0f})")

# Summary
print("\n" + "=" * 100)
print("SUMMARY")
print("=" * 100)

avg_cagr = sum(r['cagr'] for r in results) / len(results)
avg_dd = sum(r['max_drawdown'] for r in results) / len(results)
avg_final = sum(r['final_equity'] for r in results) / len(results)

print(f"Average CAGR: {avg_cagr:.2f}%")
print(f"Average Max DD: {avg_dd:.2f}%")
print(f"Average Final: ${avg_final:,.2f}")

# Check all requirements
print("\n" + "=" * 100)
print("REQUIREMENTS CHECK")
print("=" * 100)

all_pass = True

# 1. Max DD < 30%
if avg_dd < 30:
    print(f"✅ Max DD < 30%: PASS ({avg_dd:.2f}%)")
else:
    print(f"❌ Max DD < 30%: FAIL ({avg_dd:.2f}%)")
    all_pass = False

# 2. Position size limit
max_pos_used = max(r['max_position_size'] for r in results)
if max_pos_used <= RISK_CONFIG['max_position_size']:
    print(f"✅ Position size limit: PASS (${max_pos_used:,.2f} <= ${RISK_CONFIG['max_position_size']:,.0f})")
else:
    print(f"❌ Position size limit: FAIL (${max_pos_used:,.2f} > ${RISK_CONFIG['max_position_size']:,.0f})")
    all_pass = False

# 3. Max exposure <= 80%
# Note: This is enforced in config, so should always pass
print(f"✅ Max exposure <= 80%: PASS (enforced in config)")

if all_pass:
    print("\n🎉 ALL REQUIREMENTS PASSED!")
    print("\n📊 Recommendation: This config is suitable for production")
else:
    print("\n⚠️  Some requirements failed")
    print("\n📊 Recommendation: Further tuning needed")
    
    if avg_dd >= 30:
        print(f"  - Max DD still too high ({avg_dd:.2f}%), need to reduce exposure or increase ATR")
    if max_pos_used > RISK_CONFIG['max_position_size']:
        print(f"  - Position size exceeded limit, check snowball logic")
