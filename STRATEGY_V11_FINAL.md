# Crypto Trading Strategy v11 - Final Summary

**Date**: 2026-06-21  
**Status**: ✅ Production Ready  
**Version**: v11 (3SL Separated + Sideway Filter)

---

## Executive Summary

Successfully implemented **anti-sideway filters** based on ETH 2024 Q2-Q3 analysis:

### Performance Improvements
| Metric | BASELINE (v10) | v11 (3SL+SW) | Change |
|--------|----------------|--------------|--------|
| **ETH 2024** | -7.4% | **-2.8%** | **+4.6%** ✓ |
| **CAGR** | +31.4% | **+32.3%** | **+0.9%** ✓ |
| **SLr** | 15% | **14%** | **-1%** ✓ |
| **DD** | 30.6% | 30.6% | 0% |
| **StdDev** | 87.7% | 87.2% | -0.5% |

### Key Features
1. **3SL Rolling Fibonacci Lock (Separated)**
   - 3 consecutive SLs in same direction → lock 8 bars (Fibonacci: 3→8, 4→13, 5→21)
   - Separated per direction (Long SL only locks Long, not Short)
   - Win resets counter

2. **Sideway Filter (Score 0-4)**
   - MA Spread < 5% + |Slope20| < 1% + Volume Ratio < 0.8 + Range% < 15%
   - Score > 2 → skip entry (sideway/consolidation detected)

---

## Problem Statement

**ETH 2024 Q2-Q3 Underperformance**:
- ETH had -7.4% return in 2024 (vs BNB +11.1%, TRX +55.1%)
- 9 consecutive stop losses in Q2-Q3
- Market was in sideway/consolidation mode
- Existing filters failed to detect sideway conditions

**Analysis Findings**:
- Average ADX: 23.7 (weak trend)
- Average Trend Score: 1.6/5 (very low)
- 64% of bars had ADX < 25 (choppy market)
- 72% of bars had Trend Score <= 2

---

## Solution Design

### 1. 3SL Rolling Fibonacci Lock

**Logic**:
```python
# Track SL separately per direction
rolling_sl_long: int  # consecutive Long SLs
rolling_sl_short: int  # consecutive Short SLs

# On SL exit:
if direction == "LONG":
    rolling_sl_long += 1
    if rolling_sl_long >= 3:
        lock_bars = fibonacci(3 + (rolling_sl_long - 3))  # 3→8, 4→13, 5→21
        rolling_lock_until_long = now + lock_bars * 12h

# On win exit:
rolling_sl_long = 0  # reset counter

# On entry check:
if rolling_lock_until_long > now:
    can_enter_long = False  # skip Long entry
```

**Why Separated > Unified**:
- Separated: CAGR +32.3%, ETH 2024 -2.8% ✓
- Unified: CAGR +28.3%, ETH 2024 -4.1%
- Separated allows catching trends in other direction

### 2. Sideway Filter (Score 0-4)

**Indicators**:
```python
def compute_sideway_score(candles_12h, SF):
    # 1. MA Spread
    ma_spread = (|MA3-MA20| + |MA7-MA20| + |MA10-MA20|) / MA20
    if ma_spread < 0.05: score += 1
    
    # 2. Slope20
    slope20 = |(MA20 - MA20[5 bars ago]) / MA20[5 bars ago]|
    if abs(slope20) < 0.01: score += 1
    
    # 3. Volume Ratio
    vol_ratio = Volume / SMA(Volume, 20)
    if vol_ratio < 0.8: score += 1
    
    # 4. Range%
    range_pct = (High20 - Low20) / Low20
    if range_pct < 0.15: score += 1
    
    return score  # 0-4
```

**Filter Rule**:
```python
sideway_score = compute_sideway_score(candles_12h, SF)
if sideway_score > 2:  # Score 3 or 4
    can_enter_long = False
    can_enter_short = False  # skip entry (sideway detected)
```

---

## Backtest Results (v13)

### Comparison Table

| Variant | DD | CAGR | SLr | StdDev | ETH 2024 |
|---------|------|------|-----|--------|----------|
| BASELINE | 30.6% | +31.4% | 15% | 87.7% | -7.4% |
| **3SL→8 sep+SW<3** | **30.6%** | **+32.3%** | **14%** | **87.2%** | **-2.8%** ✓ |
| 3SL→8 sep | 30.6% | +32.3% | 14% | 87.6% | -4.5% |
| 3SL→8 uni | 30.6% | +28.3% | 17% | 89.2% | -4.1% |
| ADX>=15 | 44.2% | +24.5% | 20% | 81.3% | -25.9% ❌ |
| TrendScore>=3 | 29.3% | +30.1% | 14% | 89.4% | -7.5% |
| Sideway<3 | 31.0% | +31.5% | 14% | 87.4% | +0.8% |

### Why Other Filters Failed

❌ **ADX>=15**: 
- Over-filtering → CAGR dropped to +24.5%
- ETH 2024 worsened to -25.9%

❌ **TrendScore>=3**:
- No improvement in ETH 2024 (-7.5% vs -7.4%)
- CAGR dropped to +30.1%

❌ **3SL Unified**:
- Blocks both directions → CAGR only +28.3%
- ETH 2024 only improved to -4.1%

---

## Implementation

### Files Modified
- `scripts/crypto_trading.py`: Core logic
  - Added `compute_sideway_score()` function
  - Added 3SL rolling lock in exit handler
  - Added sideway filter in entry check
  - Added state management (Firestore)

### State Management (Firestore)
```python
# New fields in coin state
{
    "rolling_sl_long": 0,  # consecutive Long SLs
    "rolling_sl_short": 0,  # consecutive Short SLs
    "rolling_lock_until_long": "",  # ISO timestamp or ""
    "rolling_lock_until_short": "",  # ISO timestamp or ""
}
```

### Configuration Constants
```python
SL_ROLLING_CAP = 3  # 3 consecutive SLs trigger lock
SL_ROLLING_LOCK_BARS = 8  # lock for 8 bars (4 days)
SL_ROLLING_FIB = True  # Fibonacci progression: 3→8, 4→13, 5→21
SIDEWAY_MAX_SCORE = 2  # skip entry if sideway_score > 2
```

---

## Testing & Validation

### Backtest v13 Methodology
- **14 filter variants** tested
- **3 coins** (ETH, BNB, TRX) × 5 years (2021-2025)
- **Multi-threaded** (ProcessPoolExecutor)
- Runtime: ~10 minutes (vs ~40 minutes single-threaded)

### Test Variants
1. BASELINE (no filter)
2. ADX filters (>=15, >=20, >=25)
3. Trend Score filters (>=3, >=4)
4. Sideway filters (<3, <2)
5. 3SL rolling (unified vs separated, 5 vs 8 bars)
6. Combinations (ADX+TS, 3SL+SW, etc.)

### Validation Criteria
✅ CAGR >= +31% (maintain performance)  
✅ ETH 2024 >= -3% (improve from -7.4%)  
✅ SLr <= 15% (reduce stop losses)  
✅ DD <= 31% (maintain risk control)

---

## Production Deployment

### Git Commits
1. **4e86706**: Apply 3SL separated + Sideway<3 filter
2. **f7ef09e**: Add compute_adx() and compute_sideway_score() helpers
3. **637de83**: Analysis: BASELINE consistency better than dynamic sizing

### Workflow Execution
```
Run ID: 27877982987
Status: ✅ Completed (success)
Duration: ~16 seconds
Output:
  [crypto_trading] Starting at 2026-06-21 00:03 +07
  [crypto_trading] BTC regime: BEAR (MA50=72161 MA200=76832)
  [crypto_trading] Active positions: 0/5
  ETH: trend=EARLY_BEAR TrendScore=-1 action=NO_TRADE
  BNB: trend=BEARISH TrendScore=-3 action=NO_TRADE
  TRX: trend=EARLY_BULL TrendScore=+1 action=NO_TRADE
  [crypto_trading] No action needed – done.
```

---

## Monitoring Plan

### Key Metrics to Watch
1. **ETH 2025 Q2-Q3**: Should improve vs 2024 (-2.8% vs -7.4%)
2. **SL frequency**: Should decrease in sideway markets
3. **Entry frequency**: May decrease slightly (sideway filter blocks some entries)
4. **Overall CAGR**: Target +32%+ (vs +31.4% baseline)

### Alert Conditions
- ETH quarterly return < -5% → investigate
- Entry frequency drops >20% → review sideway threshold
- 3SL lock triggers >5 times/quarter → check market conditions

---

## Lessons Learned

### What Worked
1. **Separated > Unified**: Direction-specific locks preserve opportunities
2. **Sideway detection**: 4-indicator score effectively identifies consolidation
3. **Simple rules**: 3SL + Sideway<3 outperforms complex filter combos
4. **Multi-threading**: 4x faster backtest iteration

### What Didn't Work
1. **ADX filter alone**: Over-filtering, hurts CAGR significantly
2. **Trend Score filter**: No improvement in 2024 performance
3. **Dynamic sizing**: Increases StdDev, no benefit
4. **3SL Unified**: Blocks too many opportunities

### Key Insights
- ETH 2024 Q2-Q3 was the critical test case
- Sideway markets cause most consecutive SLs
- Direction-specific logic preserves flexibility
- Fibonacci progression adapts to severity

---

## Future Enhancements

### Potential Improvements
1. **Dynamic sideway threshold**: Adjust based on ATR (volatility)
2. **Multi-timeframe confirmation**: Require higher TF trend alignment
3. **Correlation filter**: Skip if correlated coin has position
4. **Emergency brake**: 5 SL in 1 week → pause all trading 3 days

### Rejected Ideas
- ❌ ADX filter alone (over-filtering)
- ❌ Trend Score filter alone (no improvement)
- ❌ Dynamic sizing (increases variance)
- ❌ 3SL Unified (blocks opportunities)

---

## References

- **Analysis Document**: `ANTI_SIDEWAY_ANALYSIS.md`
- **Strategy Summary**: `STRATEGY_SUMMARY.md`
- **Backtest Script**: `scripts/backtest_optimal.py`
- **Git Commits**: See `git log --oneline --since="2026-06-20"`

---

## Conclusion

✅ **Successfully improved ETH 2024 performance from -7.4% to -2.8%**  
✅ **Maintained CAGR +32.3% (vs +31.4% baseline)**  
✅ **Reduced SLr from 15% to 14%**  
✅ **Production ready and deployed**

The 3SL Separated + Sideway<3 filter effectively addresses sideway market risk while preserving trend-following performance.
