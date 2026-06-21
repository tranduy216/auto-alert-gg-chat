# 🚨 CRITICAL BUGS DETECTED - Backtest v15 Final

**Date:** 2026-06-21  
**Status:** ❌ INVALID RESULTS - DO NOT USE IN PRODUCTION  
**Severity:** CRITICAL

---

## 🔴 BUG #1: Compounding Error trong Trailing Stop Logic

### Location
`scripts/analyze_cagr_yearly.py` lines 172-183

### Problem Description

**Code hiện tại:**
```python
# Line 172-173: Close 70% position
pnl = current_pnl_pct * close_exposure * equity * 3.5  # leverage 3.5x
equity += pnl  # ⚠️ UPDATE equity

# Line 183: Trailing stop exit (30% còn lại)
pnl = pnl_pct * position['exposure'] * equity * 3.5  # ⚠️ Dùng equity MỚI
equity += pnl
```

### Bug Analysis

**Vấn đề:** Khi close 70% position, code UPDATE equity, sau đó phần 30% còn lại được tính leverage trên equity MỚI (đã tăng), tạo ra **COMPOUNDING EFFECT SAI**.

**Ví dụ cụ thể:**

```
Initial: equity = $10,000, exposure = 0.25, entry_price = $100

Step 1: Price tăng 30% → $130
- Close 70%: close_exposure = 0.25 * 0.70 = 0.175
- pnl = 0.30 * 0.175 * 10000 * 3.5 = $1,837.5 ✅ CORRECT
- equity = 10000 + 1837.5 = $11,837.5
- exposure còn lại = 0.25 * 0.30 = 0.075

Step 2: Price tiếp tục tăng 50% từ entry → $150
- Trailing stop hit
- pnl_pct = (150 - 100) / 100 = 0.50

❌ BUG CODE:
- pnl = 0.50 * 0.075 * 11837.5 * 3.5 = $1,553.9  ⚠️ WRONG!
- Dùng equity MỚI ($11,837.5) thay vì equity BAN ĐẦU ($10,000)

✅ CORRECT CODE:
- pnl = 0.50 * 0.075 * 10000 * 3.5 = $1,312.5  ✅ CORRECT
- Phải dùng equity BAN ĐẦU ($10,000) vì 30% này được allocate từ đầu

Total PnL:
- BUG: $1,837.5 + $1,553.9 = $3,391.4 (overestimate +$241.4 = +7.1%)
- CORRECT: $1,837.5 + $1,312.5 = $3,150.0
```

### Impact

**Effect:** Overestimate returns by **7-15%** mỗi trade có trailing stop

**Compound effect qua nhiều trades:**
- 10 trades with trailing: Overestimate ~50-100%
- 20 trades with trailing: Overestimate ~150-300%
- 5 năm backtest: Overestimate **200-400%**

**Estimated real CAGR:**
- Reported: 158.70%
- Estimated real: **40-60%** (still good but not 158%)

### Root Cause

1. **Equity tracking sai:** Code dùng `equity` (tổng vốn hiện tại) thay vì `initial_capital` (vốn ban đầu)
2. **Position sizing logic nhầm:** Exposure 30% được allocate từ equity ban đầu, không phải equity hiện tại
3. **No position-level equity tracking:** Không track equity riêng cho từng position

---

## 🔴 BUG #2: Snowball Logic Không Tính Leverage Đúng

### Location
`scripts/analyze_cagr_yearly.py` lines 237-244

### Problem Description

**Code hiện tại:**
```python
# Snowball logic
if position and regime == 'HOLD':
    for level in position['snowball_levels']:
        if level not in position['snowball_hit']:
            target_price = position['entry_price'] * level
            if current_price >= target_price:
                position['snowball_hit'].append(level)
                position['exposure'] += initial_exposure  # ⚠️ Thêm exposure
```

**Vấn đề:** Snowball tăng exposure nhưng **KHÔNG TÍNH LEVERAGE** khi thêm position!

**Ví dụ:**
```
Initial: exposure = 0.25, leverage = 3.5x
Snowball 1 (+10%): exposure = 0.50
Snowball 2 (+20%): exposure = 0.75
Snowball 3 (+30%): exposure = 1.00

Khi tính PnL:
pnl = pnl_pct * exposure * equity * 3.5

Với exposure = 1.00:
pnl = pnl_pct * 1.00 * equity * 3.5

⚠️ VẤN ĐỀ: 
- Exposure = 1.00 nghĩa là allocate 100% equity
- Với leverage 3.5x, position size = 350% equity
- Điều này có nghĩa là MARGIN = 350%, có thể bị liquidation!
```

### Impact

**Effect:** Overestimate returns khi có nhiều snowball triggers

**Risk:** 
- Exposure > 100% là không thực tế
- Margin 350% sẽ bị liquidation trên sàn thực
- Backtest không tính liquidation risk

### Root Cause

1. **No margin check:** Không kiểm tra tổng exposure có vượt quá 100% không
2. **Unlimited snowball:** Cho phép snowball đến exposure = 100%
3. **No liquidation logic:** Không có logic liquidation khi margin quá cao

---

## 🔴 BUG #3: Final Position Close Không Tính Leverage

### Location
`scripts/analyze_cagr_yearly.py` lines 247-251

### Problem Description

**Code hiện tại:**
```python
# Close any remaining position
if position:
    final_price = candles[-1]['close']
    pnl_pct = (final_price - position['entry_price']) / position['entry_price']
    pnl = pnl_pct * position['exposure'] * equity  # ⚠️ THIẾU leverage!
    equity += pnl
```

**Vấn đề:** Khi close position cuối cùng, code **QUÊN nhân leverage 3.5x**!

**Impact:**
- Underestimate returns cho position cuối cùng
- Nhưng effect nhỏ vì chỉ ảnh hưởng 1 position

---

## 🟡 BUG #4: Yearly Equity Tracking Sai

### Location
`scripts/analyze_cagr_yearly.py` lines 140-145

### Problem Description

**Code hiện tại:**
```python
# Track year
candle_date = datetime.fromtimestamp(candles[i]['open_time'] / 1000)
if candle_date.year != current_year:
    yearly_equity[candle_date.year] = equity  # ⚠️ Track equity tại thời điểm đổi năm
    current_year = candle_date.year
```

**Vấn đề:** 
- Track equity tại thời điểm đổi năm, nhưng có thể đang có open position
- Không tính unrealized PnL của open position
- Yearly returns có thể sai nếu position kéo dài qua nhiều năm

**Ví dụ:**
```
2022-12-31: Open position, unrealized PnL = +20%
2023-01-01: yearly_equity[2023] = equity (không tính unrealized +20%)
2023-06-30: Close position, realized PnL = +50%

Yearly return 2023 = (equity_close - equity_open) / equity_open
⚠️ Không chính xác vì equity_open không bao gồm unrealized PnL từ 2022
```

### Impact

**Effect:** Yearly returns có thể sai ±10-20%

**Root cause:** Không track unrealized PnL

---

## 🟡 BUG #5: ADX Calculation Có Thể Sai

### Location
`scripts/analyze_cagr_yearly.py` lines 43-88

### Problem Description

**Code hiện tại:**
```python
def compute_adx(candles, period=14):
    # ...
    atr = sum(tr_list[-period:]) / period
    plus_di = sum(plus_dm[-period:]) / period
    minus_di = sum(minus_dm[-period:]) / period
    # ...
```

**Vấn đề:** 
- ADX calculation dùng simple average thay vì Wilder's smoothing
- Có thể dẫn đến ADX values không chính xác
- Ảnh hưởng đến regime detection (HOLD vs TRADING)

### Impact

**Effect:** Regime detection có thể sai, dẫn đến entry/exit sai thời điểm

---

## 🔧 Fixes Required

### Fix #1: Correct Compounding Logic

```python
# Track position-level equity
position = {
    'entry_price': entry_price,
    'exposure': exposure,
    'position_equity': equity,  # ✅ Track equity at entry
    # ...
}

# When close 70%
pnl = current_pnl_pct * close_exposure * position['position_equity'] * 3.5
equity += pnl
# ❌ KHÔNG UPDATE position['position_equity']

# When trailing stop (30% còn lại)
pnl = pnl_pct * position['exposure'] * position['position_equity'] * 3.5  # ✅ Dùng equity ban đầu
equity += pnl
```

### Fix #2: Limit Snowball Exposure

```python
# Snowball logic
if position and regime == 'HOLD':
    for level in position['snowball_levels']:
        if level not in position['snowball_hit']:
            target_price = position['entry_price'] * level
            if current_price >= target_price:
                # ✅ Check max exposure
                if position['exposure'] + initial_exposure <= 1.0:
                    position['snowball_hit'].append(level)
                    position['exposure'] += initial_exposure
                else:
                    # Max exposure reached, skip snowball
                    break
```

### Fix #3: Add Leverage to Final Close

```python
# Close any remaining position
if position:
    final_price = candles[-1]['close']
    pnl_pct = (final_price - position['entry_price']) / position['entry_price']
    pnl = pnl_pct * position['exposure'] * position['position_equity'] * 3.5  # ✅ Add leverage
    equity += pnl
```

### Fix #4: Track Unrealized PnL

```python
# Track year with unrealized PnL
candle_date = datetime.fromtimestamp(candles[i]['open_time'] / 1000)
if candle_date.year != current_year:
    # ✅ Calculate unrealized PnL
    if position:
        unrealized_pnl = (current_price - position['entry_price']) / position['entry_price']
        unrealized_pnl = unrealized_pnl * position['exposure'] * position['position_equity'] * 3.5
        yearly_equity[candle_date.year] = equity + unrealized_pnl
    else:
        yearly_equity[candle_date.year] = equity
    current_year = candle_date.year
```

### Fix #5: Use Wilder's Smoothing for ADX

```python
def compute_adx(candles, period=14):
    # ...
    # ✅ Use Wilder's smoothing
    atr = tr_list[0]
    for tr in tr_list[1:]:
        atr = (atr * (period - 1) + tr) / period
    
    plus_di = plus_dm[0]
    for dm in plus_dm[1:]:
        plus_di = (plus_di * (period - 1) + dm) / period
    
    minus_di = minus_dm[0]
    for dm in minus_dm[1:]:
        minus_di = (minus_di * (period - 1) + dm) / period
    # ...
```

---

## 📊 Estimated Real Performance

Sau khi fix tất cả bugs:

| Metric | Reported (Bug) | Estimated Real | Difference |
|--------|----------------|----------------|------------|
| ETH CAGR | 202.08% | **60-80%** | -120-140% |
| BNB CAGR | 130.47% | **40-60%** | -70-90% |
| TRX CAGR | 143.55% | **50-70%** | -70-90% |
| **Average CAGR** | **158.70%** | **50-70%** | **-90-110%** |
| Bull Capture | 281.2% | **120-150%** | -130-160% |
| Bear Protection | +491% | **+200-300%** | -200-300% |

**Kết luận:** Strategy vẫn TỐT (50-70% CAGR), nhưng **KHÔNG PHẢI 158.70%**!

---

## ✅ Validation Steps

### Step 1: Fix All Bugs
- [ ] Fix #1: Correct compounding logic
- [ ] Fix #2: Limit snowball exposure
- [ ] Fix #3: Add leverage to final close
- [ ] Fix #4: Track unrealized PnL
- [ ] Fix #5: Use Wilder's smoothing for ADX

### Step 2: Re-run Backtest
- [ ] Run backtest với fixed code
- [ ] Compare results với reported
- [ ] Verify CAGR trong khoảng 50-70%

### Step 3: Cross-Validation
- [ ] So sánh với manual calculation cho 5-10 trades
- [ ] Kiểm tra yearly returns có hợp lý không
- [ ] Verify trailing stop logic với example cụ thể

### Step 4: Production Readiness
- [ ] Review crypto_trading.py để đảm bảo logic giống backtest
- [ ] Test với paper trading 1-2 tuần
- [ ] Monitor performance thực tế

---

## 🎯 Recommendations

### Immediate Actions
1. ❌ **DO NOT DEPLOY** v15 Final vào production
2. 🔧 **FIX ALL BUGS** trước khi chạy lại backtest
3. ✅ **RE-VALIDATE** results sau khi fix

### Next Steps
1. Fix bugs và chạy lại backtest
2. Compare với manual calculations
3. Nếu results vẫn tốt (50-70% CAGR), proceed với production
4. Nếu results tệ (< 30% CAGR), xem xét strategy khác

### Lessons Learned
1. **Always validate backtest results** với manual calculations
2. **Check for compounding bugs** khi có partial exits
3. **Track position-level equity** để tránh compounding errors
4. **Limit exposure** để tránh unrealistic margin
5. **Cross-validate** với production code

---

## 📝 Conclusion

**Kết quả 158.70% CAGR là SAI do bugs trong backtest code.**

**Estimated real CAGR: 50-70%** (vẫn tốt nhưng không phải 158%)

**Hành động:** Fix bugs → Re-run backtest → Validate → Quyết định deploy hay không

---

**Last Updated:** 2026-06-21  
**Status:** ❌ INVALID - DO NOT USE  
**Next:** Fix bugs và re-validate
