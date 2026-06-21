#!/usr/bin/env python3
"""Backtest v12: Adaptive Strategy with Hold Mode.

Market Regime Detection (BTC-based):
- Bull (BullScore >= 3) => HOLD MODE
- Bear => SHORT MODE (Trading)
- Sideway => CASH
- Choppy => SMALL SIZE / NO TRADE

Hold Mode Logic:
- Entry: Buy once when transitioning to HOLD MODE
- Hold: Ignore all signals, hold through small pullbacks
- Exit: Close < MA50 (2 candles) OR MA20 crosses down MA50
"""

import sys, os, json
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

# Constants
FEE_RATE = 0.0005
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")

PROFILES_BULL = {
    "ETH": {"lev": 2.5, "sl": 10, "trail": 0.04, "pos_mult": 1.0},
    "BNB": {"lev": 3.5, "sl": 12, "trail": 0.065, "pos_mult": 1.0},
    "TRX": {"lev": 3.5, "sl": 12, "trail": 0.065, "pos_mult": 1.0},
}
PROFILES_BEAR = {
    "ETH": {"lev": 2.0, "sl": 8, "trail": 0.04, "pos_mult": 0.90},
    "BNB": {"lev": 2.0, "sl": 10, "trail": 0.065, "pos_mult": 0.75},
    "TRX": {"lev": 2.0, "sl": 8, "trail": 0.065, "pos_mult": 0.75},
}
SHORT_COINS = {"ETH", "TRX"}

BASE = 10000
TP = [(8.0, 0.25), (15.0, 0.25), (25.0, 0.25), (40.0, 0.25)]


def load_cache():
    """Load cached candles."""
    with open(CACHE) as f:
        return json.load(f)


def fetch(cache, symbol):
    """Fetch candles from cache."""
    # Cache keys have format: SYMBOL_4000_1609434000000
    key = f"{symbol}_4000_1609434000000"
    return cache.get(key, [])


def sma(closes, period):
    """Simple moving average."""
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


def compute_adx(candles, period=14):
    """Compute ADX (Average Directional Index)."""
    if len(candles) < period + 1:
        return 0
    
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    closes = [c['close'] for c in candles]
    
    plus_dm = []
    minus_dm = []
    tr_list = []
    
    for i in range(1, len(candles)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0)
        
        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0)
        
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    
    # Smooth with Wilder's method
    atr = sum(tr_list[:period]) / period
    plus_di = 100 * (sum(plus_dm[:period]) / period) / atr if atr > 0 else 0
    minus_di = 100 * (sum(minus_dm[:period]) / period) / atr if atr > 0 else 0
    
    dx_list = []
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_di = (plus_di * (period - 1) + plus_dm[i]) / period
        minus_di = (minus_di * (period - 1) + minus_dm[i]) / period
        
        di_sum = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0
        dx_list.append(dx)
    
    if not dx_list:
        return 0
    
    adx = sum(dx_list[-period:]) / min(period, len(dx_list))
    return adx


def compute_sideway_score(candles, sf=1.0):
    """Compute sideway score (0-4)."""
    if len(candles) < 30:
        return 0
    
    closes = [c['close'] for c in candles]
    volumes = [c['volume'] for c in candles]
    
    # MA spread
    ma3 = sma(closes, 3)
    ma7 = sma(closes, 7)
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    ma_spread = (abs(ma3 - ma20) + abs(ma7 - ma20) + abs(ma10 - ma20)) / ma20
    
    # Slope
    slope20 = (ma20 - sma(closes[:-10] if len(closes) > 10 else closes, 20)) / ma20
    
    # Volume ratio
    vol_ratio = volumes[-1] / sma(volumes, 20) if sma(volumes, 20) > 0 else 1.0
    
    # Range
    range_pct = (max([c['high'] for c in candles[-20:]]) - min([c['low'] for c in candles[-20:]])) / min([c['low'] for c in candles[-20:]])
    
    score = 0
    if ma_spread < 0.05:
        score += 1
    if abs(slope20) < 0.01:
        score += 1
    if vol_ratio < 0.8:
        score += 1
    if range_pct < 0.15:
        score += 1
    
    return score


def detect_market_regime(btc_candles, current_idx):
    """
    Detect market regime based on BTC.
    
    Returns:
        'BULL' => HOLD MODE
        'BEAR' => SHORT MODE
        'SIDEWAY' => CASH
        'CHOPPY' => SMALL SIZE / NO TRADE
    """
    if current_idx < 100:
        return 'NEUTRAL'
    
    candles = btc_candles[:current_idx+1]
    closes = [c['close'] for c in candles]
    volumes = [c['volume'] for c in candles]
    
    # Compute MAs
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    ma100 = sma(closes, 100)
    
    # Compute slope50 (MA50 trend)
    if len(closes) > 10:
        ma50_10_ago = sma(closes[:-10], 50)
    else:
        ma50_10_ago = ma50
    slope50 = (ma50 - ma50_10_ago) / ma50_10_ago if ma50_10_ago > 0 else 0
    
    # Compute volume ratio
    vol_sma20 = sma(volumes, 20)
    vol_ratio = volumes[-1] / vol_sma20 if vol_sma20 > 0 else 1.0
    
    # Bull Score
    bull_score = 0
    if ma20 > ma50:
        bull_score += 1
    if ma50 > ma100:
        bull_score += 1
    if slope50 > 0:
        bull_score += 1
    if vol_ratio > 1.0:
        bull_score += 1
    
    # ADX for trend strength
    adx = compute_adx(candles)
    
    # Sideway score
    sideway_score = compute_sideway_score(candles, sf=2.0)
    
    # Determine regime
    if bull_score >= 3:
        return 'BULL'  # => HOLD MODE
    elif adx < 20 and sideway_score >= 3:
        return 'SIDEWAY'  # => CASH
    elif adx >= 20 and sideway_score >= 3:
        return 'CHOPPY'  # => SMALL SIZE / NO TRADE
    else:
        return 'BEAR'  # => SHORT MODE


def check_hold_exit(candles, current_idx, position):
    """
    Check if should exit HOLD position.
    
    Exit Rules:
    1. Close < MA50 for 2 consecutive candles
    2. MA20 crosses down MA50
    """
    if current_idx < 2:
        return False
    
    closes = [c['close'] for c in candles[:current_idx+1]]
    
    # Current and previous values
    ma50_now = sma(closes, 50)
    ma20_now = sma(closes, 20)
    ma50_prev = sma(closes[:-1], 50)
    ma20_prev = sma(closes[:-1], 20)
    
    # Exit 1: Close < MA50 for 2 consecutive candles
    close_now = closes[-1]
    close_prev = closes[-2]
    if close_now < ma50_now and close_prev < ma50_prev:
        return True
    
    # Exit 2: MA20 crosses down MA50
    if ma20_prev >= ma50_prev and ma20_now < ma50_now:
        return True
    
    return False


def run_backtest():
    """Run backtest with Hold Mode logic."""
    results = {}
    cache = load_cache()
    
    # Load BTC candles for regime detection
    btc_candles = fetch(cache, 'BTCUSDT')
    
    for coin in ["ETH", "BNB", "TRX"]:
        candles = fetch(cache, f'{coin}USDT')
        if not candles:
            continue
        
        allow_short = coin in SHORT_COINS
        profile_bull = PROFILES_BULL[coin]
        profile_bear = PROFILES_BEAR[coin]
        
        # State machine
        regime = 'NEUTRAL'
        hold_position = None  # {'entry_price': x, 'entry_idx': i, 'size': s}
        short_positions = []  # List of short positions
        
        # Trading stats
        consec_s = 0
        cd_s_until = -1
        rolling_sl_short = 0
        rolling_lock_until_short = -1
        
        equity_curve = [BASE]
        trades = []
        
        for idx in range(200, len(candles)):
            current_price = candles[idx]['close']
            current_date = candles[idx]['open_time']
            
            # Detect market regime
            new_regime = detect_market_regime(btc_candles, idx)
            
            # State transitions
            if regime != new_regime:
                # Exit hold position if leaving BULL
                if regime == 'BULL' and hold_position:
                    exit_price = current_price
                    pnl_pct = (exit_price - hold_position['entry_price']) / hold_position['entry_price'] * 100
                    equity = equity_curve[-1] * (1 + pnl_pct / 100 * hold_position['size'])
                    equity_curve.append(equity)
                    trades.append({
                        'type': 'HOLD_EXIT',
                        'entry_price': hold_position['entry_price'],
                        'exit_price': exit_price,
                        'pnl_pct': pnl_pct,
                        'date': current_date,
                    })
                    hold_position = None
                
                regime = new_regime
                
                # Enter hold position if entering BULL
                if regime == 'BULL' and hold_position is None:
                    entry_price = current_price
                    hold_position = {
                        'entry_price': entry_price,
                        'entry_idx': idx,
                        'size': 1.0,  # Full position
                    }
                    trades.append({
                        'type': 'HOLD_ENTRY',
                        'entry_price': entry_price,
                        'date': current_date,
                    })
            
            # HOLD MODE: Check exit conditions
            if regime == 'BULL' and hold_position:
                if check_hold_exit(candles, idx, hold_position):
                    exit_price = current_price
                    pnl_pct = (exit_price - hold_position['entry_price']) / hold_position['entry_price'] * 100
                    equity = equity_curve[-1] * (1 + pnl_pct / 100 * hold_position['size'])
                    equity_curve.append(equity)
                    trades.append({
                        'type': 'HOLD_EXIT',
                        'entry_price': hold_position['entry_price'],
                        'exit_price': exit_price,
                        'pnl_pct': pnl_pct,
                        'date': current_date,
                    })
                    hold_position = None
                    regime = 'NEUTRAL'
                
                # Skip all other logic in HOLD MODE
                continue
            
            # BEAR MODE: Trading logic (simplified short only)
            if regime == 'BEAR' and allow_short:
                # Check cooldowns
                if idx <= cd_s_until or idx <= rolling_lock_until_short:
                    continue
                
                # Simplified: Enter short if price drops 5% from recent high
                recent_high = max([c['high'] for c in candles[max(0, idx-20):idx+1]])
                if current_price < recent_high * 0.95 and not short_positions:
                    entry_price = current_price
                    profile = profile_bear
                    short_positions.append({
                        'entry_price': entry_price,
                        'entry_idx': idx,
                        'size': profile['pos_mult'],
                        'sl': profile['sl'],
                        'tp_idx': 0,
                    })
                    trades.append({
                        'type': 'SHORT_ENTRY',
                        'entry_price': entry_price,
                        'date': current_date,
                    })
                
                # Check short positions
                for pos in list(short_positions):
                    pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price'] * 100
                    
                    # Stop loss
                    if pnl_pct <= -pos['sl']:
                        equity = equity_curve[-1] * (1 + pnl_pct / 100 * pos['size'])
                        equity_curve.append(equity)
                        trades.append({
                            'type': 'SHORT_SL',
                            'entry_price': pos['entry_price'],
                            'exit_price': current_price,
                            'pnl_pct': pnl_pct,
                            'date': current_date,
                        })
                        short_positions.remove(pos)
                        consec_s += 1
                        rolling_sl_short += 1
                        
                        # Fibonacci cooldown (simplified)
                        cd_bars = min(3 + consec_s * 2, 13)
                        cd_s_until = idx + cd_bars
                        
                        # Rolling lock
                        if rolling_sl_short >= 3:
                            lock_bars = 8
                            if rolling_sl_short > 3:
                                lock_bars = min(8 + (rolling_sl_short - 3) * 5, 21)
                            rolling_lock_until_short = idx + lock_bars
                        continue
                    
                    # Take profit
                    if pos['tp_idx'] < len(TP):
                        tp_level, tp_size = TP[pos['tp_idx']]
                        if pnl_pct >= tp_level:
                            partial_size = pos['size'] * tp_size
                            equity = equity_curve[-1] * (1 + pnl_pct / 100 * partial_size)
                            equity_curve.append(equity)
                            pos['size'] -= partial_size
                            pos['tp_idx'] += 1
                            
                            if pos['size'] <= 0.01:
                                short_positions.remove(pos)
                                consec_s = 0
                                rolling_sl_short = 0
                    
                    # Trailing stop (after all TP)
                    if pos['tp_idx'] >= len(TP):
                        if 'highest' not in pos:
                            pos['highest'] = pos['entry_price']
                        pos['highest'] = min(pos['highest'], current_price)
                        
                        trail_pct = profile_bear['trail']
                        trail_stop = pos['highest'] * (1 + trail_pct)
                        
                        if current_price >= trail_stop:
                            equity = equity_curve[-1] * (1 + pnl_pct / 100 * pos['size'])
                            equity_curve.append(equity)
                            trades.append({
                                'type': 'SHORT_TRAIL',
                                'entry_price': pos['entry_price'],
                                'exit_price': current_price,
                                'pnl_pct': pnl_pct,
                                'date': current_date,
                            })
                            short_positions.remove(pos)
                            consec_s = 0
                            rolling_sl_short = 0
            
            # SIDEWAY / CHOPPY: CASH (do nothing)
            if not hold_position and not short_positions:
                equity_curve.append(equity_curve[-1])
        
        # Close any remaining positions
        if hold_position:
            exit_price = candles[-1]['close']
            pnl_pct = (exit_price - hold_position['entry_price']) / hold_position['entry_price'] * 100
            equity = equity_curve[-1] * (1 + pnl_pct / 100 * hold_position['size'])
            equity_curve.append(equity)
        
        for pos in short_positions:
            exit_price = candles[-1]['close']
            pnl_pct = (pos['entry_price'] - exit_price) / pos['entry_price'] * 100
            equity = equity_curve[-1] * (1 + pnl_pct / 100 * pos['size'])
            equity_curve.append(equity)
        
        # Compute metrics
        final_equity = equity_curve[-1]
        cagr = ((final_equity / BASE) ** (1/5) - 1) * 100
        max_dd = 0
        peak = BASE
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        sl_count = sum(1 for t in trades if 'SL' in t['type'])
        total_exits = sum(1 for t in trades if 'EXIT' in t['type'] or 'SL' in t['type'] or 'TRAIL' in t['type'])
        sl_rate = sl_count / total_exits * 100 if total_exits > 0 else 0
        
        # Yearly returns
        yearly_returns = {}
        for year in range(2021, 2026):
            year_candles = [c for c in candles if datetime.fromtimestamp(c['open_time'] / 1000).year == year]
            if year_candles:
                start_idx = candles.index(year_candles[0])
                end_idx = candles.index(year_candles[-1])
                if start_idx < len(equity_curve) and end_idx < len(equity_curve):
                    start_eq = equity_curve[start_idx] if start_idx < len(equity_curve) else BASE
                    end_eq = equity_curve[end_idx] if end_idx < len(equity_curve) else start_eq
                    ret = (end_eq - start_eq) / start_eq * 100
                    yearly_returns[year] = ret
        
        results[coin] = {
            'cagr': cagr,
            'dd': max_dd,
            'slr': sl_rate,
            'yearly': yearly_returns,
            'trades': trades,
        }
    
    return results


if __name__ == '__main__':
    from statistics import mean
    
    print("=" * 100)
    print("BACKTEST v12: Adaptive Strategy with Hold Mode")
    print("=" * 100)
    print("\nMarket Regime:")
    print("  BULL (BullScore >= 3) => HOLD MODE")
    print("  BEAR => SHORT MODE (Trading)")
    print("  SIDEWAY => CASH")
    print("  CHOPPY => SMALL SIZE / NO TRADE")
    print("\nHold Mode:")
    print("  - Entry: Buy once when transitioning to BULL")
    print("  - Exit: Close < MA50 (2 candles) OR MA20 crosses down MA50")
    print("=" * 100)
    
    results = run_backtest()
    
    avg_cagr = mean([r['cagr'] for r in results.values()])
    avg_dd = mean([r['dd'] for r in results.values()])
    avg_slr = mean([r['slr'] for r in results.values()])
    
    print(f"\nAverage CAGR: {avg_cagr:.1f}%")
    print(f"Average Max DD: {avg_dd:.1f}%")
    print(f"Average SL Rate: {avg_slr:.1f}%")
    
    print("\n" + "=" * 100)
    print("Per-Coin Results:")
    print("=" * 100)
    
    for coin, data in results.items():
        print(f"\n{coin}:")
        print(f"  CAGR: {data['cagr']:.1f}%")
        print(f"  Max DD: {data['dd']:.1f}%")
        print(f"  SL Rate: {data['slr']:.1f}%")
        print(f"  Yearly Returns:")
        for year, ret in sorted(data['yearly'].items()):
            print(f"    {year}: {ret:+.1f}%")
        
        # Trade breakdown
        hold_entries = sum(1 for t in data['trades'] if t['type'] == 'HOLD_ENTRY')
        hold_exits = sum(1 for t in data['trades'] if t['type'] == 'HOLD_EXIT')
        short_entries = sum(1 for t in data['trades'] if t['type'] == 'SHORT_ENTRY')
        short_sls = sum(1 for t in data['trades'] if t['type'] == 'SHORT_SL')
        short_trails = sum(1 for t in data['trades'] if t['type'] == 'SHORT_TRAIL')
        
        print(f"  Trades:")
        print(f"    Hold: {hold_entries} entries, {hold_exits} exits")
        print(f"    Short: {short_entries} entries, {short_sls} SL, {short_trails} trail")
    
    print("\n" + "=" * 100)
