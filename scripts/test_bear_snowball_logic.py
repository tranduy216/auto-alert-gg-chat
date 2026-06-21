"""
Logic test: So sánh Bear market với và không có snowball
Không chạy backtest, chỉ test logic
"""

print("=" * 80)
print("LOGIC TEST: Bear Market Snowball")
print("=" * 80)

# Simulate bear market scenarios
print("\n📊 SCENARIO 1: Bear market VỚI snowball")
print("-" * 80)

# Giả sử bear market kéo dài 10 candles
# Price: 100 → 90 → 85 → 80 → 75 → 70 → 75 → 80 → 85 → 90
prices_with_snowball = [100, 90, 85, 80, 75, 70, 75, 80, 85, 90]

capital = 10000
position = None
trades = []

for i, price in enumerate(prices_with_snowball):
    print(f"\nCandle {i+1}: Price = ${price}")
    
    # Check exit
    if position:
        pnl_pct = (price - position['entry']) / position['entry'] * 100
        print(f"  Position: Entry ${position['entry']}, Size ${position['size']:.2f}")
        print(f"  PnL: {pnl_pct:+.2f}%")
        
        # Exit conditions
        if pnl_pct <= -8:  # Stop loss 8%
            pnl = (price - position['entry']) / position['entry'] * position['size']
            capital += pnl
            trades.append({'pnl_pct': pnl_pct, 'pnl': pnl})
            print(f"  ❌ EXIT (SL): PnL ${pnl:+.2f}, Capital ${capital:.2f}")
            position = None
        elif pnl_pct >= 15:  # Take profit 15%
            pnl = (price - position['entry']) / position['entry'] * position['size']
            capital += pnl
            trades.append({'pnl_pct': pnl_pct, 'pnl': pnl})
            print(f"  ✅ EXIT (TP): PnL ${pnl:+.2f}, Capital ${capital:.2f}")
            position = None
        else:
            # Snowball: nếu price giảm 10% từ entry, thêm position
            if not position.get('snowball_added') and pnl_pct <= -10:
                snowball_size = position['size'] * 0.5  # 50% of original
                position['size'] += snowball_size
                position['entry'] = (position['entry'] + price) / 2  # Average price
                position['snowball_added'] = True
                print(f"  📈 SNOWBALL: Added ${snowball_size:.2f}, New entry ${position['entry']:.2f}")
    else:
        # Entry at candle 2 (price drop to 90)
        if i == 1:
            size = capital * 0.1  # 10% exposure
            position = {
                'entry': price,
                'size': size,
                'snowball_added': False
            }
            capital -= size
            print(f"  📥 ENTRY: ${price}, Size ${size:.2f}, Capital ${capital:.2f}")

print(f"\nFinal Capital (with snowball): ${capital:.2f}")
print(f"Trades: {len(trades)}")

# SCENARIO 2: Bear market KHÔNG có snowball
print("\n\n📊 SCENARIO 2: Bear market KHÔNG có snowball")
print("-" * 80)

capital_no_snowball = 10000
position = None
trades = []

for i, price in enumerate(prices_with_snowball):
    print(f"\nCandle {i+1}: Price = ${price}")
    
    # Check exit
    if position:
        pnl_pct = (price - position['entry']) / position['entry'] * 100
        print(f"  Position: Entry ${position['entry']}, Size ${position['size']:.2f}")
        print(f"  PnL: {pnl_pct:+.2f}%")
        
        # Exit conditions
        if pnl_pct <= -8:  # Stop loss 8%
            pnl = (price - position['entry']) / position['entry'] * position['size']
            capital_no_snowball += pnl
            trades.append({'pnl_pct': pnl_pct, 'pnl': pnl})
            print(f"  ❌ EXIT (SL): PnL ${pnl:+.2f}, Capital ${capital_no_snowball:.2f}")
            position = None
        elif pnl_pct >= 15:  # Take profit 15%
            pnl = (price - position['entry']) / position['entry'] * position['size']
            capital_no_snowball += pnl
            trades.append({'pnl_pct': pnl_pct, 'pnl': pnl})
            print(f"  ✅ EXIT (TP): PnL ${pnl:+.2f}, Capital ${capital_no_snowball:.2f}")
            position = None
        # NO SNOWBALL
    else:
        # Entry at candle 2 (price drop to 90)
        if i == 1:
            size = capital_no_snowball * 0.1  # 10% exposure
            position = {
                'entry': price,
                'size': size
            }
            capital_no_snowball -= size
            print(f"  📥 ENTRY: ${price}, Size ${size:.2f}, Capital ${capital_no_snowball:.2f}")

print(f"\nFinal Capital (no snowball): ${capital_no_snowball:.2f}")
print(f"Trades: {len(trades)}")

# SO SÁNH
print("\n" + "=" * 80)
print("SO SÁNH")
print("=" * 80)
print(f"Với snowball:    ${capital:.2f}")
print(f"Không snowball:  ${capital_no_snowball:.2f}")
print(f"Chênh lệch:      ${capital - capital_no_snowball:+.2f}")

if capital > capital_no_snowball:
    print("\n✅ Snowball TỐT HƠN trong scenario này")
    print("→ GIỮ NGUYÊN snowball trong bear market")
else:
    print("\n❌ Snowball TỆ HƠN trong scenario này")
    print("→ NÊN disable snowball trong bear market")

print("\n" + "=" * 80)
print("PHÂN TÍCH")
print("=" * 80)
print("""
Trong bear market:
- Price giảm liên tục: 100 → 70 (-30%)
- Với snowball: Thêm position khi price giảm → average entry thấp hơn
- Nhưng nếu price tiếp tục giảm → loss lớn hơn (position size lớn hơn)

Kết luận:
- Snowball có lợi nếu price phục hồi sớm
- Snowball có hại nếu price tiếp tục giảm sâu
- Trong bear market thực tế, price thường giảm sâu và kéo dài
- → Risk của snowball cao hơn benefit
""")
