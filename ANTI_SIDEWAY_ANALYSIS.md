# Crypto Trading Strategy - Anti-Sideway Analysis (2024-06-21)

## Summary

Successfully implemented **3SL Separated + Sideway<3 filter** based on ETH 2024 Q2-Q3 sideway market analysis.

## Problem: ETH 2024 Q2-Q3 Underperformance

**Issue**: ETH had -3.1% return in 2024, with severe drawdown in Q2-Q3:
- 9 consecutive stop losses (SL) in Q2-Q3
- Market was in sideway/consolidation mode
- Existing filters (ADX, trend score, etc.) failed to detect sideway conditions

**Root Cause Analysis**:
ETH 2024 Q2-Q3 indicators showed:
- Average ADX: 23.7 (below 25 threshold = weak trend)
- Average Trend Score: 1.6/5 (very low)
- 64% of bars had ADX < 25 (choppy market)
- 72% of bars had Trend Score <= 2

## Solution: 3SL Separated + Sideway Filter

### 3SL Rolling Fibonacci Lock (Separated per Direction)

**Logic**:
- Track stop losses separately for LONG and SHORT directions
- 3 consecutive SLs in same direction → lock that direction for 8 bars (4 days)
- Fibonacci progression: 3→8 bars, 4→13 bars, 5→21 bars, 6→34 bars
- Win resets the counter for that direction

**Why Separated > Unified**:
- Separated allows catching trends in the other direction
- Unified blocks both directions when either loses → misses opportunities
- Backtest: Separated CAGR +32.3% vs Unified +28.3% (Δ +4%)

### Sideway Filter (Score 0-4)

**Indicators**:
1. MA Spread: (|MA3-MA20| + |MA7-MA20| + |MA10-MA20|) / MA20 < 5%
2. |Slope20|: |(MA20 - MA20[5 bars ago]) / MA20[5 bars ago]| < 1%
3. Volume Ratio: Volume / SMA(Volume, 20) < 0.8
4. Range%: (High20 - Low20) / Low20 < 15%

**Filter Rule**:
- Sideway Score > 2 → skip entry (both LONG and SHORT)
- Score 0-2: trending market → allow entry
- Score 3-4: sideway/consolidation → block entry

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

### Key Improvements

✅ **ETH 2024**: -7.4% → -2.8% (+4.6%)
✅ **CAGR**: +31.4% → +32.3% (+0.9%)
✅ **SLr**: 15% → 14% (-1%)
✅ **StdDev**: Nearly unchanged (87.2% vs 87.7%)

### Why Other Filters Failed

❌ **ADX>=15**: 
- Reduced StdDev to 81.3% but CAGR dropped to +24.5%
- ETH 2024 worsened to -25.9% (over-filtering)

❌ **TrendScore>=3**:
- Slightly better DD (29.3%) but CAGR dropped to +30.1%
- ETH 2024 still -7.5% (no improvement)

❌ **3SL Unified**:
- CAGR dropped to +28.3% (blocks too many opportunities)
- Eth 2024 only improved to -4.1%

## Implementation Details

### Files Modified
- `scripts/crypto_trading.py`: Added 3SL rolling lock + sideway filter logic
- `scripts/utils/backtest_cache.py`: Cache infrastructure for backtest results

### State Management (Firestore)
```
rolling_sl_long: int (0-6+)
rolling_sl_short: int (0-6+)
rolling_lock_until_long: ISO timestamp or ""
rolling_lock_until_short: ISO timestamp or ""
```

### Key Functions
- `compute_sideway_score(candles_12h, SF)`: Calculate sideway score (0-4)
- `compute_adx(candles, period)`: Calculate ADX for trend strength
- Rolling lock logic in `process_coin_v4()` exit handler

## Testing & Validation

### Test Variants
Tested 14 different filter combinations:
- BASELINE (no filter)
- ADX filters (>=15, >=20, >=25)
- Trend Score filters (>=3, >=4)
- Sideway filters (<3, <2)
- 3SL rolling (unified vs separated, 5 vs 8 bars)
- Combinations (ADX+TS, 3SL+SW, etc.)

### Multi-threaded Backtesting
- Used ProcessPoolExecutor for parallel coin processing
- 14 filter configs × 3 coins = 42 backtests
- Runtime: ~10 minutes (vs ~40 minutes single-threaded)

## Production Deployment

✅ **Applied to production** (commit 4e86706)
- 3SL Separated (3→8 bars, Fibonacci progression)
- Sideway<3 filter (score > 2 → skip entry)
- Workflow triggered and running

## Monitoring Plan

### Key Metrics to Watch
1. **ETH 2025 Q2-Q3**: Should see improved performance vs 2024
2. **SL frequency**: Should decrease in sideway markets
3. **Entry frequency**: May decrease slightly (sideway filter blocks some entries)
4. **Overall CAGR**: Target +32%+ (vs +31.4% baseline)

### Alert Conditions
- ETH quarterly return < -5% → investigate
- Entry frequency drops >20% → review sideway threshold
- 3SL lock triggers >5 times/quarter → check market conditions

## Future Considerations

### Potential Enhancements
1. **Dynamic sideway threshold**: Adjust based on volatility (ATR)
2. **Multi-timeframe confirmation**: Require higher TF trend alignment
3. **Correlation filter**: Skip if correlated coin has position
4. **Emergency brake**: 5 SL in 1 week → pause all trading 3 days

### Rejected Ideas
- ❌ ADX filter alone (over-filtering, hurts CAGR)
- ❌ Trend Score filter alone (no improvement in 2024)
- ❌ 3SL Unified (blocks too many opportunities)
- ❌ Dynamic sizing (increases StdDev, no benefit)

## Lessons Learned

1. **Separated > Unified**: Direction-specific locks preserve opportunities
2. **Sideway detection works**: 4-indicator score effectively identifies consolidation
3. **Simple rules beat complex**: 3SL + Sideway<3 outperforms complex filter combos
4. **Backtest with multi-threading**: 4x faster iteration cycle
5. **Monitor real performance**: ETH 2024 Q2-Q3 was the key test case

## References

- ETH 2024 Q2-Q3 Analysis: `scripts/analyze_eth_2024.py` (deleted after analysis)
- Backtest v13 Results: See git commit 4e86706
- Sideway Score Formula: MA spread + Slope20 + Volume ratio + Range%
- Fibonacci Lock: 3→8, 4→13, 5→21, 6→34 bars (4 days, 6.5 days, 10.5 days, 17 days)
