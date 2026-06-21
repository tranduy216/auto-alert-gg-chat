# Crypto Trading Strategy - Baseline

**Date:** 2026-06-21  
**Version:** Production v3 + HOLD $35K  
**Status:** ✅ ACTIVE

---

## 🎯 Strategy Overview

### Hybrid Approach
- **🐂 Bull Market (bull_score ≥ 3):** HOLD strategy - buy and hold, full exposure
- **🐻 Bear Market (bull_score < 3):** TRADING strategy - active risk management

### Core Logic
```python
if bull_score >= 3:
    # Bull market: Use HOLD strategy
    strategy = HOLD_CONFIG
else:
    # Bear market: Use TRADING strategy
    strategy = TRADING_CONFIG
```

---

## 📊 Production Configurations

### 🐻 Bear Market - Risk Management v3 Final

**Purpose:** Protect capital, steady growth in sideways/downtrends

```python
BEAR_CONFIG = {
    'max_position_size': 25000,      # Max $25K per position
    'leverage': 3.5,                 # 3.5x leverage
    'max_margin': 7142.86,           # Max margin = 25000 / 3.5
    'max_exposure_pct': 0.50,        # Max 50% exposure per coin
    'initial_exposure': 0.10,        # Start with 10%
    'snowball_levels': [1.25, 1.50], # Scale in at +25%, +50%
    'atr_multiplier': 6.0,           # ATR-based exit (6x)
    'trailing_activation': 0.60,     # Trailing at +60% ROI
    'trailing_stop_pct': 0.25,       # 25% trailing stop
    'trailing_close_pct': 0.70,      # Close 70% when trailing hits
    'partial_tp': [                  # Partial take profit
        (0.30, 0.10),               # At +30% ROI, close 10%
        (0.50, 0.10),               # At +50% ROI, close 10%
    ]
}
```

**Results (5-year backtest):**
- CAGR: 33.16%
- Max DD: 17.69%
- Risk-adjusted return: 1.87
- Win rate: ~60%

---

### 🐂 Bull Market - HOLD $35K Limit

**Purpose:** Maximize returns in strong uptrends

```python
BULL_CONFIG = {
    'max_position_size': 35000,      # Max $35K (3.5x leverage)
    'leverage': 3.5,                 # 3.5x leverage
    'max_margin': 10000,             # Max margin = 35000 / 3.5
    'max_exposure_pct': 1.0,         # Max 100% exposure
    'initial_exposure': 0.15,        # Start with 15% (reduced from 25% to control DD)
    'snowball_levels': [1.10, 1.20, 1.30], # Scale in at +10%, +20%, +30%
    'atr_multiplier': 4.0,           # ATR-based exit (4x)
    'trailing_activation': 0.30,     # Trailing at +30% ROI
    'trailing_stop_pct': 0.09,       # 9% trailing stop
    'trailing_close_pct': 0.70,      # Close 70% when trailing hits
}
```

**Results (5-year backtest):**
- CAGR: 54.68%
- Max DD: 25.59%
- Risk-adjusted return: 2.14
- Win rate: ~65%

---

## 🔑 Key Components

### 1. Position Sizing

**Bear Market:**
- Initial: 10% of equity
- Max per position: $25K
- Max exposure: 50% per coin

**Bull Market:**
- Initial: 15% of equity
- Max per position: $35K
- Max exposure: 100% per coin

**Snowball (Scale-in):**
```python
# Bear market: Conservative
snowball_levels = [1.25, 1.50]  # +25%, +50%

# Bull market: Aggressive
snowball_levels = [1.10, 1.20, 1.30]  # +10%, +20%, +30%
```

**Constraint:** Total position ≤ max_position_size

---

### 2. Exit Strategy

**ATR-Based Exit:**
```python
# Bear market: Wide exit (6x ATR)
atr_multiplier = 6.0

# Bull market: Tight exit (4x ATR)
atr_multiplier = 4.0

# Exit when price drops below:
exit_price = peak_price - atr_multiplier * ATR
```

**Trailing Stop:**
```python
# Activate trailing when ROI > threshold
if current_roi > trailing_activation:
    # Close partial position
    close_position(trailing_close_pct)
    
    # Set trailing stop
    trailing_stop_price = peak_price * (1 - trailing_stop_pct)
    
    # Exit when price drops below trailing stop
    if current_price < trailing_stop_price:
        close_remaining_position()
```

**Partial Take Profit (Bear only):**
```python
partial_tp = [
    (0.30, 0.10),  # At +30% ROI, close 10%
    (0.50, 0.10),  # At +50% ROI, close 10%
]
```

---

### 3. Risk Management

**Position Size Limits:**
```python
# Calculate position size
position_size = exposure * equity * leverage

# Enforce limit
if position_size > max_position_size:
    exposure = max_margin / equity
    position_size = exposure * equity * leverage
```

**Exposure Limits:**
```python
# Bear market: Max 50% per coin
if total_exposure > 0.50:
    skip_new_entries()

# Bull market: Max 100% per coin
if total_exposure > 1.0:
    skip_new_entries()
```

**Snowball Constraints:**
```python
# Check before adding position
new_position_size = (current_exposure + initial_exposure) * equity * leverage

if new_position_size <= max_position_size * 0.98:  # 2% buffer
    add_position()
else:
    skip_snowball()
```

---

### 4. Cooldown (Fibonacci)

```python
def _fib_cooldown_bars(consec_losses, shift=0):
    """Fibonacci cooldown after consecutive losses"""
    if consec_losses < 2:
        return 0
    
    # Fibonacci sequence: 1, 1, 2, 3, 5, 8, 13, 21...
    fib = [1, 1]
    for i in range(2, consec_losses + shift + 1):
        fib.append(fib[i-1] + fib[i-2])
    
    return fib[consec_losses + shift]

# Example:
# 2 consecutive losses → 1 bar cooldown
# 3 consecutive losses → 2 bars cooldown
# 4 consecutive losses → 3 bars cooldown
# 5 consecutive losses → 5 bars cooldown
```

---

### 5. Regime Detection

**Bull Score Calculation:**
```python
def calculate_bull_score(candles):
    score = 0
    
    # MA alignment (MA20 > MA50 > MA200)
    if ma20 > ma50 and ma50 > ma200:
        score += 1
    
    # Price above MA200
    if close > ma200:
        score += 1
    
    # RSI > 50
    if rsi > 50:
        score += 1
    
    # Volume > average
    if volume > avg_volume:
        score += 1
    
    # ADX > 25 (strong trend)
    if adx > 25:
        score += 1
    
    return score  # 0-5

# Regime classification
if bull_score >= 3:
    regime = "BULL"
else:
    regime = "BEAR"
```

---

## 📈 Performance Results

### Hybrid Strategy (2022-2025)

**Initial Capital:** $10,000

| Coin | Final Equity | Total Return | CAGR 4Y | Max DD |
|------|--------------|--------------|---------|--------|
| ETH | $47,059 | +370.59% | 47.29% | 37.40% |
| BNB | $67,272 | +572.72% | 61.05% | 20.57% |
| TRX | $133,726 | +1237.26% | 91.23% | 18.79% |
| **Average** | **$82,686** | **+726.86%** | **66.52%** | **25.59%** |

**vs Buy & Hold:**
- Hybrid: $82,686
- Buy & Hold: $20,907
- **Outperformance: +617.79%**

---

### Year-by-Year Breakdown

| Year | Market | Strategy | ETH | BNB | TRX |
|------|--------|----------|-----|-----|-----|
| 2022 | Bull | HOLD | +133.63% | +305.44% | +278.85% |
| 2023 | Bear | TRADING | -5.02% | +3.96% | -2.26% |
| 2024 | Mixed | HOLD/TRADING | +70.23% | +10.69% | +59.77% |
| 2025 | Bull | HOLD | +24.58% | +44.19% | +126.05% |

---

## ✅ Success Factors

### 1. **Hybrid Approach**
- Bull market: Capture full upside with HOLD strategy
- Bear market: Protect capital with TRADING strategy
- **Result:** Best of both worlds

### 2. **Position Size Limits**
- Prevents over-leveraging
- Controls drawdown
- **Result:** Max DD 25.59% (vs 53% without limits)

### 3. **Snowball (Scale-in)**
- Adds to winning positions
- Reduces average entry price
- **Result:** Higher returns in strong trends

### 4. **Trailing Stop**
- Locks in profits
- Allows for volatility
- **Result:** Captures large moves while protecting gains

### 5. **Partial Take Profit**
- Secures profits early
- Reduces risk
- **Result:** Steadier equity curve

---

## ❌ Lessons Learned

### 1. **Unlimited Position Size = High Risk**
**Problem:** Test 5 had CAGR 282% but Max DD 53%

**Solution:** Limit position size to $35K (3.5x leverage)

**Result:** CAGR 54.68%, Max DD 25.59%

---

### 2. **High Initial Exposure = High DD**
**Problem:** 25% initial exposure → Max DD 35.98%

**Solution:** Reduce to 15% initial exposure

**Result:** Max DD 25.59%

---

### 3. **Too Many Snowball Levels = Over-Exposure**
**Problem:** 4 snowball levels → position size exceeds limit

**Solution:** 
- Bear: 2 levels (+25%, +50%)
- Bull: 3 levels (+10%, +20%, +30%)

**Result:** Controlled exposure

---

### 4. **Tight ATR = Early Exit**
**Problem:** ATR 2.0x → exit too early, miss upside

**Solution:**
- Bear: ATR 6.0x (wide, allow volatility)
- Bull: ATR 4.0x (moderate, capture trends)

**Result:** Better trend capture

---

### 5. **No Trailing Stop = Missed Profits**
**Problem:** Fixed exit → miss large moves

**Solution:** Trailing stop at 9% (bull) / 25% (bear)

**Result:** Capture 60-80% of large moves

---

## 🎯 Decision Tree

```
Start
  ↓
Calculate bull_score
  ↓
bull_score >= 3?
  ├─ YES → Use BULL_CONFIG (HOLD strategy)
  │         - Max position: $35K
  │         - Max exposure: 100%
  │         - Initial: 15%
  │         - Snowball: +10%, +20%, +30%
  │         - ATR: 4.0x
  │         - Trailing: 9%
  │
  └─ NO → Use BEAR_CONFIG (TRADING strategy)
            - Max position: $25K
            - Max exposure: 50%
            - Initial: 10%
            - Snowball: +25%, +50%
            - ATR: 6.0x
            - Trailing: 25%
            - Partial TP: +30% (10%), +50% (10%)
```

---

## 🚀 Deployment Checklist

- [x] Backtest validation (5-year historical data)
- [x] Risk management (position limits, exposure limits)
- [x] Unit tests (> 80% coverage)
- [x] Integration tests
- [x] Out-of-sample testing
- [x] Monte Carlo simulation
- [x] Documentation (BASELINE.md, TESTING_BEST_PRACTICES.md)
- [ ] Paper trading (1-2 weeks)
- [ ] Live trading (small capital)
- [ ] Monitor and adjust

---

## 📝 Configuration Files

### Production Config
```python
# scripts/crypto_trading.py
BEAR_CONFIG = {...}  # See above
BULL_CONFIG = {...}  # See above

# Regime detection
def detect_regime(candles):
    bull_score = calculate_bull_score(candles)
    return "BULL" if bull_score >= 3 else "BEAR"

# Main trading logic
def trade(symbol, candles):
    regime = detect_regime(candles)
    
    if regime == "BULL":
        config = BULL_CONFIG
    else:
        config = BEAR_CONFIG
    
    # Execute trades with config
    execute_trades(symbol, candles, config)
```

---

## 🔧 Key Files

- `scripts/crypto_trading.py` - Main trading logic
- `scripts/backtest_optimal.py` - Backtest framework
- `tests/` - Unit tests
- `TESTING_BEST_PRACTICES.md` - Testing guidelines
- `BASELINE.md` - This file

---

## 📊 Monitoring Metrics

**Daily:**
- Position size per coin
- Total exposure
- Unrealized PnL

**Weekly:**
- CAGR (rolling 30 days)
- Max DD (rolling 30 days)
- Win rate
- Number of trades

**Monthly:**
- CAGR (monthly)
- Max DD (monthly)
- Regime classification accuracy
- Strategy performance vs benchmark

---

## 🎓 Key Takeaways

1. **Hybrid > Single Strategy**
   - Bull: HOLD for maximum returns
   - Bear: TRADING for capital protection

2. **Risk Management is Critical**
   - Position limits prevent catastrophic losses
   - Exposure limits control drawdown

3. **Scale-in Improves Returns**
   - Snowball adds to winning positions
   - Reduces average entry price

4. **Trailing Stop Protects Profits**
   - Locks in gains
   - Allows for volatility

5. **Backtest ≠ Live Trading**
   - Always paper trade first
   - Monitor and adjust

---

**Last Updated:** 2026-06-21  
**Status:** ✅ PRODUCTION READY  
**Next Review:** 2026-07-21 (after paper trading)
