# BASELINE - Crypto Trading Strategy

**Last Updated:** 2026-06-21  
**Status:** Production Ready (with 1 critical issue to fix)

---

## Strategy Overview

**Core Principle:** Mỗi coin có regime riêng (MA50 vs MA200), KHÔNG dựa trên BTC regime.

- **🐂 Bull Market** (MA50 > MA200): Normal trading - full leverage, full position
- **🐻 Bear Market** (MA50 < MA200): Risk reduction - lower leverage, smaller position

---

## Configuration

### Bear Market (Risk Reduction)

```python
BEAR_LEV = 2.0  # All coins use 2.0x leverage

def _coin_sl_bear(coin: str) -> float:
    if coin == "ETH": return 8.0
    if coin == "BNB": return 10.0
    if coin == "TRX": return 8.0
    return 10.0

def _coin_pos_mult_bear(coin: str) -> float:
    if coin == "ETH": return 0.90
    return 0.75  # BNB, TRX, others
```

**Chiến lược:**
1. Leverage: 2.0x (từ 2.5-3.5x trong bull)
2. Position Size: ETH 90%, BNB/TRX 75%
3. Stop Loss: Tighter (ETH 8%, BNB 10%, TRX 8%)

### Bull Market (Normal Trading)

```python
PROFILES_BULL = {
    "ETH": {"lev": 2.5, "sl": 10, "pos_mult": 1.0},
    "BNB": {"lev": 3.5, "sl": 12, "pos_mult": 1.0},
    "TRX": {"lev": 3.5, "sl": 12, "pos_mult": 1.0},
}
```

**Chiến lược:**
1. Leverage: Full (ETH 2.5x, BNB/TRX 3.5x)
2. Position Size: 100%
3. Stop Loss: Wider (ETH 10%, BNB/TRX 12%)

---

## Comparison: BEAR vs BULL

| Aspect | BEAR | BULL |
|--------|------|------|
| **ETH Leverage** | 2.0x | 2.5x |
| **BNB Leverage** | 2.0x | 3.5x |
| **TRX Leverage** | 2.0x | 3.5x |
| **ETH Position** | 90% | 100% |
| **BNB Position** | 75% | 100% |
| **TRX Position** | 75% | 100% |
| **ETH SL** | 8% | 10% |
| **BNB SL** | 10% | 12% |
| **TRX SL** | 8% | 12% |

---

## Performance Results (BASELINE Config)

**Tested with backtest_fast.py:**

| Coin | CAGR | Max DD | SL Rate | Final Equity |
|------|------|--------|---------|--------------|
| ETH | +23.14% | 37.18% | 16.19% | $30,549 |
| BNB | +37.50% | 20.60% | 15.25% | $55,187 |
| TRX | +33.65% | 34.07% | 12.96% | $47,389 |
| **Average** | **+31.43%** | **30.62%** | **14.80%** | **$44,375** |

---

## 🚨 CRITICAL ISSUE: Regime-Dependent Cooldown Shift

### Problem

**backtest_optimal.py có, nhưng crypto_trading.py KHÔNG có:**

```python
# backtest_optimal.py (lines 125-126):
long_shift = bull_l_shift if is_bull else bear_l_shift
short_shift = bull_s_shift if is_bull else bear_s_shift

# crypto_trading.py (line 182):
cd_bars_fib = _fib_cooldown_bars(consec_l, 0)  # ❌ Không có shift
```

### Impact

Production results sẽ **khác** backtest results vì production không có regime-dependent cooldown.

### Fix Required

Thêm function vào `crypto_trading.py`:

```python
def _get_cooldown_shift(coin: str, is_long: bool, is_bull: bool) -> int:
    """Get cooldown shift based on regime and direction.
    
    Bear market: SHORT→shift=0 (3 bars), LONG→shift=1 (5 bars)
    Bull market: SHORT→shift=1 (5 bars), LONG→shift=0 (3 bars)
    """
    if is_bull:
        return 1 if is_long else 0
    else:
        return 0 if is_long else 1

# Usage trong entry logic:
shift = _get_cooldown_shift(coin, is_long=True, is_bull=_coin_bull)
cd_bars_fib = _fib_cooldown_bars(consec_l, shift)
```

---

## Consistency Checklist

### 4 Files Must Sync

1. `scripts/backtest_optimal.py` - Backtest framework
2. `scripts/crypto_trading.py` - Production implementation
3. `tests/test_crypto_trading.py` - Unit tests (25/25 passing)
4. `BASELINE.md` - This file

### Values Comparison

| Parameter | backtest_optimal.py | crypto_trading.py | Status |
|-----------|---------------------|-------------------|--------|
| **ETH Leverage (Bull)** | 2.5 | 2.5 | ✅ Match |
| **BNB Leverage (Bull)** | 3.5 | 3.5 | ✅ Match |
| **TRX Leverage (Bull)** | 3.5 | 3.5 | ✅ Match |
| **All Leverage (Bear)** | 2.0 | 2.0 | ✅ Match |
| **ETH SL (Bull)** | 10% | 10% | ✅ Match |
| **BNB SL (Bull)** | 12% | 12% | ✅ Match |
| **TRX SL (Bull)** | 12% | 12% | ✅ Match |
| **ETH SL (Bear)** | 8% | 8% | ✅ Match |
| **BNB SL (Bear)** | 10% | 10% | ✅ Match |
| **TRX SL (Bear)** | 8% | 8% | ✅ Match |
| **ETH Position (Bear)** | 0.90 | 0.90 | ✅ Match |
| **BNB Position (Bear)** | 0.75 | 0.75 | ✅ Match |
| **TRX Position (Bear)** | 0.75 | 0.75 | ✅ Match |
| **Cooldown Shift** | ✅ Có | ❌ KHÔNG | 🔴 **MISMATCH** |

---

## Sync Process

Khi thay đổi strategy:

1. **Update backtest_optimal.py:**
   - Thay đổi PROFILES_BULL/BEAR
   - Chạy backtest để validate

2. **Update crypto_trading.py:**
   - Sync `_coin_lev()`, `_coin_sl_roi()`, `_coin_pos_mult_bear()`
   - **Sync `_get_cooldown_shift()` logic** 🔴 **CRITICAL**

3. **Update tests/test_crypto_trading.py:**
   - Thêm tests cho new logic
   - Đảm bảo 25/25 tests passing

4. **Update BASELINE.md:**
   - Document changes
   - Update checklist

5. **Validate:**
   - Chạy backtest_optimal.py
   - Chạy crypto_trading.py với cùng data
   - So sánh results (differences < 5% là acceptable)

---

## Validation Commands

```bash
# 1. Chạy backtest
python3 scripts/backtest_optimal.py
# Expected: CAGR ~31.43%, Max DD ~30.62%, SL Rate ~14.80%

# 2. Chạy production với test data
python3 scripts/crypto_trading.py --test-mode
# Expected: Results tương tự backtest (±5%)

# 3. Chạy unit tests
python3 -m unittest tests.test_crypto_trading -v
# Expected: 25/25 tests passing

# 4. So sánh results
# Expected: CAGR, Max DD, SL Rate tương tự nhau (±5%)
# Differences > 5% → Investigate mismatch
```

---

## Known Issues

### Issue #1: Regime-Dependent Cooldown Shift 🔴 CRITICAL

**Problem:** crypto_trading.py KHÔNG có regime-dependent cooldown shift

**Impact:** Production results khác backtest results

**Status:** 🔴 **NOT FIXED** - Cần implement trước khi deploy

**Priority:** 🔴 **CRITICAL** - Ảnh hưởng đến production results

---

## Deployment Checklist

- [x] Per-coin regime detection implemented
- [x] Backtest validation (5-year historical data)
- [x] Risk management (position limits, exposure limits)
- [x] Unit tests (25/25 passing)
- [x] Integration tests
- [x] Out-of-sample testing
- [x] Documentation updated
- [ ] **Fix regime-dependent cooldown shift** 🔴 **CRITICAL**
- [ ] Paper trading (1-2 weeks)
- [ ] Live trading (small capital)
- [ ] Monitor and adjust

---

## Key Files

- `scripts/crypto_trading.py` - Main trading logic
- `scripts/backtest_optimal.py` - Backtest framework
- `scripts/backtest_fast.py` - Fast backtest tool (cache, parallel)
- `tests/test_crypto_trading.py` - Unit tests (25 tests)
- `BASELINE.md` - This file
- `TESTING_BEST_PRACTICES.md` - Testing guidelines

---

## Key Takeaways

1. **Per-Coin Regime > BTC Regime** - Mỗi coin có trend riêng
2. **Direction-Specific > Cross-Direction** - LONG cooldown chỉ block LONG
3. **Fibonacci > Fixed Cooldown** - Progressive cooldown
4. **Risk Reduction in Bear Market** - Lower leverage, smaller position, tighter SL
5. **Performance: CAGR 31.43%, DD 30.62%** - Solid performance với risk management

---

**Next Review:** 2026-07-21 (after paper trading)
