"""
Quick test: So sánh Bear market với và không có snowball (chỉ test ETH)
"""
import sys
import json
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from backtest_optimal import run_backtest

print("=" * 80)
print("QUICK TEST: Bear Market Snowball (ETH only)")
print("=" * 80)

# Load ETH data
cache_path = Path(__file__).parent.parent / 'scripts' / '_klines_12h_5y.json'
with open(cache_path) as f:
    data = json.load(f)

eth_candles = data['ETHUSDT']
print(f"Loaded {len(eth_candles)} candles for ETH")

# Test 1: Baseline (có snowball trong bear)
print("\n1. Baseline: Có snowball trong bear market")
print("-" * 80)

# Import necessary functions
from crypto_trading import (
    sma, compute_rsi, compute_macd, compute_bollinger_bands,
    compute_atr, get_entry_signal, get_exit_signal
)

# Simple backtest function
def simple_backtest(candles, bear_snowball=True):
    """Simple backtest for ETH"""
    initial_capital = 10000
    capital = initial_capital
    position = None
    trades = []
    max_dd = 0
    peak = initial_capital
    
    for i in range(200, len(candles)):
        # Get price
        price = candles[i]['close']
        
        # Check exit
        if position:
            pnl_pct = (price - position['entry']) / position['entry'] * 100
            
            # Exit conditions
            exit_signal = False
            
            # Stop loss
            if pnl_pct <= -position['sl']:
                exit_signal = True
            
            # Take profit
            elif pnl_pct >= position['tp']:
                exit_signal = True
            
            # Trailing stop (simple)
            elif pnl_pct > 10 and price < position['highest'] * 0.95:
                exit_signal = True
            
            # Update highest
            if price > position['highest']:
                position['highest'] = price
            
            if exit_signal:
                # Close position
                pnl = (price - position['entry']) / position['entry'] * position['size']
                capital += pnl
                trades.append({
                    'entry': position['entry'],
                    'exit': price,
                    'pnl_pct': pnl_pct,
                    'pnl': pnl
                })
                position = None
                
                # Update max DD
                if capital > peak:
                    peak = capital
                dd = (peak - capital) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        
        # Check entry
        else:
            # Simple entry: RSI < 30 and price > MA50
            if i >= 50:
                prices = [c['close'] for c in candles[i-50:i+1]]
                ma50 = sum(prices) / 50
                rsi = compute_rsi(prices)
                
                if rsi < 30 and price > ma50:
                    # Entry
                    size = capital * 0.1  # 10% exposure
                    position = {
                        'entry': price,
                        'size': size,
                        'sl': 8.0,  # 8% stop loss
                        'tp': 40.0,  # 40% take profit
                        'highest': price
                    }
                    capital -= size
    
    # Calculate CAGR
    years = (len(candles) - 200) / (365 * 2)  # 12h candles
    cagr = ((capital / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
    
    return {
        'cagr': cagr,
        'max_drawdown': max_dd,
        'final_capital': capital,
        'num_trades': len(trades)
    }

# Run tests
print("\nTest 1: Với snowball trong bear market")
result1 = simple_backtest(eth_candles, bear_snowball=True)
print(f"CAGR: {result1['cagr']:.2f}%")
print(f"Max DD: {result1['max_drawdown']:.2f}%")
print(f"Final Capital: ${result1['final_capital']:.2f}")
print(f"Trades: {result1['num_trades']}")

print("\nTest 2: KHÔNG có snowball trong bear market")
result2 = simple_backtest(eth_candles, bear_snowball=False)
print(f"CAGR: {result2['cagr']:.2f}%")
print(f"Max DD: {result2['max_drawdown']:.2f}%")
print(f"Final Capital: ${result2['final_capital']:.2f}")
print(f"Trades: {result2['num_trades']}")

# So sánh
print("\n" + "=" * 80)
print("SO SÁNH")
print("=" * 80)
cagr_diff = result2['cagr'] - result1['cagr']
dd_diff = result2['max_drawdown'] - result1['max_drawdown']

print(f"CAGR: {result1['cagr']:.2f}% → {result2['cagr']:.2f}% ({cagr_diff:+.2f}%)")
print(f"Max DD: {result1['max_drawdown']:.2f}% → {result2['max_drawdown']:.2f}% ({dd_diff:+.2f}%)")

# Kết luận
print("\n" + "=" * 80)
print("KẾT LUẬN")
print("=" * 80)

if cagr_diff > 0 and dd_diff <= 0:
    print("✅ New config TỐT HƠN: CAGR tăng, DD giảm hoặc không đổi")
    print("→ NÊN sửa code để disable snowball trong bear market")
elif cagr_diff > 0 and dd_diff > 0:
    ra1 = result1['cagr'] / result1['max_drawdown'] if result1['max_drawdown'] > 0 else 0
    ra2 = result2['cagr'] / result2['max_drawdown'] if result2['max_drawdown'] > 0 else 0
    if ra2 > ra1:
        print("✅ New config TỐT HƠN: Risk-adjusted return cao hơn")
        print("→ NÊN sửa code để disable snowball trong bear market")
    else:
        print("⚠️  New config KHÔNG RÕ RÀNG: CAGR tăng nhưng DD cũng tăng")
        print("→ GIỮ NGUYÊN baseline (có snowball trong bear)")
else:
    print("❌ New config TỆ HƠN: CAGR giảm hoặc DD tăng")
    print("→ GIỮ NGUYÊN baseline (có snowball trong bear)")
