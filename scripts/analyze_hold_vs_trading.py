#!/usr/bin/env python3
"""Deep analysis: Hold vs Trading strategy comparison per coin.

Analyze:
1. Hold strategy: Buy Jan 1, Sell Dec 31 → ROI
2. Trading strategy: ROI from backtest
3. Gap analysis: When trading underperforms hold → why?
"""

import sys, os, json
from datetime import datetime

sys.path.insert(0, 'scripts')
from crypto_trading import sma

SF = 2.0
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")

with open(CACHE) as f:
    _cache = json.load(f)


def fetch(symbol):
    """Fetch cached klines data."""
    key = f"{symbol}_4000_1609434000000"
    return _cache.get(key, [])


def get_yearly_prices(symbol):
    """Get first and last price of each year."""
    data = fetch(symbol)
    if not data:
        return {}
    
    yearly = {}
    for candle in data:
        ts = candle['open_time'] / 1000  # Convert ms to seconds
        dt = datetime.utcfromtimestamp(ts)
        year = dt.year
        
        if year not in yearly:
            yearly[year] = {'first': None, 'last': None, 'first_ts': float('inf'), 'last_ts': 0}
        
        if ts < yearly[year]['first_ts']:
            yearly[year]['first'] = candle['close']
            yearly[year]['first_ts'] = ts
        
        if ts > yearly[year]['last_ts']:
            yearly[year]['last'] = candle['close']
            yearly[year]['last_ts'] = ts
    
    return yearly


def calculate_hold_roi(yearly_prices, years):
    """Calculate hold ROI for each year."""
    hold_roi = {}
    for year in years:
        if year in yearly_prices and yearly_prices[year]['first'] and yearly_prices[year]['last']:
            first_price = yearly_prices[year]['first']
            last_price = yearly_prices[year]['last']
            roi = ((last_price - first_price) / first_price) * 100
            hold_roi[year] = roi
    return hold_roi


def main():
    print("=" * 100)
    print("  DEEP ANALYSIS: Hold vs Trading Strategy Comparison")
    print("=" * 100)
    
    # Trading ROI from previous backtest (v11)
    trading_roi = {
        'ETH': {2021: 86.5, 2022: 24.6, 2023: 0.4, 2024: 0.8, 2025: 41.7},
        'BNB': {2021: 316.0, 2022: 0.0, 2023: 9.0, 2024: 11.0, 2025: 11.7},
        'TRX': {2021: 173.6, 2022: -14.1, 2023: 20.9, 2024: 48.9, 2025: 7.1},
    }
    
    years = [2021, 2022, 2023, 2024, 2025]
    coins = ['ETH', 'BNB', 'TRX']
    
    # Calculate Hold ROI
    hold_roi = {}
    yearly_prices = {}
    
    for coin in coins:
        symbol = f"{coin}USDT"
        yearly_prices[coin] = get_yearly_prices(symbol)
        hold_roi[coin] = calculate_hold_roi(yearly_prices[coin], years)
    
    # Comparison table
    print("\n" + "=" * 100)
    print("  HOLD vs TRADING ROI COMPARISON")
    print("=" * 100)
    
    for coin in coins:
        print(f"\n{coin}:")
        print(f"  {'Year':<6} {'Price Start':>12} {'Price End':>12} {'Hold ROI':>10} {'Trade ROI':>10} {'Gap':>8} {'Winner':>10}")
        print("  " + "-" * 80)
        
        total_hold = 0
        total_trade = 0
        years_analyzed = 0
        
        for year in years:
            if year in hold_roi[coin] and year in trading_roi[coin]:
                first_price = yearly_prices[coin][year]['first']
                last_price = yearly_prices[coin][year]['last']
                hold = hold_roi[coin][year]
                trade = trading_roi[coin][year]
                gap = trade - hold
                winner = "Trade ✓" if trade > hold else "Hold ✓" if hold > trade else "Equal"
                
                print(f"  {year:<6} ${first_price:>11.2f} ${last_price:>11.2f} {hold:>+9.1f}% {trade:>+9.1f}% {gap:>+7.1f}% {winner:>10}")
                
                total_hold += hold
                total_trade += trade
                years_analyzed += 1
        
        if years_analyzed > 0:
            avg_hold = total_hold / years_analyzed
            avg_trade = total_trade / years_analyzed
            avg_gap = avg_trade - avg_hold
            print("  " + "-" * 80)
            print(f"  {'Avg':<6} {'':>12} {'':>12} {avg_hold:>+9.1f}% {avg_trade:>+9.1f}% {avg_gap:>+7.1f}%")
    
    # Deep dive: Years where trading underperformed hold significantly
    print("\n" + "=" * 100)
    print("  GAP ANALYSIS: When Trading Underperforms Hold")
    print("=" * 100)
    
    significant_gaps = []
    
    for coin in coins:
        for year in years:
            if year in hold_roi[coin] and year in trading_roi[coin]:
                hold = hold_roi[coin][year]
                trade = trading_roi[coin][year]
                gap = trade - hold
                
                # Significant underperformance: gap < -20%
                if gap < -20:
                    significant_gaps.append({
                        'coin': coin,
                        'year': year,
                        'hold': hold,
                        'trade': trade,
                        'gap': gap,
                        'first_price': yearly_prices[coin][year]['first'],
                        'last_price': yearly_prices[coin][year]['last'],
                    })
    
    if significant_gaps:
        for gap_info in significant_gaps:
            coin = gap_info['coin']
            year = gap_info['year']
            hold = gap_info['hold']
            trade = gap_info['trade']
            gap = gap_info['gap']
            
            print(f"\n⚠️  {coin} {year}: Trading underperformed Hold by {abs(gap):.1f}%")
            print(f"   Hold: {hold:+.1f}% | Trade: {trade:+.1f}% | Gap: {gap:+.1f}%")
            print(f"   Price: ${gap_info['first_price']:.2f} → ${gap_info['last_price']:.2f}")
            
            # Analyze why
            print(f"\n   Possible reasons:")
            
            if hold > 50:
                print(f"   • Strong bull trend ({hold:+.1f}%) - trading exited too early on volatility")
                print(f"   • Stop losses triggered during pullbacks, missed continuation")
                print(f"   • Sideway filter may have blocked re-entries during consolidation phases")
            
            if hold < -30:
                print(f"   • Strong bear trend ({hold:+.1f}%) - trading tried to catch bounces")
                print(f"   • Multiple failed long entries before trend confirmed bearish")
                print(f"   • Short entries may have been limited by cooldown or sideway filter")
            
            if abs(hold) < 20:
                print(f"   • Sideway market ({hold:+.1f}%) - trading struggled to capture small moves")
                print(f"   • Frequent entries/exits with small losses accumulated")
                print(f"   • Transaction costs (fees + slippage) eroded profits")
            
            # Specific coin insights
            if coin == 'ETH' and year == 2023:
                print(f"   • ETH-specific: Post-merge uncertainty, low volatility")
                print(f"   • Trading captured only +0.4% vs Hold +4.9%")
                print(f"   • Likely: Multiple small losses in choppy market")
            
            if coin == 'TRX' and year == 2024:
                print(f"   • TRX-specific: Strong rally (+55.1% hold) but trading captured only +48.9%")
                print(f"   • Likely: Exited positions during pullbacks, missed final leg up")
                print(f"   • Or: Entered late after significant move already happened")
    else:
        print("\n✅ No significant underperformance (all gaps > -20%)")
    
    # Summary statistics
    print("\n" + "=" * 100)
    print("  SUMMARY STATISTICS")
    print("=" * 100)
    
    for coin in coins:
        trade_wins = 0
        hold_wins = 0
        total_years = 0
        
        for year in years:
            if year in hold_roi[coin] and year in trading_roi[coin]:
                total_years += 1
                if trading_roi[coin][year] > hold_roi[coin][year]:
                    trade_wins += 1
                elif hold_roi[coin][year] > trading_roi[coin][year]:
                    hold_wins += 1
        
        if total_years > 0:
            trade_win_rate = (trade_wins / total_years) * 100
            print(f"\n{coin}:")
            print(f"  Trading wins: {trade_wins}/{total_years} years ({trade_win_rate:.0f}%)")
            print(f"  Hold wins:    {hold_wins}/{total_years} years ({100-trade_win_rate:.0f}%)")
            
            avg_trade = sum(trading_roi[coin].values()) / len(trading_roi[coin])
            avg_hold = sum(hold_roi[coin].values()) / len(hold_roi[coin])
            print(f"  Avg ROI: Trade {avg_trade:+.1f}% vs Hold {avg_hold:+.1f}% (Δ {avg_trade-avg_hold:+.1f}%)")
    
    # Recommendations
    print("\n" + "=" * 100)
    print("  RECOMMENDATIONS")
    print("=" * 100)
    
    print("\n✅ Trading Strategy Strengths:")
    print("   • Protects capital in bear markets (2022: ETH +24.6% vs Hold -67.5%)")
    print("   • Captures profits while managing downside risk")
    print("   • v11 improvements: ETH 2024 from -7.4% → +0.8%")
    
    print("\n⚠️  Trading Strategy Weaknesses:")
    print("   • May underperform in strong bull runs (exits too early)")
    print("   • Transaction costs reduce net returns")
    print("   • Sideway markets generate small losses")
    
    print("\n💡 Optimization Opportunities:")
    print("   • Consider longer holding periods during confirmed bull trends")
    print("   • Reduce position sizing in low-volatility sideway markets")
    print("   • Implement trend-strength filter (ADX > 30 = strong trend, hold longer)")
    
    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
