# Chiến lược Crypto Trading - Tổng kết & Vấn đề tồn đọng

**Ngày:** 2026-06-20  
**Trạng thái:** Production (v10 Baseline)  
**Hiệu suất:** CAGR=+31.3%, DD=30.6%, SLr=15%, StdDev=82.9%

---

## 1. Cấu trúc chiến lược hiện tại

### 1.1 Core Components
- **Direction-specific Fibonacci cooldown**: LONG/SHORT cooldown độc lập
- **Bear-mode risk reduction**: Lev=2.0, pos=75-90%, SL giảm
- **Regime detection**: Bull/Bear dựa trên MA50 vs MA200
- **Entry signal**: Score-based (ENTRY_MIN=65)

### 1.2 Coin Configuration
| Coin | Bull Lev | Bear Lev | Cap | SL | Trail | CD |
|------|----------|----------|-----|----| ----|-----|
| ETH  | 2.5x     | 2.0x     | 2.5 | 10/8 | 0.04 | 0 |
| BNB  | 3.5x     | 2.0x     | 2.8 | 12/10 | 0.065 | 0 |
| TRX  | 3.5x     | 2.0x     | 2.5 | 12/8 | 0.065 | 5 |

### 1.3 Cooldown Rules
- **Fibonacci**: 2→3, 3→5, 4→8, 5→13 bars (shift=0)
- **Direction-specific**: LONG loss → LONG cooldown only
- **Win reset**: Reset chỉ direction tương ứng

---

## 2. Kết quả backtest (2021-2025)

### 2.1 Performance Summary
```
Coin    CAGR     DD      SLr     2024 Return
ETH     +22.7%   37.2%   16%     -3.1%
BNB     +37.5%   20.6%   15%     +11.1%
TRX     +33.6%   34.1%   13%     +57.6%
AVG     +31.3%   30.6%   15%     +21.9%
```

### 2.2 Yearly Breakdown
```
Year    ETH       BNB       TRX       AVG
2021    +86.5%    +316.0%   +173.6%   +192.0%
2022    +24.6%    +0.0%     -19.5%    +1.7%
2023    +5.5%     +8.4%     +17.1%    +10.3%
2024    -3.1%     +11.1%    +57.6%    +21.9%
2025    +33.5%    +14.1%    +7.0%     +18.2%
```

### 2.3 Consistency (StdDev)
- ETH: 35.1% (best)
- BNB: 137.7% (worst, do 2021 spike)
- TRX: 75.9%
- **Avg: 82.9%**

---

## 3. Vấn đề tồn đọng

### 3.1 ETH 2024 Performance (-3.1%)

**Nguyên nhân:**
- Q2-Q3: 9 lệnh SL liên tiếp (-60.6%)
- Regime detector báo BULL nhưng thị trường sideway (tháng 5-10)
- Cooldown không đủ bảo vệ:
  - 2 losses → 3 bars (36h) - quá ngắn
  - Snowball entries đã mở TRƯỚC khi cooldown active
  - TREND_REV exit ≠ SL (ROI -3~5% thay vì -10%)

**Đã test các giải pháp:**
| Solution | Result |
|----------|--------|
| ADX < 25 filter | DD +6.5%, CAGR -22.7% ❌ |
| Consecutive SL cap (3 SL → skip 14 bars) | DD +3.5%, CAGR -3.6% ❌ |
| Snowball guard (skip if entry 1 underwater) | Worse ❌ |
| Dynamic sizing (score-based exposure) | StdDev +7.9% ❌ |

**Kết luận:** Các filters quá aggressive, làm giảm CAGR hoặc tăng variance. Baseline vẫn tốt nhất.

### 3.2 Cooldown Effectiveness

**Vấn đề:**
- Cooldown ngắn ở giai đoạn đầu (2→3 bars = 36h)
- Không ngăn được snowball entries đã open
- TREND_REV exit không trigger cooldown đầy đủ

**Nguyên nhân sâu:**
- Fibonacci cooldown design cho streak dài (4-5+ losses)
- Không có "emergency brake" cho trường hợp 2-3 losses liên tiếp

### 3.3 BNB Volatility

**Vấn đề:**
- StdDev=137.7% (cao nhất)
- Do 2021 spike +316%
- Các năm sau ổn định hơn (0-14%)

**Có nên giảm BNB leverage?**
- Không test, vì BNB DD=20.6% (tốt nhất trong 3 coins)
- CAGR=37.5% (cao nhất)
- Chấp nhận variance cao để có return cao

### 3.4 Regime Detection Lag

**Vấn đề:**
- MA50 vs MA200 phản ứng chậm
- ETH 2024: regime báo BULL suốt năm nhưng thực tế choppy
- Không có secondary confirmation (volume, ADX, sideway score)

**Đã implement:**
- `compute_adx()` và `compute_sideway_score()` trong crypto_trading.py
- Nhưng chưa dùng trong entry logic (test cho thấy giảm performance)

---

## 4. Các giải pháp đã test & bị reject

| Feature | Impact | Reason |
|---------|--------|--------|
| Regime-dependent cooldown (Bear L→5, Bull L→3) | No improvement | BASELINE (L→3, S→3) vẫn tốt nhất |
| ETH short lev=2.5 (strong signal) | Negligible (+0.1% CAGR) | Không đáng |
| BNB short | DD +0.3%, CAGR +0.1% | Không đáng |
| ADX < 25 filter | DD +6.5%, CAGR -22.7% | Quá aggressive |
| Consecutive SL cap | DD +3.5%, CAGR -3.6% | Giảm performance |
| Snowball guard | Worse | Chặn good entries |
| Dynamic sizing | StdDev +7.9% | Tăng variance |
| Sideway filter | Worse | Giảm performance |

---

## 5. Hướng cải thiện tiềm năng (chưa test)

### 5.1 Emergency Brake
- **Idea**: 3 SL trong 1 tuần → pause trading 3 ngày
- **Risk**: Có thể bỏ qua recovery trades
- **Test effort**: Medium

### 5.2 Adaptive Cooldown
- **Idea**: Cooldown dựa trên magnitude của losses (không chỉ count)
- **Example**: 2 SL với ROI=-10% each → longer cooldown
- **Risk**: Complex logic
- **Test effort**: High

### 5.3 Multi-timeframe Confirmation
- **Idea**: Require higher timeframe trend alignment
- **Example**: 12h signal + 1d trend confirmation
- **Risk**: Giảm số lượng trades
- **Test effort**: Medium

### 5.4 Position Sizing theo Volatility
- **Idea**: Reduce size khi ATR cao (high volatility)
- **Risk**: Có thể miss strong moves
- **Test effort**: Medium

### 5.5 Correlation Filter
- **Idea**: Skip entry nếu correlated coin đã có position
- **Example**: ETH-BNB correlation > 0.8 → skip
- **Risk**: Giảm diversification
- **Test effort**: High

---

## 6. Recommendations

### 6.1 Short-term (Production)
- ✅ Giữ BASELINE v10 (hiện tại)
- ✅ Monitor ETH Q2-Q3 pattern trong 2026
- ✅ Không thêm filters mới (đã test, đều worse)

### 6.2 Medium-term (Research)
- 🧪 Test "emergency brake" (3 SL/week → pause 3 days)
- 🧪 Test adaptive cooldown (magnitude-based)
- 🧪 Test position sizing theo volatility

### 6.3 Long-term (Architecture)
- 🏗️ Tách regime detection thành module riêng
- 🏗️ Add walk-forward optimization
- 🏗️ Real-time backtest validation

---

## 7. Metrics theo dõi

### 7.1 Production Monitoring
- ETH quarterly returns (đặc biệt Q2-Q3)
- Consecutive SL streaks (>3)
- Regime detection accuracy (manual review)
- SLr per coin (target <20%)

### 7.2 Strategy Health
- Avg DD < 35% ✅ (currently 30.6%)
- Avg CAGR > 25% ✅ (currently 31.3%)
- Avg SLr < 20% ✅ (currently 15%)
- StdDev < 100% ✅ (currently 82.9%)

### 7.3 Risk Alerts
- Any coin DD > 40% → review immediately
- Any quarter return < -15% → investigate
- SLr > 25% for any coin → review SL levels

---

## 8. Files & Scripts

### 8.1 Production
```
scripts/crypto_trading.py       - Main trading bot
scripts/breaking_news.py        - News alerts
scripts/rss_digest.py           - RSS feed digest
scripts/reset_states.py         - Reset Firestore states
```

### 8.2 Development
```
scripts/backtest_optimal.py     - Backtest engine (v10)
scripts/optimize_profile.py     - Profile optimization
```

### 8.3 Configuration
```
wrangler.toml                   - Cloudflare Worker config
package.json                    - Node dependencies
requirements.txt                - Python dependencies
.github/workflows/              - CI/CD workflows
```

### 8.4 Data
```
scripts/_klines_12h_5y.json    - 5Y candle cache (gitignored)
backtest_data/                  - Backtest results cache (gitignored)
```

---

## 9. Conclusion

**Chiến lược hiện tại (BASELINE v10) là tốt nhất trong tất cả variants đã test.**

Các cải tiến (filters, dynamic sizing, sideway detection) đều làm giảm performance hoặc tăng variance. Đôi khi "đơn giản là tốt nhất".

**Ưu điểm:**
- CAGR +31.3% (solid)
- DD 30.6% (acceptable)
- SLr 15% (tốt, <20%)
- Consistency ổn (StdDev 82.9%)

**Nhược điểm:**
- ETH 2024 underperform (-3.1%)
- BNB variance cao (do 2021 spike)
- Không có protection cho consecutive SL streaks ngắn

**Next steps:**
1. Monitor production performance
2. Research emergency brake và adaptive cooldown
3. Review lại sau 6 tháng (cuối 2026)

---

**Generated:** 2026-06-20  
**Last updated:** 2026-06-20  
**Status:** ✅ Production ready
