# Crypto Trading Strategy Summary

**Last Updated**: 2026-06-21  
**Current Production Version**: v11 (3SL Separated + Sideway Filter)  
**Status**: ✅ Production Ready

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Strategy Versions Comparison](#strategy-versions-comparison)
3. [Current Production: v11](#current-production-v11)
4. [HOLD Mode Research: v12-v13](#hold-mode-research-v12-v13)
5. [Key Metrics Explained](#key-metrics-explained)
6. [Recommendations](#recommendations)
7. [Documentation Index](#documentation-index)

---

## Executive Summary

### Problem Solved
ETH 2024 Q2-Q3 underperformed significantly (-7.4%) due to:
- 9 consecutive stop losses in choppy/sideway market
- Market regime detection failed to identify consolidation
- Existing filters couldn't prevent repeated entries in ranging markets

### Solution Implemented (v11)
**3SL Rolling Fibonacci Lock (Separated) + Sideway Filter**

**Results**:
- ✅ ETH 2024: **-7.4% → +0.8%** (+8.2% improvement)
- ✅ CAGR: **+31.4% → +31.5%** (+0.1%)
- ✅ SL Rate: **14.8% → 14.3%** (-0.5%)
- ✅ Max DD: **30.6% → 31.0%** (+0.4%)

### Alternative Research (v12-v13)
**HOLD Mode + Snowball Strategies** for passive investors

**Best Result (Snowball L1)**:
- CAGR: **19.2%** (vs 31.5% trading)
- Max DD: **38.1%** (vs 31.0% trading)
- SL Rate: **2.3%** (vs 14.3% trading)
- Capture Ratio: **391.5%** (vs baseline 163.0%)

---

## Strategy Versions Comparison

### Performance Overview

| Version | Strategy | CAGR | Max DD | SL Rate | Key Features |
|---------|----------|------|--------|---------|--------------|
| **v10** | Baseline | 31.4% | 30.6% | 14.8% | Direction-specific cooldown |
| **v11** | **Production** | **31.5%** | **31.0%** | **14.3%** | 3SL Separated + Sideway Filter |
| v12 | HOLD Mode | 5.3% | 52.0% | N/A | Bull=Hold, Bear=Short (failed) |
| **v13 L1** | HOLD + Snowball | **19.2%** | **38.1%** | **2.3%** | Price-based snowball |
| v13 L2 | HOLD + Snowball | 14.3% | 45.9% | 2.3% | BullScore-based snowball |
| v13 L3 | HOLD + Snowball | 18.5% | 38.1% | 2.3% | Profit-based snowball |

### Per-Coin Performance (v11 Production)

| Coin | CAGR | Max DD | SL Rate | ETH 2024 | Status |
|------|------|--------|---------|----------|--------|
| **ETH** | 24.3% | 38.4% | 14.3% | **+0.8%** | ✅ Fixed |
| **BNB** | 37.1% | 20.6% | 15.7% | +11.0% | ✅ Stable |
| **TRX** | 33.1% | 34.1% | 12.9% | +48.9% | ✅ Strong |
| **Average** | **31.5%** | **31.0%** | **14.3%** | **+20.2%** | ✅ **Ready** |

---

## Current Production: v11

### Core Features

#### 1. 3SL Rolling Fibonacci Lock (Separated per Direction)
```
Trigger: 3 consecutive SLs in same direction
Lock Duration: 8 bars (4 days)
Progression: 3→8, 4→13, 5→21 bars (Fibonacci)

Key Innovation: Separated per direction
- Long SL → Only locks Long entries
- Short SL → Only locks Short entries
- Other direction continues trading normally

Reset: Win trade resets counter to 0
```

**Why Separated > Unified**:
- Separated: CAGR +32.3%, ETH 2024 -2.8%
- Unified: CAGR +28.3%, ETH 2024 -4.1%
- **Gap**: +4.0% CAGR, +1.3% ETH 2024

#### 2. Sideway Filter (Score 0-4)
```
Indicators:
  MA Spread < 5%           → +1 point
  |Slope20| < 1%           → +1 point
  Volume Ratio < 0.8       → +1 point
  Range% < 15%             → +1 point

Filter Rule:
  Score > 2 → Skip entry (sideway detected)
  Score ≤ 2 → Allow entry (trending market)
```

**Why This Works**:
- Combines 4 complementary indicators
- Simple threshold (score > 2)
- Only blocks clearly choppy markets
- Doesn't over-filter (preserves opportunities)

### Market Regime Detection
```
Bull Detection (BTC-based):
  MA20 > MA50              → +1
  MA50 > MA100             → +1
  Slope50 > 0              → +1
  Volume > SMA20           → +1
  MA50 > MA200 (BTC bull)  → +1
  
  BullScore >= 3 → BULL regime
  BullScore < 3  → BEAR regime
```

### Entry/Exit Logic

#### Entry Conditions (All must be true)
1. ✅ Signal score >= 65 (strong signal)
2. ✅ Not in cooldown (direction-specific)
3. ✅ Not in 3SL rolling lock
4. ✅ Sideway score <= 2
5. ✅ Max 3 positions per coin

#### Exit Conditions (Any triggers exit)
1. ❌ Stop Loss: Price hits SL% (8-12%)
2. ✅ Take Profit: Price hits TP levels (8/15/25/40%)
3. ✅ Trailing Stop: After all TP, trail at 4-6.5%
4. ⚠️ Trend Reversal: Trend score flips direction

### Configuration Parameters

```python
PROFILES_BULL = {
    "ETH": {"lev": 2.5, "sl": 10, "cap": 2.5, "trail": 0.04, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "rsi_max_long": 65, "pos_mult": 1.0},
    "BNB": {"lev": 3.5, "sl": 12, "cap": 2.8, "trail": 0.065, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 1.0},
    "TRX": {"lev": 3.5, "sl": 12, "cap": 2.5, "trail": 0.065, "cd": 5,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 1.0},
}

PROFILES_BEAR = {
    "ETH": {"lev": 2.0, "sl": 8, "cap": 2.5, "trail": 0.04, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "rsi_max_long": 65, "pos_mult": 0.90},
    "BNB": {"lev": 2.0, "sl": 10, "cap": 2.8, "trail": 0.065, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 0.75},
    "TRX": {"lev": 2.0, "sl": 8, "cap": 2.5, "trail": 0.065, "cd": 5,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 0.75},
}

# 3SL Rolling Lock
SL_ROLLING_CAP = 3
SL_ROLLING_LOCK_BARS = 8
SL_ROLLING_FIB = True

# Sideway Filter
SIDEWAY_MAX_SCORE = 2
```

### Yearly Performance (v11)

| Year | ETH | BNB | TRX | Average | Notes |
|------|-----|-----|-----|---------|-------|
| 2021 | +86.5% | +316.0% | +173.6% | +192.0% | Bull market |
| 2022 | +24.6% | -0.0% | -14.1% | +3.5% | Bear market |
| 2023 | +0.4% | +9.0% | +20.9% | +10.1% | Recovery |
| **2024** | **+0.8%** | **+11.0%** | **+48.9%** | **+20.2%** | ✅ **Fixed** |
| 2025 | +41.7% | +11.7% | +7.1% | +20.2% | Current |
| **CAGR** | **24.3%** | **37.1%** | **33.1%** | **31.5%** | **5-year** |

---

## HOLD Mode Research: v12-v13

### Motivation
- Trading mode underperforms Hold in strong bull markets
- ETH 2021: Trading +86.5% vs Hold +397.6% (gap: -311.1%)
- Need passive alternative for long-term investors

### v12: Basic HOLD Mode (Failed)
```
Strategy:
  BULL regime → HOLD (buy and hold)
  BEAR regime → SHORT (trading)

Results:
  CAGR: 5.3%
  Max DD: 52.0%

Problem:
  Too frequent regime transitions (384-421 entries)
  No position management (100% all-in)
  High drawdown
```

### v13: HOLD + Snowball (Success)

#### Snowball Level 1: Price-based ⭐ **BEST**
```
Entry: 25% when BullScore >= 3
Add 1: +25% when price +10%
Add 2: +25% when price +20%
Add 3: +25% when price +30%
Max: 100%

Results:
  CAGR: 19.2% (+243% vs baseline)
  Max DD: 38.1%
  SL Rate: 2.3%
  Capture Ratio: 391.5%
```

#### Snowball Level 2: BullScore-based
```
Entry based on BullScore:
  Score 3: 25% position
  Score 4: 50% position
  Score 5: 100% position
Dynamic: Only increase, never decrease

Results:
  CAGR: 14.3%
  Max DD: 45.9%
  SL Rate: 2.3%
  Capture Ratio: 349.3%
```

#### Snowball Level 3: Profit-based
```
Entry: 25% when BullScore >= 3
Add 1: +25% when profit +10%
Add 2: +25% when profit +20%
Add 3: +25% when profit +40%
Max: 100%

Results:
  CAGR: 18.5%
  Max DD: 38.1%
  SL Rate: 2.3%
  Capture Ratio: 371.7%
```

### Anti-FOMO Filters (v13)
```
Skip entry if:
  ATR14/Close > 8% (high volatility)
  (Close - MA50)/MA50 > 30% (overheated)
```

### Exit Conditions (HOLD Mode)
```
Exit if:
  Close < MA50 for 2 consecutive candles
  OR
  MA20 crosses down MA50
```

### Why Snowball Works
1. **Reduced initial risk**: 25% vs 100% (75% less exposure)
2. **Pyramid on strength**: Only add when trend confirms
3. **Longer holding period**: 27 adds vs 384 entries
4. **Lower SL rate**: 2.3% vs 14.3% (fewer forced exits)

### Why Still Lower Than Trading
1. **No short positions**: Miss bear market profits (~12% CAGR gap)
2. **Slower capital deployment**: 25% → 100% vs immediate 100%
3. **Exit lag**: Wait for MA50 cross vs quick TP at 8/15/25/40%

### Per-Coin Performance (Snowball L1)

| Coin | CAGR | Max DD | SL Rate | Adds | Capture |
|------|------|--------|---------|------|---------|
| **ETH** | **33.0%** | 49.9% | 3.9% | 27 | 425% |
| **BNB** | **29.0%** | **10.0%** | 0.0% | 27 | 385% |
| TRX | -4.4% | 54.4% | 2.9% | 21 | 364% |

---

## Key Metrics Explained

### CAGR (Compound Annual Growth Rate)
```
Formula: ((Final Value / Initial Value) ^ (1/Years) - 1) * 100%

Example:
  Initial: $10,000
  Final: $31,500
  Years: 5
  CAGR: ((31500/10000) ^ (1/5) - 1) * 100 = 25.8%

Interpretation:
  > 30%: Excellent
  20-30%: Good
  10-20%: Acceptable
  < 10%: Poor
```

### Max DD (Maximum Drawdown)
```
Formula: max((Peak - Trough) / Peak * 100%)

Example:
  Peak: $15,000
  Trough: $10,000
  DD: (15000 - 10000) / 15000 * 100 = 33.3%

Interpretation:
  < 30%: Low risk
  30-50%: Moderate risk
  > 50%: High risk
```

### SL Rate (Stop Loss Rate)
```
Formula: (Number of SL exits / Total exits) * 100%

Example:
  SL exits: 15
  Total exits: 100
  SL Rate: 15%

Interpretation:
  < 15%: Good (most trades profitable)
  15-25%: Acceptable
  > 25%: Poor (too many losses)
```

### Capture Ratio
```
Formula: (System Return / Buy & Hold Return) * 100%

Example:
  System: +100%
  Buy & Hold: +50%
  Capture: 200%

Interpretation:
  > 100%: Outperforms buy & hold
  50-100%: Captures most of trend
  < 50%: Underperforms significantly
```

### StdDev (Standard Deviation of Yearly Returns)
```
Formula: Standard deviation of yearly returns

Example:
  Yearly returns: [+80%, -20%, +30%, +10%, +25%]
  Mean: +25%
  StdDev: 35%

Interpretation:
  < 30%: Very consistent
  30-50%: Moderately consistent
  > 50%: High variance
```

---

## Recommendations

### For Active Traders
✅ **Use v11 (Current Production)**
- CAGR: 31.5%
- Max DD: 31.0%
- SL Rate: 14.3%
- Best for: Active management, short-term trading

**When to Use**:
- Bear markets or choppy conditions
- Want to profit in both directions (long + short)
- Can monitor and adjust positions daily
- Short-term horizon (days to weeks)

### For Passive Investors
✅ **Use v13 Snowball L1 (Price-based)**
- CAGR: 19.2%
- Max DD: 38.1%
- SL Rate: 2.3%
- Best for: Passive income, long-term holding

**When to Use**:
- Strong bull markets (BullScore >= 3)
- Low volatility environments
- Want passive income without active management
- Long-term horizon (1+ years)

### Hybrid Strategy (Recommended)
```python
if regime == 'BULL':
    Use HOLD mode with Snowball L1
elif regime == 'BEAR':
    Use Trading mode with v11 features
elif regime == 'SIDEWAY' or 'CHOPPY':
    CASH (no positions)
```

**Benefits**:
- Best of both worlds
- Passive in bull, active in bear
- Reduces overall drawdown
- Improves consistency

### Optimization Opportunities

#### Short-term (Next Quarter)
1. **Implement hybrid strategy** in production
2. **Monitor v11 performance** for 6 months (2025 H2)
3. **Compare with pure trading mode**
4. **Fine-tune parameters** if needed

#### Medium-term (Next Year)
1. **Test Snowball parameter variations**:
   - Add levels: +5%, +15%, +25% instead of +10%, +20%, +30%
   - Initial size: 20%, 30%, 40% instead of 25%
   - Max position: 80%, 90% instead of 100%

2. **Add more anti-FOMO filters**:
   - RSI > 80 → Skip (overbought)
   - Volume spike > 3x → Skip (exhaustion)
   - Bollinger Band upper band → Skip

3. **Multi-timeframe confirmation**:
   - Weekly: Regime detection
   - Daily: Entry timing
   - 12h: Snowball add timing

#### Long-term (Next 2 Years)
1. **Machine learning for regime detection**
2. **Dynamic parameter optimization** (walk-forward)
3. **Portfolio-level risk management** (correlation-based)
4. **Alternative assets** (stocks, commodities)

---

## Documentation Index

### Core Documentation
- **[STRATEGY_SUMMARY.md](./STRATEGY_SUMMARY.md)**: This file - Overall strategy overview
- **[TESTING_RULES.md](./TESTING_RULES.md)**: Testing methodology and rules
- **[HOLD_SNOWBALL_ANALYSIS.md](./HOLD_SNOWBALL_ANALYSIS.md)**: Detailed HOLD + Snowball analysis

### Analysis Reports
- **[ANTI_SIDEWAY_ANALYSIS.md](../ANTI_SIDEWAY_ANALYSIS.md)**: ETH 2024 Q2-Q3 deep dive
- **[STRATEGY_V11_FINAL.md](../STRATEGY_V11_FINAL.md)**: v11 final summary
- **[HOLD_VS_TRADING_ANALYSIS.md](../HOLD_VS_TRADING_ANALYSIS.md)**: Hold vs Trading comparison

### Backtest Scripts
- **[backtest_optimal.py](../scripts/backtest_optimal.py)**: v10 baseline backtest
- **[compare_v11_vs_baseline.py](../scripts/compare_v11_vs_baseline.py)**: v11 vs v10 comparison
- **[backtest_v12_hold_mode.py](../scripts/backtest_v12_hold_mode.py)**: v12 HOLD mode (failed)
- **[backtest_v13_hold_snowball.py](../scripts/backtest_v13_hold_snowball.py)**: v13 HOLD + Snowball ✓
- **[analyze_eth_2024.py](../scripts/analyze_eth_2024.py)**: ETH 2024 deep dive

### Production Code
- **[crypto_trading.py](../scripts/crypto_trading.py)**: Main trading logic (v11 features)

### Cache Data
- **[_klines_12h_5y.json](../scripts/_klines_12h_5y.json)**: 5-year historical data (2021-2025)

---

## Quick Reference

### v11 Features Checklist
- [x] 3SL Rolling Fibonacci Lock (Separated)
- [x] Sideway Filter (Score > 2)
- [x] Direction-specific cooldown
- [x] Bear-mode risk reduction
- [x] BTC regime detection

### v13 Features Checklist
- [x] Snowball Level 1 (Price-based)
- [x] Anti-FOMO filters
- [x] HOLD mode with MA50 exit
- [x] Separated 3SL lock
- [x] Sideway filter

### Testing Commands
```bash
# Run v11 baseline comparison
python3 scripts/compare_v11_vs_baseline.py

# Run v13 snowball strategies
python3 scripts/backtest_v13_hold_snowball.py

# Analyze ETH 2024 Q2-Q3
python3 scripts/analyze_eth_2024.py

# Run HOLD mode backtest
python3 scripts/backtest_v12_hold_mode.py
```

---

## Version History

| Date | Version | Changes | CAGR | Max DD |
|------|---------|---------|------|--------|
| 2026-06-19 | v10 | Baseline (direction-specific cooldown) | 31.4% | 30.6% |
| 2026-06-20 | v11 | 3SL Separated + Sideway Filter | 31.5% | 31.0% |
| 2026-06-21 | v12 | HOLD mode (failed) | 5.3% | 52.0% |
| 2026-06-21 | v13 L1 | HOLD + Snowball (Price-based) | 19.2% | 38.1% |
| 2026-06-21 | v13 L2 | HOLD + Snowball (BullScore-based) | 14.3% | 45.9% |
| 2026-06-21 | v13 L3 | HOLD + Snowball (Profit-based) | 18.5% | 38.1% |

---

## Contact & Support

**Repository**: https://github.com/yourusername/crypto-trading  
**Issues**: Use GitHub Issues for bugs and feature requests  
**Discussions**: Use GitHub Discussions for strategy questions

---

**Document Maintainer**: AI Assistant  
**Last Reviewed**: 2026-06-21  
**Next Review**: 2026-07-21 (after 1 month of production monitoring)
