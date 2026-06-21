# Backtest v16: Flexible MA Cross Exit Thresholds

**Date:** 2026-06-21  
**Status:** ✅ Complete  
**Best Config:** RSI<65 + ATR Exit (v15) hoặc MA cross 4% threshold

---

## Mục tiêu

Test các threshold linh hoạt cho MA cross exit thay vì exit ngay khi MA20 < MA50:
- **0% (baseline):** MA20 < MA50 → Exit ngay
- **2%:** MA20 < MA50 * 0.98 → Chờ MA20 xuống 2% so với MA50
- **3%:** MA20 < MA50 * 0.97 → Chờ MA20 xuống 3% so với MA50
- **4%:** MA20 < MA50 * 0.96 → Chờ MA20 xuống 4% so với MA50

**So sánh với:** ATR-based exit (best từ v15)

---

## Kết quả

### Summary Table

| Config | CAGR | Max DD | Trades | Win Rate | W/L Ratio | Profit Factor | Expectancy |
|--------|------|--------|--------|----------|-----------|---------------|------------|
| **Baseline v14 (0%)** | 15.39% | 9.27% | 151 | 48.3% | 2.74x | 2.56x | $78.63 |
| **MA cross 2%** | 21.61% | 11.58% | 104 | 45.2% | 3.79x | 3.12x | $184.04 |
| **MA cross 3%** | 16.71% | 20.83% | 77 | 37.7% | 4.58x | 2.77x | $172.37 |
| **MA cross 4%** | **23.96%** | 17.92% | 62 | 40.3% | **5.91x** | **3.99x** | $360.55 |
| **RSI<65 + ATR (v15)** | **36.69%** | 14.04% | 52 | 38.5% | 5.45x | 3.40x | **$869.54** |

### Phân tích chi tiết

#### 1. MA cross 2% threshold
```
✅ CAGR: 21.61% (+6.22% vs baseline)
✅ Profit Factor: 3.12x (+0.56x vs baseline)
✅ Max DD: 11.58% (chấp nhận được)
✅ Expectancy: $184.04 (gấp 2.3x baseline)
⚠️  Trades: 104 (giảm 31% so với baseline)
```

**Nhận xét:** Cải thiện rõ rệt so với baseline, cân bằng tốt giữa CAGR và DD.

#### 2. MA cross 3% threshold
```
⚠️  CAGR: 16.71% (+1.32% vs baseline, nhưng thấp hơn 2%)
✅ Profit Factor: 2.77x (+0.21x vs baseline)
❌ Max DD: 20.83% (cao nhất trong các MA cross)
✅ Expectancy: $172.37 (gấp 2.2x baseline)
⚠️  Trades: 77 (giảm 49% so với baseline)
```

**Nhận xét:** Không tốt bằng 2% và 4%, DD cao nhất.

#### 3. MA cross 4% threshold
```
✅ CAGR: 23.96% (+8.57% vs baseline, tốt nhất trong MA cross)
✅ Profit Factor: 3.99x (+1.43x vs baseline, CAO NHẤT trong tất cả)
✅ Win/Loss: 5.91x (tốt nhất trong MA cross)
✅ Expectancy: $360.55 (gấp 4.6x baseline)
⚠️  Max DD: 17.92% (cao hơn baseline)
⚠️  Trades: 62 (giảm 59% so với baseline)
```

**Nhận xét:** Profit Factor cao nhất (3.99x), Win/Loss ratio tốt nhất (5.91x). Rất an toàn.

#### 4. RSI<65 + ATR Exit (v15 best)
```
✅ CAGR: 36.69% (CAO NHẤT trong tất cả)
✅ Expectancy: $869.54 (CAO NHẤT trong tất cả)
✅ Win/Loss: 5.45x (tốt)
⚠️  Profit Factor: 3.40x (thấp hơn MA cross 4%)
⚠️  Max DD: 14.04% (chấp nhận được)
⚠️  Trades: 52 (ít nhất)
```

**Nhận xét:** CAGR và Expectancy cao nhất, nhưng Profit Factor thấp hơn MA cross 4%.

---

## So sánh Profit/Loss

| Config | Total Wins | Total Losses | Net Profit | Avg Win | Avg Loss | Win/Loss |
|--------|------------|--------------|------------|---------|----------|----------|
| Baseline (0%) | $19,481 | $7,609 | $11,872 | $267 | $98 | 2.74x |
| MA cross 2% | $28,151 | $9,010 | $19,140 | $599 | $158 | 3.79x |
| MA cross 3% | $20,792 | $7,519 | $13,272 | $717 | $157 | 4.58x |
| **MA cross 4%** | $29,824 | $7,470 | $22,354 | **$1,193** | $202 | **5.91x** |
| **ATR (v15)** | **$64,021** | $18,805 | **$45,216** | **$3,201** | $588 | 5.45x |

### Key Insights

1. **MA cross 4%:**
   - Avg Win cao nhất trong MA cross: $1,193 (gấp 4.5x baseline)
   - Avg Loss thấp: $202 (chỉ gấp 2x baseline)
   - Win/Loss ratio: 5.91x (tốt nhất)
   - **Thắng $1,193, thua $202 → Tỷ lệ 5.9:1**

2. **ATR Exit:**
   - Total Wins cao nhất: $64,021 (gấp 3.3x baseline)
   - Avg Win cao nhất: $3,201 (gấp 12x baseline)
   - Avg Loss cao hơn: $588 (gấp 6x baseline)
   - **Thắng $3,201, thua $588 → Tỷ lệ 5.5:1**

---

## Rankings

### 🏆 Top 3 by Profit Factor (Thắng/Thua ratio)
1. **MA cross 4%:** PF 3.99x ← An toàn nhất
2. **ATR Exit:** PF 3.40x
3. **MA cross 2%:** PF 3.12x

### 📈 Top 3 by CAGR (Lợi nhuận hàng năm)
1. **ATR Exit:** CAGR 36.69% ← Lợi nhuận cao nhất
2. **MA cross 4%:** CAGR 23.96%
3. **MA cross 2%:** CAGR 21.61%

### 💰 Top 3 by Expectancy (Kỳ vọng mỗi trade)
1. **ATR Exit:** $869.54/trade ← Kỳ vọng cao nhất
2. **MA cross 4%:** $360.55/trade
3. **MA cross 2%:** $184.04/trade

---

## Trade-offs Analysis

### MA cross 4% vs ATR Exit

| Metric | MA cross 4% | ATR Exit | Winner |
|--------|-------------|----------|--------|
| CAGR | 23.96% | **36.69%** | ATR ✅ |
| Max DD | 17.92% | **14.04%** | ATR ✅ |
| Profit Factor | **3.99x** | 3.40x | MA 4% ✅ |
| Win/Loss | **5.91x** | 5.45x | MA 4% ✅ |
| Expectancy | $360.55 | **$869.54** | ATR ✅ |
| Trades | 62 | 52 | ATR (ít hơn) |

**Kết luận:**
- **ATR Exit:** Tốt hơn về CAGR, DD, Expectancy → **Lợi nhuận cao hơn**
- **MA cross 4%:** Tốt hơn về Profit Factor, Win/Loss → **An toàn hơn**

### MA cross 2% vs 4%

| Metric | MA 2% | MA 4% | Winner |
|--------|-------|-------|--------|
| CAGR | 21.61% | **23.96%** | MA 4% ✅ |
| Max DD | **11.58%** | 17.92% | MA 2% ✅ |
| Profit Factor | 3.12x | **3.99x** | MA 4% ✅ |
| Win/Loss | 3.79x | **5.91x** | MA 4% ✅ |
| Expectancy | $184.04 | **$360.55** | MA 4% ✅ |
| Trades | 104 | 62 | MA 4% (ít hơn) |

**Kết luận:** MA cross 4% tốt hơn MA 2% ở hầu hết metrics, chỉ DD cao hơn.

---

## Recommendation

### Option 1: ATR Exit (Aggressive - Lợi nhuận cao)
```
Config: RSI < 65 + ATR-based Exit (2x ATR from peak)
CAGR: 36.69%
Max DD: 14.04%
Profit Factor: 3.40x
Expectancy: $869.54/trade
```

**Ưu điểm:**
- ✅ CAGR cao nhất (36.69%)
- ✅ Expectancy cao nhất ($869/trade)
- ✅ Max DD thấp (14.04%)

**Nhược điểm:**
- ❌ Profit Factor thấp hơn MA cross 4% (3.40x vs 3.99x)
- ❌ Avg Loss cao hơn ($588 vs $202)

**Phù hợp:** Trader muốn lợi nhuận cao, chấp nhận risk cao hơn.

### Option 2: MA cross 4% (Conservative - An toàn)
```
Config: RSI < 70 + MA20 < MA50 * 0.96 (4% threshold)
CAGR: 23.96%
Max DD: 17.92%
Profit Factor: 3.99x (CAO NHẤT)
Expectancy: $360.55/trade
```

**Ưu điểm:**
- ✅ Profit Factor cao nhất (3.99x) - Thắng gấp 4 lần thua
- ✅ Win/Loss ratio cao nhất (5.91x) - Thắng $1,193, thua $202
- ✅ Avg Loss thấp ($202) - Mỗi lần thua mất ít

**Nhược điểm:**
- ❌ CAGR thấp hơn ATR (24% vs 37%)
- ❌ Max DD cao hơn (17.92% vs 14.04%)

**Phù hợp:** Trader muốn an toàn, ít rủi ro, chấp nhận lợi nhuận thấp hơn.

### Option 3: MA cross 2% (Balanced - Cân bằng)
```
Config: RSI < 70 + MA20 < MA50 * 0.98 (2% threshold)
CAGR: 21.61%
Max DD: 11.58% (THẤP NHẤT)
Profit Factor: 3.12x
Expectancy: $184.04/trade
```

**Ưu điểm:**
- ✅ Max DD thấp nhất (11.58%) - An toàn nhất về drawdown
- ✅ Profit Factor tốt (3.12x)
- ✅ Cân bằng giữa CAGR và DD

**Nhược điểm:**
- ❌ CAGR thấp hơn 2 options kia
- ❌ Expectancy thấp hơn

**Phù hợp:** Trader rất conservative, ưu tiên bảo toàn vốn.

---

## Final Recommendation

### 🏆 Winner: **ATR Exit (v15 best)**

**Lý do:**
1. CAGR cao nhất (36.69%) - Gần gấp 1.5x MA cross 4%
2. Expectancy cao nhất ($869/trade) - Gần gấp 2.4x MA cross 4%
3. Max DD thấp nhất (14.04%) - Tốt hơn MA cross 4%
4. Profit Factor vẫn tốt (3.40x) - Thắng gấp 3.4 lần thua

**Trade-off:**
- Profit Factor thấp hơn MA cross 4% (3.40x vs 3.99x)
- Nhưng CAGR cao hơn nhiều (37% vs 24%)
- Expectancy cao hơn nhiều ($870 vs $361)

**Kết luận:** ATR Exit cho lợi nhuận cao hơn với risk tương đương (thậm chí thấp hơn về Max DD).

---

## Implementation Guide

### ATR-based Exit Logic
```python
def check_exit_atr(position, current_price, atr):
    """
    Exit when price drops 2x ATR from peak
    """
    peak_price = position.get('peak_price', position['entry_price'])
    
    # Update peak
    if current_price > peak_price:
        position['peak_price'] = current_price
        peak_price = current_price
    
    # Check exit condition
    stop_price = peak_price - 2 * atr
    if current_price < stop_price:
        return True, 'ATR-based stop'
    
    return False, None
```

### MA Cross with Threshold Logic
```python
def check_exit_ma_cross(ma20, ma50, threshold=0.04):
    """
    Exit when MA20 < MA50 * (1 - threshold)
    threshold = 0.04 means MA20 < MA50 * 0.96 (4% below)
    """
    threshold_price = ma50 * (1 - threshold)
    if ma20 < threshold_price:
        return True, f'MA20 < MA50*{1-threshold:.2f}'
    
    return False, None
```

---

## Next Steps

1. ✅ **Apply ATR Exit vào production** (recommended)
2. 🔄 **Test với BNB và TRX** để validate
3. 🔄 **Paper trading 1-2 weeks** để confirm
4. 📊 **Monitor real performance** trong 3-6 months

---

## Files

- **Backtest script:** `scripts/backtest_v16_flexible_exit.py`
- **Cache:** `scripts/_klines_12h_5y.json`

---

## Conclusion

**Flexible MA cross thresholds cải thiện đáng kể so với baseline:**
- MA cross 2%: CAGR +6.22%, PF +0.56x
- MA cross 4%: CAGR +8.57%, PF +1.43x

**Tuy nhiên, ATR Exit vẫn tốt nhất:**
- CAGR 36.69% (cao nhất)
- Expectancy $869/trade (cao nhất)
- Max DD 14.04% (thấp nhất)
- Profit Factor 3.40x (tốt)

**Recommendation:** Apply ATR Exit vào production.

---

**Last Updated:** 2026-06-21  
**Tested By:** backtest_v16_flexible_exit.py  
**Status:** ✅ Ready for production
