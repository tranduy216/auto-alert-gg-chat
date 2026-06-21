# Testing Rules - Anti-Sideway & Snowball Strategies

## 1. Test Environment Setup

### Cache Data
- File: `scripts/_klines_12h_5y.json`
- Format: `{symbol}_4000_1609434000000`
- Period: 5 years (2021-2025)
- Timeframe: 12h candles
- Coins: ETH, BNB, TRX, BTC (for regime detection)

### Backtest Parameters
- Initial Capital: $10,000
- Fee Rate: 0.05% per trade
- Position Size: Based on regime and strategy
- Max Drawdown: Calculated from equity peak

### Metrics
- **CAGR**: Compound Annual Growth Rate
- **Max DD**: Maximum Drawdown from peak
- **SL Rate**: Stop Loss frequency
- **Capture Ratio**: System Return / Buy & Hold Return
- **StdDev**: Standard deviation of yearly returns (consistency)

---

## 2. Market Regime Detection (BTC-based)

### Bull Score Calculation (0-5)
```
MA20 > MA50              → +1
MA50 > MA100             → +1
Slope50 > 0              → +1  (MA50 trend)
Volume > SMA20 Volume    → +1
MA50 > MA200 (BTC bull)  → +1
```

### Regime Classification
- **BULL** (BullScore >= 3) → HOLD MODE
- **BEAR** → SHORT MODE (Trading)
- **SIDEWAY** (ADX < 20, SidewayScore >= 3) → CASH
- **CHOPPY** (ADX >= 20, SidewayScore >= 3) → SMALL SIZE / NO TRADE

### Sideway Score (0-4)
```
MA Spread < 5%           → +1
|Slope20| < 1%           → +1
Volume Ratio < 0.8       → +1
Range% < 15%             → +1
```

---

## 3. HOLD Mode Rules

### Entry
- Trigger: Transition to BULL regime
- Anti-FOMO Filter:
  - ATR14/Close > 8% → Skip
  - (Close - MA50)/MA50 > 30% → Skip (overheated)

### Exit Conditions
1. Close < MA50 for 2 consecutive candles
2. MA20 crosses down MA50

### Snowball Strategies

#### Level 0: Baseline (No Snowball)
- Initial: 100% position
- No adds

#### Level 1: Price-based
- Initial: 25%
- Add at +10%: +25%
- Add at +20%: +25%
- Add at +30%: +25%
- Max: 100%

#### Level 2: BullScore-based
- Score 3: 25%
- Score 4: 50%
- Score 5: 100%
- Dynamic: Only increase, never decrease during hold

#### Level 3: Profit-based
- Initial: 25%
- Profit +10%: +25%
- Profit +20%: +25%
- Profit +40%: +25%
- Max: 100%

---

## 4. BEAR Mode (Trading) - v11 Features

### Direction-Specific Cooldown
- Fibonacci: 2→3, 3→5, 4→8, 5→13 bars
- Long SL → Long cooldown only
- Short SL → Short cooldown only
- Win resets counter

### 3SL Rolling Lock (Separated)
- 3 consecutive SLs in same direction → lock 8 bars
- Fibonacci progression: 3→8, 4→13, 5→21 bars
- Separated per direction (Long SL only locks Long)

### Sideway Filter
- SidewayScore > 2 → Skip entry
- Only in BEAR mode

---

## 5. Backtest Comparison Results

### v11 (Trading) vs v13 (HOLD + Snowball)

| Strategy | CAGR | Max DD | SL Rate | Capture Ratio |
|----------|------|--------|---------|---------------|
| **v11 Trading (Baseline)** | **31.5%** | **31.0%** | **14.3%** | N/A |
| v13 HOLD Baseline | 5.6% | 57.6% | 2.3% | 163.0% |
| v13 Snowball L1 (Price) | 19.2% | 38.1% | 2.3% | 391.5% |
| v13 Snowball L2 (BullScore) | 14.3% | 45.9% | 2.3% | 349.3% |
| v13 Snowball L3 (Profit) | 18.5% | 38.1% | 2.3% | 371.7% |

### Per-Coin Breakdown (v13 Snowball L1)

| Coin | CAGR | Max DD | SL Rate | Snowball Adds |
|------|------|--------|---------|---------------|
| ETH | 33.0% | 49.9% | 3.9% | 27 |
| BNB | 29.0% | 10.0% | 0.0% | 27 |
| TRX | -4.4% | 54.4% | 2.9% | 21 |

---

## 6. Key Insights

### Why Snowball Works in HOLD Mode
1. **Longer holding period** → More time for price to reach add levels
2. **Reduced initial risk** → 25% instead of 100%
3. **Pyramid on strength** → Only add when winning
4. **Lower SL rate** → 2.3% vs 14.3% (fewer exits)

### Why v11 Trading Still Wins
1. **Active management** → Captures both bull and bear
2. **Short positions** → Profit in downtrends
3. **Quick TP levels** → 8/15/25/40% vs holding through volatility
4. **Direction-specific logic** → Long and Short independent

### Best Snowball Strategy: Level 1 (Price-based)
- Highest CAGR: 19.2%
- Lowest DD: 38.1% (tied with L3)
- Highest Capture: 391.5%
- Simple and predictable

---

## 7. Recommendations

### For HOLD Mode
✅ Use **Snowball Level 1** (Price-based: +10%, +20%, +30%)
✅ Enable **Anti-FOMO filters**
✅ Monitor **Exit conditions** (MA50 cross)

### For Trading Mode
✅ Keep **v11 baseline** (3SL + Sideway filter)
✅ Use in **BEAR regime**
✅ Combine with HOLD mode in BULL regime

### Hybrid Strategy (Future Work)
- BULL regime → HOLD mode with Snowball L1
- BEAR regime → Trading mode with v11 features
- SIDEWAY/CHOPPY → CASH

---

## 8. Test Commands

```bash
# Run v11 baseline comparison
python3 scripts/compare_v11_vs_baseline.py

# Run v13 snowball strategies
python3 scripts/backtest_v13_hold_snowball.py

# Run specific snowball level
python3 scripts/backtest_v13_hold_snowball.py --level 1

# Analyze ETH 2024 Q2-Q3
python3 scripts/analyze_eth_2024.py
```

---

## 9. File Structure

```
scripts/
├── crypto_trading.py                    # Production code (v11 features)
├── backtest_optimal.py                  # v10 baseline backtest
├── compare_v11_vs_baseline.py          # v11 vs v10 comparison
├── backtest_v12_hold_mode.py           # v12 HOLD mode (failed)
├── backtest_v13_hold_snowball.py       # v13 HOLD + Snowball ✓
├── analyze_eth_2024.py                 # ETH 2024 deep dive
└── _klines_12h_5y.json                # Cached data

docs/
├── STRATEGY_SUMMARY.md                 # Overall strategy
├── ANTI_SIDEWAY_ANALYSIS.md            # Anti-sideway details
├── STRATEGY_V11_FINAL.md              # v11 final summary
├── HOLD_VS_TRADING_ANALYSIS.md        # Hold vs Trading comparison
└── TESTING_RULES.md                   # This file
```

---

## 10. Next Steps

1. **Implement Hybrid Strategy**
   - BULL → HOLD + Snowball L1
   - BEAR → Trading + v11
   - Test regime transition logic

2. **Optimize Snowball Parameters**
   - Test different add levels (+5%, +15%, +25%)
   - Test different initial sizes (20%, 30%, 40%)
   - Test profit-based with different triggers

3. **Add More Anti-FOMO Filters**
   - RSI > 80 → Skip
   - Volume spike > 3x → Skip
   - Bollinger Band upper band → Skip

4. **Multi-Timeframe Confirmation**
   - Weekly trend for regime
   - Daily for entry
   - 12h for timing

---

**Last Updated**: 2026-06-21
**Version**: v13 (HOLD + Snowball)
**Status**: Testing complete, ready for production consideration
