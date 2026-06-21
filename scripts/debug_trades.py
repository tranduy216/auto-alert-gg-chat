#!/usr/bin/env python3
"""
Debug script - Đếm số trades và validate logic

Mục tiêu: Kiểm tra xem có bao nhiêu trades được thực hiện và logic có đúng không
"""

import json
from pathlib import Path
from datetime import datetime

# Load cache
cache_file = Path("scripts/_klines_12h_5y.json")
with open(cache_file) as f:
    data = json.load(f)

def compute_sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

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

    # Use Wilder's smoothing
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

def debug_trades(symbol, rsi_max=65, atr_multiplier=2.0, initial_exposure=0.25):
    """Debug trades cho 1 coin"""
    candles_data = data.get(f"{symbol}USDT_4000_1609434000000", [])
    candles = [{"open_time": k['open_time'], "open": k['open'], "high": k['high'], 
                "low": k['low'], "close": k['close'], "volume": k['volume']} 
               for k in candles_data]
    
    print(f"\n{'='*80}")
    print(f"DEBUG TRADES - {symbol}")
    print(f"{'='*80}")
    
    initial_capital = 10000
    equity = initial_capital
    position = None
    
    trades = []
    entries = 0
    exits = 0
    snowballs = 0
    
    for i in range(200, len(candles)):
        window = candles[max(0, i-200):i+1]
        prices = [c['close'] for c in window]
        current_price = prices[-1]
        
        # Compute indicators
        adx = compute_adx(window)
        bull_score = compute_bull_score(window)
        
        # Determine regime
        if adx > 30 and bull_score >= 3:
            regime = 'HOLD'
        else:
            regime = 'TRADING'
        
        # Exit logic
        if position:
            current_pnl_pct = (current_price - position['entry_price']) / position['entry_price']
            peak_price = position.get('peak_price', position['entry_price'])
            
            if current_price > peak_price:
                position['peak_price'] = current_price
                peak_price = current_price
            
            # Trailing stop trigger
            if current_pnl_pct > 0.30 and not position.get('trailing_activated'):
                close_pct = 0.70
                close_exposure = position['exposure'] * close_pct
                pnl = current_pnl_pct * close_exposure * position['position_equity'] * 3.5
                equity += pnl
                position['exposure'] = position['exposure'] * (1 - close_pct)
                position['trailing_activated'] = True
                position['trailing_stop_pct'] = 0.09
                
                trades.append({
                    'type': 'trailing_activated',
                    'price': current_price,
                    'pnl_pct': current_pnl_pct * 100,
                    'pnl': pnl,
                    'exposure': close_exposure,
                    'equity': equity
                })
            
            # Trailing stop exit
            if position.get('trailing_activated'):
                trailing_stop_price = peak_price * (1 - position['trailing_stop_pct'])
                if current_price < trailing_stop_price:
                    exit_price = current_price
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                    pnl = pnl_pct * position['exposure'] * position['position_equity'] * 3.5
                    equity += pnl
                    
                    trades.append({
                        'type': 'trailing_exit',
                        'entry': position['entry_price'],
                        'exit': exit_price,
                        'pnl_pct': pnl_pct * 100,
                        'pnl': pnl,
                        'exposure': position['exposure'],
                        'equity': equity
                    })
                    
                    position = None
                    exits += 1
                    continue
            
            # ATR-based exit
            if not position.get('trailing_activated'):
                atr = compute_adx(window) * current_price / 100
                if current_price < peak_price - atr_multiplier * atr:
                    exit_price = current_price
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                    pnl = pnl_pct * position['exposure'] * position['position_equity'] * 3.5
                    equity += pnl
                    
                    trades.append({
                        'type': 'atr_exit',
                        'entry': position['entry_price'],
                        'exit': exit_price,
                        'pnl_pct': pnl_pct * 100,
                        'pnl': pnl,
                        'exposure': position['exposure'],
                        'equity': equity
                    })
                    
                    position = None
                    exits += 1
                    continue
        
        # Entry logic
        if not position and regime == 'HOLD':
            entry_price = current_price
            exposure = initial_exposure
            
            position = {
                'entry_price': entry_price,
                'exposure': exposure,
                'position_equity': equity,
                'snowball_levels': [1.10, 1.20],
                'snowball_hit': [],
                'peak_price': entry_price,
                'max_exposure': 0.75
            }
            
            trades.append({
                'type': 'entry',
                'price': entry_price,
                'exposure': exposure,
                'equity': equity
            })
            
            entries += 1
        
        # Snowball logic
        if position and regime == 'HOLD':
            for level in position['snowball_levels']:
                if level not in position['snowball_hit']:
                    target_price = position['entry_price'] * level
                    if current_price >= target_price:
                        max_exp = position.get('max_exposure', 0.75)
                        if position['exposure'] + initial_exposure <= max_exp:
                            position['snowball_hit'].append(level)
                            position['exposure'] += initial_exposure
                            
                            trades.append({
                                'type': 'snowball',
                                'level': level,
                                'price': current_price,
                                'exposure': position['exposure'],
                                'equity': equity
                            })
                            
                            snowballs += 1
    
    # Close remaining position
    if position:
        final_price = candles[-1]['close']
        pnl_pct = (final_price - position['entry_price']) / position['entry_price']
        pnl = pnl_pct * position['exposure'] * position['position_equity'] * 3.5
        equity += pnl
        
        trades.append({
            'type': 'final_close',
            'entry': position['entry_price'],
            'exit': final_price,
            'pnl_pct': pnl_pct * 100,
            'pnl': pnl,
            'exposure': position['exposure'],
            'equity': equity
        })
    
    # Print summary
    print(f"\nTotal Candles: {len(candles)}")
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Final Equity: ${equity:,.2f}")
    print(f"Total Return: {(equity/initial_capital - 1)*100:.2f}%")
    print(f"\nEntries: {entries}")
    print(f"Exits: {exits}")
    print(f"Snowballs: {snowballs}")
    
    # Print first 20 trades
    print(f"\nFirst 20 Trades:")
    print(f"{'Type':<20} {'Entry':<12} {'Exit':<12} {'PnL%':<10} {'PnL$':<12} {'Exposure':<10} {'Equity':<15}")
    print("-"*100)
    
    for trade in trades[:20]:
        trade_type = trade['type']
        entry = trade.get('entry', trade.get('price', 0))
        exit_price = trade.get('exit', '-')
        pnl_pct = trade.get('pnl_pct', 0)
        pnl = trade.get('pnl', 0)
        exposure = trade.get('exposure', 0)
        equity_val = trade.get('equity', 0)
        
        if isinstance(exit_price, (int, float)):
            print(f"{trade_type:<20} ${entry:<11.2f} ${exit_price:<11.2f} {pnl_pct:>+9.2f}% ${pnl:<11.2f} {exposure:<10.2f} ${equity_val:<14,.2f}")
        else:
            print(f"{trade_type:<20} ${entry:<11.2f} {'-':<12} {pnl_pct:>+9.2f}% ${pnl:<11.2f} {exposure:<10.2f} ${equity_val:<14,.2f}")
    
    # Calculate CAGR
    years = 5
    cagr = ((equity / initial_capital) ** (1 / years) - 1) * 100
    
    print(f"\nCAGR: {cagr:.2f}%")
    print(f"{'='*80}\n")
    
    return trades

def main():
    print("\n" + "="*80)
    print("DEBUG TRADES SCRIPT")
    print("="*80)
    
    # Debug ETH
    eth_trades = debug_trades('ETH', rsi_max=70, atr_multiplier=2.5)
    
    # Debug BNB
    bnb_trades = debug_trades('BNB', rsi_max=65, atr_multiplier=2.0)
    
    # Debug TRX
    trx_trades = debug_trades('TRX', rsi_max=65, atr_multiplier=2.0)
    
    print("\n" + "="*80)
    print("VALIDATION")
    print("="*80)
    print()
    print(f"ETH: {len(eth_trades)} trades")
    print(f"BNB: {len(bnb_trades)} trades")
    print(f"TRX: {len(trx_trades)} trades")
    print()
    print("Nếu CAGR vẫn > 100%, có thể:")
    print("  1. Leverage 3.5x được áp dụng quá nhiều lần")
    print("  2. Compound effect quá mạnh")
    print("  3. Có bug khác chưa phát hiện")
    print()

if __name__ == "__main__":
    main()
