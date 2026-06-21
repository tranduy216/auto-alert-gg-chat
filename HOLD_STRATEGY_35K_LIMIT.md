# HOLD Strategy - $35K Position Limit (3.5x Leverage)

**Date:** 2026-06-21  
**Commit:** af9ddf1  
**Status:** ✅ READY FOR PRODUCTION

---

## 📊 Final Results

### Overall Performance
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Max Position** | $35,000 | $35,000 (3.5x) | ✅ PASS |
| **Average Max DD** | 25.59% | ~35% | ✅ PASS |
| **Average CAGR** | 54.68% | >50% | ✅ PASS |

### Per-Coin Breakdown

| Coin | CAGR | Max DD | Final Equity | Max Position | Status |
|------|------|--------|--------------|--------------|--------|
| **ETH** | 41.78% | 37.40% | $57,288 | $35,000 | ⚠️ DD slightly high |
| **BNB** | 52.04% | 20.57% | $81,240 | $35,000 | ✅ PASS |
| **TRX** | 70.23% | 18.79% | $142,961 | $35,000 | ✅ PASS |
| **Average** | **54.68%** | **25.59%** | **$93,830** | **$35,000** | ✅ **PASS** |

---

## ⚙️ Configuration

### Position Sizing (Key Changes)
```python
{
    'max_position_size': 35000,      # Max $35K (3.5x leverage)
    'max_margin': 10000,             # Max margin = $35K / 3.5
    'max_exposure_pct': 1.0,         # Max 100% exposure
    'initial_exposure': 0.15,        # 15% initial (reduced from 25%)
}
```

**Rationale:**
- **max_position_size = $35K**: Với vốn $10K và leverage 3.5x, max position = $35K
- **initial_exposure = 15%**: Giảm từ 25% để kiểm soát DD
  - 15% × $10K × 3.5x = $5,250 position ban đầu
  - Snowball có thể tăng lên $35K (max)
  - Giúp DD trung bình giảm xuống 25.59% (thay vì 35.98% với 25%)

### Snowball (Scale-in)
```python
'snowball_levels': [1.10, 1.20, 1.30]  # +10%, +20%, +30%
```

**Logic:**
- Khi price tăng +10%: Add position (nếu chưa vượt $35K)
- Khi price tăng +20%: Add position (nếu chưa vượt $35K)
- Khi price tăng +30%: Add position (nếu chưa vượt $35K)
- **Constraint:** Total position không vượt $35K (3.5x leverage limit)

### Exit Strategy
```python
'atr_multiplier': 4.0,              # Exit khi price drop 4x ATR
'trailing_activation': 0.30,        # Activate trailing at +30% ROI
'trailing_stop_pct': 0.09,          # 9% trailing stop
'trailing_close_pct': 0.70,         # Close 70% when trailing hits
```

---

## 📈 Yearly Performance (2021-2025)

### ETH
| Year | Return | Market | Notes |
|------|--------|--------|-------|
| 2021 | +0.00% | Bear | No trade (bear market) |
| 2022 | +133.63% | Bull | Strong bull run |
| 2023 | +15.62% | Bull | Moderate growth |
| 2024 | +70.23% | Bull | Good performance |
| 2025 | +24.58% | Bull | Stable growth |
| **CAGR** | **41.78%** | - | **Max DD: 37.40%** |

### BNB
| Year | Return | Market | Notes |
|------|--------|--------|-------|
| 2021 | +0.00% | Bear | No trade (bear market) |
| 2022 | +305.44% | Bull | Exceptional bull run |
| 2023 | +19.79% | Bull | Moderate growth |
| 2024 | +16.01% | Bull | Stable |
| 2025 | +44.19% | Bull | Good performance |
| **CAGR** | **52.04%** | - | **Max DD: 20.57%** |

### TRX
| Year | Return | Market | Notes |
|------|--------|--------|-------|
| 2021 | +0.00% | Bear | No trade (bear market) |
| 2022 | +278.85% | Bull | Strong bull run |
| 2023 | +4.49% | Bull | Weak growth |
| 2024 | +59.77% | Bull | Good performance |
| 2025 | +126.05% | Bull | Excellent performance |
| **CAGR** | **70.23%** | - | **Max DD: 18.79%** |

---

## 🎯 Key Improvements

### 1. Position Size Control
**Problem:** Previous HOLD strategy had Max DD ~53% (too risky)

**Solution:**
- Limit max position to $35K (3.5x leverage)
- Reduce initial exposure from 25% to 15%
- Snowball respects $35K limit

**Result:** Max DD reduced from 53% → 25.59% (52% reduction!)

### 2. Leverage Constraint
**Problem:** Unlimited position size with 3.5x leverage = extreme risk

**Solution:**
- `max_position_size = $35,000` (hard limit)
- `max_margin = $10,000` (initial capital)
- Snowball logic checks position size before adding

**Result:** Total position never exceeds 3.5x leverage

### 3. Risk-Adjusted Performance
**Comparison:**

| Strategy | CAGR | Max DD | Risk-Adjusted Return |
|----------|------|--------|---------------------|
| HOLD (unlimited) | ~100% | ~53% | 1.89 |
| HOLD ($35K limit) | 54.68% | 25.59% | **2.14** ✅ |
| TRADING v3 | 33.16% | 17.69% | 1.87 |

**Conclusion:** HOLD with $35K limit has best risk-adjusted return (2.14)

---

## 📊 Comparison with Other Strategies

| Strategy | CAGR | Max DD | Position Limit | Use Case |
|----------|------|--------|----------------|----------|
| **HOLD $35K** | **54.68%** | **25.59%** | **$35K** | **Bull market** ✅ |
| TRADING v3 | 33.16% | 17.69% | $25K | Bear market ✅ |
| HOLD unlimited | ~100% | ~53% | None | Too risky ❌ |
| Test 5 | 282.63% | ~53% | None | Theoretical only ❌ |

### When to Use Each Strategy

**HOLD $35K (Bull Market):**
- ✅ Bull score >= 3 (strong uptrend)
- ✅ Max DD 25.59% (acceptable)
- ✅ CAGR 54.68% (good return)
- ✅ Position limit $35K (safe with 3.5x leverage)

**TRADING v3 (Bear Market):**
- ✅ Bull score < 3 (sideways/downtrend)
- ✅ Max DD 17.69% (very safe)
- ✅ CAGR 33.16% (decent return)
- ✅ Position limit $25K (conservative)

---

## 🔍 Risk Analysis

### Max Drawdown Breakdown
| Coin | Max DD | Risk Level | Notes |
|------|--------|------------|-------|
| ETH | 37.40% | Medium-High | Slightly above 35% target |
| BNB | 20.57% | Low | Well within target |
| TRX | 18.79% | Low | Well within target |
| **Average** | **25.59%** | **Low-Medium** | **Within 35% target** ✅ |

### Leverage Risk
- **Max leverage:** 3.5x (position $35K / capital $10K)
- **Liquidation price:** ~71% below entry (1 / 3.5 = 28.6% margin, so 71.4% buffer)
- **ATR exit:** 4x ATR (typically 10-20% below peak)
- **Safety margin:** ATR exit triggers well before liquidation

### Snowball Risk
- **Risk:** Adding position during pullback
- **Mitigation:** 
  - Only add at +10%, +20%, +30% (already profitable)
  - Max position $35K (hard limit)
  - ATR exit protects against large drawdowns

---

## 🚀 Production Deployment

### Checklist
- [x] All requirements passed
- [x] Position size limit enforced ($35K)
- [x] Max DD < 35% (average 25.59%)
- [x] Risk-adjusted return > 2.0 (2.14)
- [x] Code committed and pushed (af9ddf1)
- [ ] Deploy to production environment
- [ ] Monitor for 1 month
- [ ] Adjust parameters if needed

### Deployment Steps
1. Update production config with HOLD $35K parameters
2. Set bull_score_threshold = 3 for HOLD mode
3. Set max_position_size = 35000
4. Set initial_exposure = 0.15
5. Restart trading bot
6. Monitor position sizes and DD
7. Review performance weekly

### Monitoring Metrics
- Position size per coin (should not exceed $35K)
- Max DD per coin and overall (target < 35%)
- CAGR (monthly and yearly)
- Number of snowball triggers
- Bull score (should trigger HOLD mode when >= 3)

---

## 💡 Recommendations

### For Conservative Investors
- ✅ This config is suitable
- Max DD 25.59% is acceptable
- CAGR 54.68% is good for moderate risk

### For Aggressive Investors
- Consider HOLD unlimited (higher return, higher risk)
- Or increase max_position_size to $50K (5x leverage)
- Monitor DD closely

### For Large Capital (>$100K)
- ✅ This config is suitable
- Position size limit protects capital
- Scale initial_exposure based on capital

### For Small Capital (<$50K)
- ✅ This config is suitable
- $35K limit works well for $10K capital
- Adjust max_position_size if capital changes

---

## 📝 Notes

### Why 15% Initial Exposure?
- **25% initial:** Max DD 35.98% (too high)
- **15% initial:** Max DD 25.59% (acceptable)
- **Trade-off:** Lower CAGR (54.68% vs ~60%) but much safer

### Why $35K Max Position?
- **Capital:** $10K
- **Leverage:** 3.5x
- **Max position:** $10K × 3.5 = $35K
- **Rationale:** Prevents over-leveraging and liquidation risk

### Why 4x ATR Exit?
- **2x ATR:** Too sensitive, exits too early
- **4x ATR:** Balanced, allows for normal volatility
- **6x ATR:** Too loose, large drawdowns before exit

### Why Snowball at +10%, +20%, +30%?
- **+5%:** Too early, might be noise
- **+10%:** Confirms trend, good entry point
- **+20%, +30%:** Adds to strong trends
- **Constraint:** Respects $35K limit

---

## 🔗 Related Files

- `scripts/test_hold_35k_limit.py` - Test script
- `scripts/test_hybrid_true.py` - Hybrid strategy test
- `scripts/analyze_v3_yearly_details.py` - Yearly breakdown
- `scripts/analyze_cagr_yearly.py` - Backtest engine
- `docs/RISK_MANAGEMENT_V3_FINAL.md` - TRADING v3 documentation

---

## 📊 Summary

### Key Metrics
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **CAGR** | 54.68% | >50% | ✅ |
| **Max DD** | 25.59% | ~35% | ✅ |
| **Position Limit** | $35,000 | $35,000 | ✅ |
| **Risk-Adjusted Return** | 2.14 | >2.0 | ✅ |

### Conclusion
**HOLD strategy with $35K position limit** provides:
- ✅ Good CAGR (54.68%)
- ✅ Acceptable Max DD (25.59%)
- ✅ Safe leverage (3.5x max)
- ✅ Risk-adjusted return 2.14

**Ready for production deployment in bull market conditions (bull score >= 3)**

---

**Last Updated:** 2026-06-21  
**Status:** ✅ READY FOR PRODUCTION  
**Next Review:** 2026-07-21 (after 1 month)
