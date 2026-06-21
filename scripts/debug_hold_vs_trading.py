#!/usr/bin/env python3
"""Debug: Tại sao HOLD mode không tốt hơn trading trong bull market?"""

import sys
import os
import json
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

# Load cache
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
with open(CACHE) as f:
    cache = json.load(f)

def fetch(symbol):
    key = f"{symbol}_4000_1609434000000"
    return cache.get(key, [])

def sma(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period

def detect_regime(btc_candles, idx):
    """Detect bull/bear regime."""
    if idx < 200:
        return 'NEUTRAL'
    
    candles = btc_candles[:idx+1]
    closes = [c['close'] for c in candles]
    
    ma50 = sma(closes, 50)
    ma200 = sma(closes, 200)
    
    # Bull Score
    ma20 = sma(closes, 20)
    ma100 = sma(closes, 100)
    
    if len(closes) > 10:
        ma50_10_ago = sma(closes[:-10], 50)
    else:
        ma50_10_ago = ma50
    slope50 = (ma50 - ma50_10_ago) / ma50_10_ago if ma50_10_ago > 0 else 0
    
    volumes = [c['volume'] for c in candles]
    vol_sma20 = sma(volumes, 20)
    vol_ratio = volumes[-1] / vol_sma20 if vol_sma20 > 0 else 1.0
    
    bull_score = 0
    if ma20 > ma50:
        bull_score += 1
    if ma50 > ma100:
        bull_score += 1
    if slope50 > 0:
        bull_score += 1
    if vol_ratio > 1.0:
        bull_score += 1
    if ma50 > ma200:
        bull_score += 1
    
    return 'BULL' if bull_score >= 3 else 'BEAR'

print("=" * 100)
print("DEBUG: Tại sao HOLD mode không tốt hơn trading trong bull market?")
print("=" * 100)

btc_candles = fetch('BTCUSDT')
coins = ['ETH', 'BNB', 'TRX']

for coin in coins:
    candles = fetch(f'{coin}USDT')
    if not candles:
        continue
    
    print(f"\n{'='*100}")
    print(f"{coin} ANALYSIS")
    print(f"{'='*100}")
    
    # Count regime distribution
    regime_count = defaultdict(int)
    regime_by_year = defaultdict(lambda: defaultdict(int))
    
    for idx in range(200, len(candles)):
        regime = detect_regime(btc_candles, idx)
        regime_count[regime] += 1
        
        year = datetime.fromtimestamp(candles[idx]['open_time'] / 1000).year
        regime_by_year[year][regime] += 1
    
    total_candles = sum(regime_count.values())
    
    print(f"\nRegime Distribution:")
    for regime, count in sorted(regime_count.items()):
        pct = count / total_candles * 100
        print(f"  {regime:<10}: {count:>5} candles ({pct:>5.1f}%)")
    
    print(f"\nRegime by Year:")
    for year in sorted(regime_by_year.keys()):
        year_data = regime_by_year[year]
        total = sum(year_data.values())
        bull_pct = year_data.get('BULL', 0) / total * 100
        bear_pct = year_data.get('BEAR', 0) / total * 100
        print(f"  {year}: BULL {bull_pct:>5.1f}%, BEAR {bear_pct:>5.1f}%")
    
    # Calculate buy & hold returns by regime
    print(f"\nBuy & Hold Returns by Regime:")
    
    for year in range(2021, 2026):
        year_candles = [c for c in candles if datetime.fromtimestamp(c['open_time'] / 1000).year == year]
        if not year_candles:
            continue
        
        # Split by regime
        bull_prices = []
        bear_prices = []
        
        for candle in year_candles:
            idx = candles.index(candle)
            regime = detect_regime(btc_candles, idx)
            
            if regime == 'BULL':
                bull_prices.append(candle['close'])
            else:
                bear_prices.append(candle['close'])
        
        if bull_prices:
            bull_return = (bull_prices[-1] - bull_prices[0]) / bull_prices[0] * 100
            print(f"  {year} BULL: {bull_return:>+7.1f}% ({len(bull_prices)} candles)")
        
        if bear_prices:
            bear_return = (bear_prices[-1] - bear_prices[0]) / bear_prices[0] * 100
            print(f"  {year} BEAR: {bear_return:>+7.1f}% ({len(bear_prices)} candles)")
        
        # Total year
        total_return = (year_candles[-1]['close'] - year_candles[0]['close']) / year_candles[0]['close'] * 100
        print(f"  {year} TOTAL: {total_return:>+7.1f}%")
        print()

print("\n" + "=" * 100)
print("INSIGHTS")
print("=" * 100)
print("""
Tại sao HOLD mode có thể thấp hơn trading:

1. Regime transitions quá thường xuyên
   - HOLD mode vào/ra liên tục
   - Miss early trend và late trend profits

2. Exit logic quá chậm
   - Wait for MA50 cross (2 candles)
   - Give back nhiều profits khi trend reversal

3. Position sizing conservative
   - Snowball bắt đầu 25%, max 100%
   - Trading mode dùng 100% ngay

4. Không có short positions
   - Trading profit trong BEAR regime
   - HOLD chỉ CASH trong BEAR (0% return)

5. Anti-FOMO filters
   - Skip entries khi overheated
   - Có thể miss strong momentum moves

Recommendations:
- Optimize exit logic (faster exit)
- Increase initial position (50% instead of 25%)
- Add trailing stop instead of fixed MA50 exit
- Consider hybrid: HOLD in strong bull, trading in weak bull
""")
