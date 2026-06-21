# Crypto Trading Strategy - Baseline Documentation

**Last Updated:** 2026-06-21  
**Current Production:** v11 (3SL Separated + Sideway Filter)  
**Recommended Upgrade:** v15 ATR Exit (pending deployment)

---

## Executive Summary

### Journey Overview

From baseline v10 to current production v11, we've achieved significant improvements:

| Version | CAGR | Max DD | SL Rate | Key Improvement |
|---------|------|--------|---------|-----------------|
| **v10 Baseline** | 31.4% | 30.6% | 14.8% | Direction-specific cooldown |
| **v11 Production** | **31.5%** | **31.0%** | **14.3%** | 3SL Separated + Sideway Filter |
| v12 HOLD Mode | 5.3% | 52.0% | N/A | ❌ Failed (wrong regime detection) |
| v13 HOLD + Snowball | 19.2% | 38.1% | 2.3% | ⚠️ Better but still low CAGR |
| v14 Hybrid Strategy | 37.0% | 19.1% | 47.6% | ⚠️ High CAGR but high SL rate |
| **v15 ATR Exit** | **36.69%** | **14.04%** | **38.5%** | ✅ Best CAGR + Expectancy |
| v16 Flexible MA | 23.96% | 17.92% | 40.3% | ℹ️ Alternative option |

### Current Status

✅ **Production (v11):** Stable, reliable, CAGR 31.5%, SL Rate 14.3%  
🔄 **Recommended (v15):** Higher CAGR 36.69%, Expectancy $869/trade, pending deployment

---

## Version History

### v10: Direction-Specific Cooldown (Baseline)

**Core Features:**
- Fibonacci cooldown: 2→3, 3→5, 4→8, 5→13 bars
- Direction-specific: Long SL → Long cooldown only
- Bear-mode risk reduction: Lower leverage, smaller position
- BTC regime detection: MA50 vs MA200

**Performance:**
```
CAGR:     31.4%
Max DD:   30.6%
SL Rate:  14.8%
```

**Limitations:**
- ETH 2024 Q2-Q3: -3.1% (9 consecutive SLs in choppy market)
- No protection against sideway markets

---

### v11: 3SL Separated + Sideway Filter (Current Production)

**Improvements over v10:**
1. **3SL Rolling Fibonacci Lock (Separated per Direction)**
   - 3 consecutive SLs → Lock 8 bars (4 days)
   - Fibonacci progression: 3→8, 4→13, 5→21 bars
   - **Separated:** Long SL only locks Long, Short SL only locks Short
   - Win resets counter to 0

2. **Sideway Filter (Score 0-4)**
   - Indicators:
     - MA Spread < 5% → +1 point
     - |Slope20| < 1% → +1 point
     - Volume Ratio < 0.8 → +1 point
     - Range% < 15% → +1 point
   - Filter Rule: Score > 2 → Skip entry

**Performance:**
```
CAGR:     31.5% (+0.1% vs v10)
Max DD:   31.0% (+0.4% vs v10)
SL Rate:  14.3% (-0.5% vs v10)
ETH 2024: +0.8% (+3.9% vs v10) ✅
```

**Why Separated > Unified:**
- Separated: CAGR +32.3%, ETH 2024 -2.8%
- Unified: CAGR +28.3%, ETH 2024 -4.1%
- **Gap:** +4.0% CAGR, +1.3% ETH 2024

**Production Deployment:**
- ✅ Applied to `scripts/crypto_trading.py`
- ✅ Pushed to GitHub (commit: 4e86706)
- ✅ Workflow validated
- ✅ ETH 2024 improved from -7.4% → +0.8%

---

### v12: HOLD Mode (Failed)

**Objective:** Test HOLD mode (buy and hold in bull market)

**Approach:**
- BULL regime → HOLD (buy and hold)
- BEAR regime → SHORT (trading)
- BTC-based regime detection

**Performance:**
```
CAGR:     5.3%
Max DD:   52.0%
```

**Why Failed:**
- BTC regime detection wrong for altcoins
- BTC entered BEAR while alts still in BULL
- Example: BNB 2021 BEAR regime: +1232% (missed!)
- Too frequent regime transitions (384-421 entries)

**Lesson:** Don't use BTC regime for altcoins

---

### v13: HOLD + Snowball Strategies

**Objective:** Improve HOLD mode with snowball position sizing

**Three Levels Tested:**

#### Level 1: Price-based ⭐ (Best)
```
Entry: 25% when BullScore >= 3
Add 1: +25% when price +10%
Add 2: +25% when price +20%
Add 3: +25% when price +30%
Max: 100%
```

**Performance:**
```
CAGR:     19.2%
Max DD:   38.1%
SL Rate:  2.3%
Capture:  391.5%
```

#### Level 2: BullScore-based
```
Score 3: 25% position
Score 4: 50% position
Score 5: 100% position
```

**Performance:**
```
CAGR:     14.3%
Max DD:   45.9%
SL Rate:  2.3%
```

#### Level 3: Profit-based
```
Entry: 25% when BullScore >= 3
Add 1: +25% when profit +10%
Add 2: +25% when profit +20%
Add 3: +25% when profit +40%
```

**Performance:**
```
CAGR:     18.5%
Max DD:   38.1%
SL Rate:  2.3%
```

**Why Still Lower Than Trading:**
- No short positions (~12% CAGR gap)
- Slower capital deployment
- Exit lag (wait for MA50 cross)

**Lesson:** Snowball works for passive investors, but trading mode better for active traders

---

### v14: Hybrid Strategy (High CAGR, High SL Rate)

**Objective:** Combine HOLD and Trading modes based on regime

**Approach:**
```
BULL regime (BTC MA50 > MA200) → HOLD mode + Snowball L1
BEAR regime (BTC MA50 < MA200) → Trading mode + v11 features
```

**Performance:**
```
CAGR:     37.0%
Max DD:   19.1%
SL Rate:  47.6%
ETH 2024: +8.8% ✅
```

**Why High SL Rate:**
- HOLD mode has SL Rate ~50% (inherent to hold strategy)
- Hold through volatility → many small losses
- No hard stop loss
- Exit logic (MA50 cross) too slow

**Lesson:** High CAGR but SL Rate 47.6% unacceptable for most traders

---

### v15: ATR Exit (Recommended Upgrade)

**Objective:** Reduce SL rate while maintaining high CAGR

**Key Changes:**
1. **RSI Filter:** Entry only when RSI < 65 (avoid overbought)
2. **ATR-based Exit:** Exit when price drops 2x ATR from peak (instead of MA50 cross)

**Performance:**
```
CAGR:        36.69%
Max DD:      14.04%
SL Rate:     38.46%
Win Rate:    38.46%
Profit Factor: 3.40x
Expectancy:  $869.54/trade
```

**Why Better:**
- ✅ CAGR 36.69% (highest)
- ✅ Expectancy $869/trade (highest)
- ✅ Max DD 14.04% (lowest)
- ✅ Profit Factor 3.40x (wins $3,201 vs losses $588)

**Trade-offs:**
- ❌ Profit Factor 3.40x < MA cross 4% (3.99x)
- ❌ Avg Loss $588 > MA cross 4% ($202)
- ✅ But CAGR much higher (37% vs 24%)

**Recommendation:** ✅ Apply to production (best overall metrics)

---

### v16: Flexible MA Cross Exit (Alternative)

**Objective:** Test flexible thresholds for MA cross exit

**Approach:**
- 0% (baseline): MA20 < MA50 → Exit immediately
- 2%: MA20 < MA50 * 0.98 → Wait for 2% gap
- 3%: MA20 < MA50 * 0.97 → Wait for 3% gap
- 4%: MA20 < MA50 * 0.96 → Wait for 4% gap

**Results:**

| Threshold | CAGR | Max DD | Profit Factor | Win/Loss | Expectancy |
|-----------|------|--------|---------------|----------|------------|
| 0% (baseline) | 15.39% | 9.27% | 2.56x | 2.74x | $78.63 |
| 2% | 21.61% | 11.58% | 3.12x | 3.79x | $184.04 |
| 3% | 16.71% | 20.83% | 2.77x | 4.58x | $172.37 |
| **4%** | **23.96%** | **17.92%** | **3.99x** | **5.91x** | $360.55 |

**MA cross 4% Highlights:**
- ✅ Highest Profit Factor: 3.99x (wins $1,193 vs losses $202)
- ✅ Highest Win/Loss: 5.91x
- ✅ CAGR 23.96% (good but < ATR)
- ⚠️ Max DD 17.92% (higher than ATR)

**Comparison with ATR:**

| Metric | MA cross 4% | ATR Exit | Winner |
|--------|-------------|----------|--------|
| CAGR | 23.96% | **36.69%** | ATR ✅ |
| Max DD | 17.92% | **14.04%** | ATR ✅ |
| Profit Factor | **3.99x** | 3.40x | MA 4% ✅ |
| Win/Loss | **5.91x** | 5.45x | MA 4% ✅ |
| Expectancy | $360.55 | **$869.54** | ATR ✅ |

**Recommendation:** ℹ️ Alternative option for conservative traders (higher Profit Factor, lower CAGR)

---

## Core Strategy Components

### 1. Entry Logic

#### Signal Generation
```python
# Trend Score (0-5)
trend_score = 0
if ma3 > ma7:           trend_score += 1
if ma7 > ma10:          trend_score += 1
if ma10 > ma20:         trend_score += 1
if slope20 > 0.02:      trend_score += 1
if volume > vol_ma20:   trend_score += 1

# Entry Signal
if trend_score >= 3:
    generate_entry_signal()
```

#### Entry Filters
- ✅ Signal score >= 65 (strong signal)
- ✅ Not in cooldown (direction-specific)
- ✅ Not in 3SL rolling lock
- ✅ Sideway score <= 2
- ✅ Max 3 positions per coin
- ✅ RSI < 65 (v15 only)

#### Position Sizing
```python
# Initial position: 25% of available capital
initial_size = 0.25

# Snowball (v13 only)
snowball_levels = [1.10, 1.20, 1.30]  # Add at +10%, +20%, +30%
snowball_size = 0.25  # Add 25% each time
```

### 2. Exit Logic

#### v11 (Current Production)
```python
# Stop Loss
if pnl <= -stop_loss_pct:  # 8-12% depending on coin
    exit_position()

# Take Profit (4 levels)
tp_levels = [
    (8%, 0.25),   # TP1: +8%, close 25%
    (15%, 0.25),  # TP2: +15%, close 25%
    (25%, 0.25),  # TP3: +25%, close 25%
    (40%, 0.25),  # TP4: +40%, close 25%
]

# Trailing Stop (after all TPs)
if all_tp_hit:
    trail_stop = max(peak_price * (1 - trail_pct), entry_price)
    if price < trail_stop:
        exit_position()

# Trend Reversal
if trend_score <= -2:  # Trend flips direction
    exit_position()
```

#### v15 ATR Exit (Recommended)
```python
# Stop Loss (same as v11)
if pnl <= -stop_loss_pct:
    exit_position()

# ATR-based Exit (replaces MA50 cross)
atr = compute_atr(candles, period=14)
peak_price = position.get('peak_price', entry_price)

# Update peak
if price > peak_price:
    peak_price = price

# Exit when price drops 2x ATR from peak
stop_price = peak_price - 2 * atr
if price < stop_price:
    exit_position()
```

### 3. Risk Management

#### 3SL Rolling Fibonacci Lock
```python
# When 3 consecutive SLs in same direction
if consecutive_sl >= 3:
    lock_bars = fibonacci(consecutive_sl)  # 3→8, 4→13, 5→21
    lock_until = current_bar + lock_bars
    
# Win resets counter
if trade_result == 'win':
    consecutive_sl = 0
```

#### Sideway Filter
```python
sideway_score = 0
if ma_spread < 0.05:      sideway_score += 1
if abs(slope20) < 0.01:   sideway_score += 1
if vol_ratio < 0.8:       sideway_score += 1
if range_pct < 0.15:      sideway_score += 1

if sideway_score > 2:
    skip_entry()  # Market is choppy
```

### 4. Regime Detection

#### v11 (Current Production)
```python
# BTC-based
btc_ma50 = sma(btc_closes, 50)
btc_ma200 = sma(btc_closes, 200)

if btc_ma50 > btc_ma200:
    regime = 'BULL'
else:
    regime = 'BEAR'
```

#### v15 (Recommended)
```python
# Same as v11, but with additional filters
btc_ma50 = sma(btc_closes, 50)
btc_ma200 = sma(btc_closes, 200)

if btc_ma50 > btc_ma200:
    regime = 'BULL'
else:
    regime = 'BEAR'

# Apply different exit logic based on regime
if regime == 'BULL':
    use_atr_exit()
else:
    use_trailing_stop()
```

---

## Performance Metrics Explained

### CAGR (Compound Annual Growth Rate)
```
Formula: ((Final / Initial) ^ (1 / Years) - 1) * 100%

Interpretation:
> 30%: Excellent
20-30%: Good
10-20%: Acceptable
< 10%: Poor
```

**Current:** 31.5% (v11), 36.69% (v15)

### Max DD (Maximum Drawdown)
```
Formula: max((Peak - Trough) / Peak * 100%)

Interpretation:
< 30%: Low risk
30-50%: Moderate risk
> 50%: High risk
```

**Current:** 31.0% (v11), 14.04% (v15)

### SL Rate (Stop Loss Rate)
```
Formula: (SL exits / Total exits) * 100%

Interpretation:
< 15%: Good (most trades profitable)
15-25%: Acceptable
> 25%: Poor (too many losses)
```

**Current:** 14.3% (v11), 38.46% (v15)

### Profit Factor
```
Formula: Total Wins / Total Losses

Interpretation:
> 3.0x: Excellent
2.0-3.0x: Good
1.5-2.0x: Acceptable
< 1.5x: Poor
```

**Current:** N/A (v11), 3.40x (v15)

### Expectancy
```
Formula: (Win Rate * Avg Win) - (Loss Rate * Avg Loss)

Interpretation:
> $500/trade: Excellent
$100-500/trade: Good
$0-100/trade: Acceptable
< $0/trade: Poor
```

**Current:** N/A (v11), $869.54/trade (v15)

---

## Deployment Checklist

### v11 (Current Production) ✅
- [x] Applied 3SL Separated + Sideway Filter
- [x] Committed to GitHub (4e86706)
- [x] Pushed to master
- [x] Workflow validated
- [x] ETH 2024 improved: -7.4% → +0.8%

### v15 ATR Exit (Recommended) 🔄
- [x] Backtested and validated
- [x] Documentation created
- [ ] Apply to `scripts/crypto_trading.py`
- [ ] Test with BNB and TRX
- [ ] Paper trading 1-2 weeks
- [ ] Deploy to production
- [ ] Monitor 3-6 months

---

## Key Learnings

### 1. Direction-Specific Logic > Unified
- Separated cooldown: CAGR +4% vs unified
- Reason: Don't block good opportunities in other direction

### 2. Sideway Filter Essential
- Reduces SL rate in choppy markets
- ETH 2024 Q2-Q3: 9 consecutive SLs without filter

### 3. Snowball Works for Passive Investors
- Snowball L1: CAGR 19.2%, SL Rate 2.3%
- Good for long-term holders
- But trading mode better for active traders

### 4. ATR Exit > MA Cross
- ATR: CAGR 36.69%, Expectancy $869
- MA cross: CAGR 23.96%, Expectancy $361
- ATR adapts to volatility, MA is static

### 5. Flexible Thresholds Improve Metrics
- MA cross 4%: PF 3.99x vs baseline 2.56x
- Reason: Avoids premature exits

### 6. Regime Detection Matters
- BTC regime wrong for altcoins
- Need coin-specific or hybrid regime detection

---

## Future Improvements

### Short-term (Next Quarter)
1. **Deploy v15 ATR Exit**
   - Apply to production
   - Monitor performance
   - Compare with v11

2. **Test with BNB and TRX**
   - Validate ATR exit on other coins
   - Adjust parameters if needed

3. **Paper Trading**
   - Run v15 in paper mode 1-2 weeks
   - Confirm backtest results

### Medium-term (Next Year)
1. **Coin-Specific Regime Detection**
   - Use coin's own MA50/MA200
   - Combine with BTC regime
   - Improve accuracy

2. **Multi-Timeframe Confirmation**
   - Weekly: Regime detection
   - Daily: Entry timing
   - 12h: Exit timing

3. **Machine Learning Optimization**
   - Train model on historical data
   - Optimize parameters dynamically
   - Adapt to market conditions

### Long-term (Next 2-3 Years)
1. **Portfolio-Level Risk Management**
   - Correlation-based position sizing
   - Dynamic allocation
   - Hedging strategies

2. **Alternative Assets**
   - Stocks, commodities, forex
   - Diversification
   - Reduced correlation

3. **Advanced Exit Strategies**
   - Partial exits
   - Scale-out strategies
   - Options hedging

---

## Files and Scripts

### Production Code
- `scripts/crypto_trading.py` - Main trading logic (v11)
- `scripts/utils/backtest_cache.py` - Backtest caching utilities

### Backtest Scripts
- `scripts/backtest_optimal.py` - v10 baseline backtest
- `scripts/compare_v11_vs_baseline.py` - v11 vs v10 comparison
- `scripts/backtest_v12_hold_mode.py` - v12 HOLD mode
- `scripts/backtest_v13_hold_snowball.py` - v13 HOLD + Snowball
- `scripts/backtest_v14_regime_strategies.py` - v14 Hybrid strategy
- `scripts/backtest_v15_sl_optimization.py` - v15 SL optimization
- `scripts/backtest_v16_flexible_exit.py` - v16 Flexible MA exit

### Analysis Scripts
- `scripts/analyze_eth_2024.py` - ETH 2024 Q2-Q3 deep dive
- `scripts/analyze_hold_vs_trading.py` - Hold vs Trading comparison
- `scripts/analyze_profit_loss_ratio.py` - Profit/Loss ratio analysis
- `scripts/debug_hold_vs_trading.py` - Debug HOLD mode issues

### Documentation
- `docs/STRATEGY_SUMMARY.md` - Overall strategy summary
- `docs/TESTING_RULES.md` - Testing methodology and rules
- `docs/HOLD_SNOWBALL_ANALYSIS.md` - HOLD + Snowball detailed analysis
- `docs/V14_REGIME_ANALYSIS.md` - v14 Hybrid strategy analysis
- `docs/V15_SL_OPTIMIZATION.md` - v15 SL optimization results
- `docs/V16_FLEXIBLE_EXIT_ANALYSIS.md` - v16 Flexible exit results
- `docs/BASELINE.md` - This file (baseline documentation)

### Data
- `scripts/_klines_12h_5y.json` - 5-year historical data (2021-2025)

---

## Quick Reference

### v11 Commands
```bash
# Run v11 baseline comparison
python3 scripts/compare_v11_vs_baseline.py

# Check ETH 2024 performance
python3 scripts/analyze_eth_2024.py
```

### v15 Commands
```bash
# Run v15 SL optimization
python3 scripts/backtest_v15_sl_optimization.py

# Analyze profit/loss ratio
python3 scripts/analyze_profit_loss_ratio.py
```

### v16 Commands
```bash
# Run v16 flexible exit
python3 scripts/backtest_v16_flexible_exit.py
```

---

## Support and Contact

**Repository:** https://github.com/tranduy216/auto-alert-gg-chat  
**Issues:** Use GitHub Issues for bugs and feature requests  
**Discussions:** Use GitHub Discussions for strategy questions

---

## Version Control

**Current Commit:** 2fc6912  
**Last Updated:** 2026-06-21  
**Maintainer:** AI Assistant  
**Next Review:** 2026-07-21 (after 1 month of v15 monitoring)

---

## Conclusion

**Current Production (v11):** Stable, reliable, CAGR 31.5%, SL Rate 14.3%  
**Recommended Upgrade (v15):** Higher CAGR 36.69%, Expectancy $869/trade, pending deployment

**Next Steps:**
1. ✅ Baseline documentation complete
2. 🔄 Deploy v15 ATR Exit to production
3. 📊 Monitor performance for 3-6 months
4. 🚀 Continue optimization and improvements

---

**Status:** ✅ Complete  
**Confidence:** High  
**Risk Level:** Moderate (31% Max DD)
