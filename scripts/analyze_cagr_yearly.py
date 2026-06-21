#!/usr/bin/env python3
"""
Phân tích CAGR từng coin theo năm và so sánh Trading vs Hold

Mục tiêu:
1. Thống kê CAGR từng coin (ETH, BNB, TRX) qua từng năm
2. Tính CAGR trung bình 5 năm
3. So sánh với Buy & Hold returns
4. Kiểm tra gap trong bull market years
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from statistics import mean

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

# Helper functions
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

    # Use Wilder's smoothing instead of simple average
    atr = tr_list[0]
    for tr in tr_list[1:]:
        atr = (atr * (period - 1) + tr) / period
    
    plus_di = plus_dm[0]
    for dm in plus_dm[1:]:
        plus_di = (plus_di * (period - 1) + dm) / period
    
    minus_di = minus_dm[0]
    for dm in minus_dm[1:]:
        minus_di = (minus_di * (period - 1) + dm) / period

    if atr == 0:
        return 25

    plus_di_pct = 100 * plus_di / atr
    minus_di_pct = 100 * minus_di / atr

    di_sum = plus_di_pct + minus_di_pct
    if di_sum == 0:
        return 25

    dx = 100 * abs(plus_di_pct - minus_di_pct) / di_sum
    return dx

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

def backtest_coin_yearly(candles, symbol, initial_exposure=0.25, rsi_max=65):
    """Backtest với ATR exit, trả về yearly returns"""
    initial_capital = 10000
    equity = initial_capital
    position = None
    
    # Margin constraints
    max_position_size = 10000  # Max position size in USD (including leverage)
    leverage = 3.5
    max_margin = max_position_size / leverage  # Max margin = 2,857 USD
    max_exposure_pct = max_margin / initial_capital  # Max exposure = 28.57%
    
    trades = []  # Track all trades
    exits = 0  # Count exits
    
    # Track max drawdown
    peak_equity = equity
    max_drawdown = 0
    
    # Track max position size
    max_position_size_actual = 0

    # Dynamic parameters per coin
    coin_params = {
        'ETH': {'rsi_max': 70, 'atr_multiplier': 2.5},  # Looser (high volatility)
        'BNB': {'rsi_max': 65, 'atr_multiplier': 2.0},  # Tighter (medium volatility)
        'TRX': {'rsi_max': 65, 'atr_multiplier': 2.0},  # Tighter (medium volatility)
    }

    params = coin_params.get(symbol, {'rsi_max': 65, 'atr_multiplier': 2.0})
    rsi_max = params['rsi_max']
    atr_multiplier = params['atr_multiplier']

    yearly_equity = {2020: initial_capital}
    current_year = 2020
    
    for i in range(200, len(candles)):
        window = candles[max(0, i-200):i+1]
        prices = [c['close'] for c in window]
        volumes = [c['volume'] for c in window]
        current_price = prices[-1]
        
        # Track year
        candle_date = datetime.fromtimestamp(candles[i]['open_time'] / 1000)
        if candle_date.year != current_year:
            # Calculate unrealized PnL if there's an open position
            if position:
                unrealized_pnl_pct = (current_price - position['entry_price']) / position['entry_price']
                unrealized_pnl = unrealized_pnl_pct * position['exposure'] * position['position_equity'] * leverage
                yearly_equity[candle_date.year] = equity + unrealized_pnl
            else:
                yearly_equity[candle_date.year] = equity
            current_year = candle_date.year
        
        # Compute indicators
        adx = compute_adx(window)
        bull_score = compute_bull_score(window)
        rsi = compute_rsi(prices)
        ma50 = compute_sma(prices, 50)
        ma20 = compute_sma(prices, 20)
        
        # Determine regime
        if adx > 30 and bull_score >= 3:
            regime = 'HOLD'
        else:
            regime = 'TRADING'
        
        # Exit logic
        if position:
            current_pnl_pct = (current_price - position['entry_price']) / position['entry_price']
            peak_price = position.get('peak_price', position['entry_price'])
            
            # Check for liquidation (at -28.6% drop = 1/3.5 leverage)
            if current_pnl_pct < -0.286:
                # Lose entire position
                loss = position['exposure'] * position['position_equity']
                equity -= loss
                
                trades.append({
                    'type': 'liquidation',
                    'entry': position['entry_price'],
                    'exit': current_price,
                    'pnl_pct': -100,
                    'pnl': -loss,
                    'exposure': position['exposure'],
                    'equity': equity
                })
                
                position = None
                exits += 1
                continue

            # Update peak
            if current_price > peak_price:
                position['peak_price'] = current_price
                peak_price = current_price

            # Trailing stop trigger: profit > 30%
            if current_pnl_pct > 0.30 and not position.get('trailing_activated'):
                # Close 70% position
                close_pct = 0.70
                close_exposure = position['exposure'] * close_pct
                pnl = current_pnl_pct * close_exposure * position['position_equity'] * leverage
                equity += pnl
                
                # Update max drawdown
                if equity > peak_equity:
                    peak_equity = equity
                drawdown = (peak_equity - equity) / peak_equity * 100
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                
                position['exposure'] = position['exposure'] * (1 - close_pct)  # Keep 30%
                position['trailing_activated'] = True
                position['trailing_stop_pct'] = 0.09  # 9% from peak (coin price, not leveraged)

            # Trailing stop exit
            if position.get('trailing_activated'):
                trailing_stop_price = peak_price * (1 - position['trailing_stop_pct'])
                if current_price < trailing_stop_price:
                    exit_price = current_price
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                    pnl = pnl_pct * position['exposure'] * position['position_equity'] * leverage
                    equity += pnl
                    
                    # Update max drawdown
                    if equity > peak_equity:
                        peak_equity = equity
                    drawdown = (peak_equity - equity) / peak_equity * 100
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                    
                    position = None
                    continue

            # ATR-based exit (for non-trailing part)
            if not position.get('trailing_activated'):
                atr = compute_adx(window) * current_price / 100
                if current_price < peak_price - atr_multiplier * atr:
                    exit_price = current_price
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                    pnl = pnl_pct * position['exposure'] * position['position_equity'] * leverage
                    equity += pnl
                    
                    # Update max drawdown
                    if equity > peak_equity:
                        peak_equity = equity
                    drawdown = (peak_equity - equity) / peak_equity * 100
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                    
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
            
            # Check if position size exceeds max
            position_size = exposure * equity * leverage
            if position_size > max_position_size:
                # Reduce exposure to fit max position size
                exposure = max_margin / equity
            
            # Update max position size
            if position_size > max_position_size_actual:
                max_position_size_actual = position_size
            
            position = {
                'entry_price': entry_price,
                'exposure': exposure,
                'position_equity': equity,  # Track equity at entry for correct PnL calculation
                'snowball_levels': [1.10],  # Only 1 snowball: +10%
                'snowball_hit': [],
                'peak_price': entry_price,
                'max_exposure': max_exposure_pct  # Max exposure based on position size constraint
            }
        
        # Snowball logic
        if position and regime == 'HOLD':
            for level in position['snowball_levels']:
                if level not in position['snowball_hit']:
                    target_price = position['entry_price'] * level
                    if current_price >= target_price:
                        # Check max exposure based on position size constraint
                        new_exposure = position['exposure'] + initial_exposure
                        new_position_size = new_exposure * position['position_equity'] * leverage
                        
                        if new_position_size <= max_position_size:
                            position['snowball_hit'].append(level)
                            position['exposure'] = new_exposure
    
    # Close any remaining position
    if position:
        final_price = candles[-1]['close']
        pnl_pct = (final_price - position['entry_price']) / position['entry_price']
        pnl = pnl_pct * position['exposure'] * position['position_equity'] * leverage
        equity += pnl
        
        # Update max drawdown
        if equity > peak_equity:
            peak_equity = equity
        drawdown = (peak_equity - equity) / peak_equity * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    yearly_equity[2025] = equity
    
    # Calculate yearly returns
    yearly_returns = {}
    for year in range(2021, 2026):
        if year in yearly_equity and (year-1) in yearly_equity:
            start = yearly_equity[year-1]
            end = yearly_equity[year]
            yearly_returns[year] = (end - start) / start * 100
    
    # Calculate CAGR
    years = 5
    cagr = ((equity / initial_capital) ** (1 / years) - 1) * 100

    return {
        'symbol': symbol,
        'yearly_returns': yearly_returns,
        'cagr': cagr,
        'final_equity': equity,
        'max_drawdown': max_drawdown,
        'max_position_size': max_position_size_actual,
        'trades': trades
    }

def buy_and_hold_yearly(candles, symbol):
    """Calculate Buy & Hold returns"""
    yearly_prices = {}
    
    for candle in candles:
        candle_date = datetime.fromtimestamp(candle['open_time'] / 1000)
        year = candle_date.year
        
        if year not in yearly_prices:
            yearly_prices[year] = {'first': candle['close'], 'last': candle['close']}
        else:
            yearly_prices[year]['last'] = candle['close']
    
    # Calculate yearly returns
    yearly_returns = {}
    for year in range(2021, 2026):
        if year in yearly_prices and (year-1) in yearly_prices:
            start_price = yearly_prices[year-1]['last']
            end_price = yearly_prices[year]['last']
            yearly_returns[year] = (end_price - start_price) / start_price * 100
    
    # Calculate CAGR (use first available year to last year)
    first_year = min(yearly_prices.keys())
    last_year = max(yearly_prices.keys())
    first_price = yearly_prices[first_year]['first']
    last_price = yearly_prices[last_year]['last']
    years = last_year - first_year + 1
    cagr = ((last_price / first_price) ** (1 / years) - 1) * 100
    
    return {
        'symbol': symbol,
        'yearly_returns': yearly_returns,
        'cagr': cagr,
        'first_price': first_price,
        'last_price': last_price
    }

# Run analysis
print("="*100)
print("PHÂN TÍCH CAGR TỪNG COIN THEO NĂM")
print("="*100)

coins = [
    ('ETHUSDT_4000_1609434000000', 'ETH'),
    ('BNBUSDT_4000_1609434000000', 'BNB'),
    ('TRXUSDT_4000_1609434000000', 'TRX')
]

trading_results = {}
hold_results = {}

for symbol_key, symbol_name in coins:
    print(f"\n{'='*100}")
    print(f"Analyzing {symbol_name}...")
    print(f"{'='*100}")
    
    candles = data[symbol_key]
    
    # Convert to dict format
    candles_dict = [{"open_time": k['open_time'], "open": k['open'], "high": k['high'], 
                     "low": k['low'], "close": k['close'], "volume": k['volume']} 
                    for k in candles]
    
    # Trading (v15 ATR Exit)
    trading = backtest_coin_yearly(candles_dict, symbol_name)
    trading_results[symbol_name] = trading
    
    # Buy & Hold
    hold = buy_and_hold_yearly(candles_dict, symbol_name)
    hold_results[symbol_name] = hold
    
    print(f"\n📈 {symbol_name} - Trading (v15 ATR Exit)")
    print(f"  CAGR 5 năm: {trading['cagr']:.2f}%")
    print(f"  Final Equity: ${trading['final_equity']:,.2f}")
    print(f"  Yearly Returns:")
    for year in range(2021, 2026):
        ret = trading['yearly_returns'].get(year, 0)
        print(f"    {year}: {ret:+.2f}%")
    
    print(f"\n💰 {symbol_name} - Buy & Hold")
    print(f"  CAGR 5 năm: {hold['cagr']:.2f}%")
    print(f"  Price: ${hold['first_price']:.2f} → ${hold['last_price']:.2f}")
    print(f"  Yearly Returns:")
    for year in range(2021, 2026):
        ret = hold['yearly_returns'].get(year, 0)
        print(f"    {year}: {ret:+.2f}%")

# Summary table
print("\n" + "="*100)
print("SUMMARY TABLE")
print("="*100)

print(f"\n{'Coin':<10} {'2021':>10} {'2022':>10} {'2023':>10} {'2024':>10} {'2025':>10} {'CAGR':>10} {'Final':>12}")
print("-"*100)

for symbol in ['ETH', 'BNB', 'TRX']:
    trading = trading_results[symbol]
    print(f"{symbol:<10} "
          f"{trading['yearly_returns'].get(2021, 0):>+9.2f}% "
          f"{trading['yearly_returns'].get(2022, 0):>+9.2f}% "
          f"{trading['yearly_returns'].get(2023, 0):>+9.2f}% "
          f"{trading['yearly_returns'].get(2024, 0):>+9.2f}% "
          f"{trading['yearly_returns'].get(2025, 0):>+9.2f}% "
          f"{trading['cagr']:>+9.2f}% "
          f"${trading['final_equity']:>11,.2f}")

print(f"\n{'Average':<10} ", end="")
for year in range(2021, 2026):
    avg = mean([trading_results[s]['yearly_returns'].get(year, 0) for s in ['ETH', 'BNB', 'TRX']])
    print(f"{avg:>+9.2f}% ", end="")

avg_cagr = mean([trading_results[s]['cagr'] for s in ['ETH', 'BNB', 'TRX']])
avg_final = mean([trading_results[s]['final_equity'] for s in ['ETH', 'BNB', 'TRX']])
print(f"{avg_cagr:>+9.2f}% ${avg_final:>11,.2f}")

# Gap analysis
print("\n" + "="*100)
print("GAP ANALYSIS: TRADING vs BUY & HOLD")
print("="*100)

print(f"\n{'Coin':<10} {'Year':<6} {'Trading':>10} {'Hold':>10} {'Gap':>10} {'Bull?':<6}")
print("-"*100)

bull_years = []
bear_years = []

for symbol in ['ETH', 'BNB', 'TRX']:
    trading = trading_results[symbol]
    hold = hold_results[symbol]
    
    for year in range(2021, 2026):
        trading_ret = trading['yearly_returns'].get(year, 0)
        hold_ret = hold['yearly_returns'].get(year, 0)
        gap = trading_ret - hold_ret
        
        # Determine if bull market (hold return > 20%)
        is_bull = hold_ret > 20
        bull_marker = "🐂" if is_bull else "🐻"
        
        print(f"{symbol:<10} {year:<6} {trading_ret:>+9.2f}% {hold_ret:>+9.2f}% {gap:>+9.2f}% {bull_marker:<6}")
        
        if is_bull:
            bull_years.append((symbol, year, trading_ret, hold_ret, gap))
        else:
            bear_years.append((symbol, year, trading_ret, hold_ret, gap))

# Bull market analysis
print("\n" + "="*100)
print("BULL MARKET ANALYSIS (Hold Return > 20%)")
print("="*100)

if bull_years:
    print(f"\n{'Coin':<10} {'Year':<6} {'Trading':>10} {'Hold':>10} {'Gap':>10} {'Capture':>10}")
    print("-"*100)
    
    total_trading = 0
    total_hold = 0
    
    for symbol, year, trading_ret, hold_ret, gap in bull_years:
        capture = trading_ret / hold_ret * 100 if hold_ret > 0 else 0
        print(f"{symbol:<10} {year:<6} {trading_ret:>+9.2f}% {hold_ret:>+9.2f}% {gap:>+9.2f}% {capture:>9.1f}%")
        total_trading += trading_ret
        total_hold += hold_ret
    
    print("-"*100)
    avg_trading = total_trading / len(bull_years)
    avg_hold = total_hold / len(bull_years)
    avg_gap = avg_trading - avg_hold
    avg_capture = avg_trading / avg_hold * 100 if avg_hold > 0 else 0
    print(f"{'Average':<10} {'':<6} {avg_trading:>+9.2f}% {avg_hold:>+9.2f}% {avg_gap:>+9.2f}% {avg_capture:>9.1f}%")
    
    print(f"\n📊 Bull Market Summary:")
    print(f"  Total bull years: {len(bull_years)}")
    print(f"  Average Trading return: {avg_trading:+.2f}%")
    print(f"  Average Hold return: {avg_hold:+.2f}%")
    print(f"  Average Gap: {avg_gap:+.2f}%")
    print(f"  Average Capture Ratio: {avg_capture:.1f}%")
    
    if avg_capture > 80:
        print(f"\n✅ GOOD: Trading captures {avg_capture:.1f}% of bull market (target > 80%)")
    elif avg_capture > 50:
        print(f"\n⚠️  ACCEPTABLE: Trading captures {avg_capture:.1f}% of bull market (target > 50%)")
    else:
        print(f"\n❌ POOR: Trading captures only {avg_capture:.1f}% of bull market (target > 50%)")

# Bear market analysis
print("\n" + "="*100)
print("BEAR MARKET ANALYSIS (Hold Return <= 20%)")
print("="*100)

if bear_years:
    print(f"\n{'Coin':<10} {'Year':<6} {'Trading':>10} {'Hold':>10} {'Gap':>10} {'Protection':>10}")
    print("-"*100)
    
    total_trading = 0
    total_hold = 0
    
    for symbol, year, trading_ret, hold_ret, gap in bear_years:
        protection = (trading_ret - hold_ret) / abs(hold_ret) * 100 if hold_ret < 0 else 0
        print(f"{symbol:<10} {year:<6} {trading_ret:>+9.2f}% {hold_ret:>+9.2f}% {gap:>+9.2f}% {protection:>9.1f}%")
        total_trading += trading_ret
        total_hold += hold_ret
    
    print("-"*100)
    avg_trading = total_trading / len(bear_years)
    avg_hold = total_hold / len(bear_years)
    avg_gap = avg_trading - avg_hold
    avg_protection = (avg_trading - avg_hold) / abs(avg_hold) * 100 if avg_hold < 0 else 0
    print(f"{'Average':<10} {'':<6} {avg_trading:>+9.2f}% {avg_hold:>+9.2f}% {avg_gap:>+9.2f}% {avg_protection:>9.1f}%")
    
    print(f"\n📊 Bear Market Summary:")
    print(f"  Total bear years: {len(bear_years)}")
    print(f"  Average Trading return: {avg_trading:+.2f}%")
    print(f"  Average Hold return: {avg_hold:+.2f}%")
    print(f"  Average Gap: {avg_gap:+.2f}%")
    
    if avg_gap > 0:
        print(f"\n✅ GOOD: Trading outperforms Hold by {avg_gap:+.2f}% in bear markets")
    else:
        print(f"\n⚠️  Trading underperforms Hold by {avg_gap:+.2f}% in bear markets")

# Final summary
print("\n" + "="*100)
print("FINAL SUMMARY")
print("="*100)

print(f"\n📈 CAGR 5 năm:")
print(f"  {'Coin':<10} {'Trading':>10} {'Hold':>10} {'Gap':>10}")
print(f"  {'-'*40}")

total_trading_cagr = 0
total_hold_cagr = 0

for symbol in ['ETH', 'BNB', 'TRX']:
    trading_cagr = trading_results[symbol]['cagr']
    hold_cagr = hold_results[symbol]['cagr']
    gap = trading_cagr - hold_cagr
    print(f"  {symbol:<10} {trading_cagr:>+9.2f}% {hold_cagr:>+9.2f}% {gap:>+9.2f}%")
    total_trading_cagr += trading_cagr
    total_hold_cagr += hold_cagr

print(f"  {'-'*40}")
avg_trading_cagr = total_trading_cagr / 3
avg_hold_cagr = total_hold_cagr / 3
avg_gap = avg_trading_cagr - avg_hold_cagr
print(f"  {'Average':<10} {avg_trading_cagr:>+9.2f}% {avg_hold_cagr:>+9.2f}% {avg_gap:>+9.2f}%")

print(f"\n💡 Kết luận:")
print(f"  - Trading CAGR trung bình: {avg_trading_cagr:.2f}%")
print(f"  - Hold CAGR trung bình: {avg_hold_cagr:.2f}%")
print(f"  - Gap: {avg_gap:+.2f}%")

if avg_gap > 0:
    print(f"\n✅ Trading outperforms Hold by {avg_gap:.2f}% CAGR")
elif avg_gap > -10:
    print(f"\n⚠️  Trading underperforms Hold by {abs(avg_gap):.2f}% CAGR (acceptable)")
else:
    print(f"\n❌ Trading significantly underperforms Hold by {abs(avg_gap):.2f}% CAGR")

print("\n" + "="*100)
