# Auto Alert GG Chat — Crypto Trading System

## Architecture

```
backtest_shared.py    ← shared: sma, atr, entry_conditions, constants
    ├── crypto_trading.py     (LIVE pyramid: TRX long, XAU long)
    ├── combined_backtest.py  (backtest per coin, portfolio)
    ├── pooled_backtest.py    (pooled multi-coin backtest)
    ├── daily_trading.py      (LIVE 12h/1D hybrid: BNB long+short)
    └── backtest_daily_trading.py
```

## Strategies

| Strategy | Coins | Direction | Leverage | Entry | Exit |
|---|---|---|---|---|---|
| **Pyramid** | TRX, XAU | Long-only | 2x | MA pullback (entry_conditions) | Trailing/MA cross + TP ladder |
| **Daily** | BNB | Long + Short | 3x | 1D MA3>MA5>MA7 trend, 12h pullback to MA3 | OCO (ATR-based TP/SL) |

### Pyramid Strategy Config

| Param | TRX | XAU |
|---|---|---|
| MA Period | 15 | 20 |
| MA Buffer | 5% | 5% |
| Vol Bars | 3 | 3 |
| Leverage | 2x | 2x |
| Exit Mode | Trailing (82%) | MA Cross (MA40/MA90) |
| TP Schedule | 10/20/30/40/50% | - |
| Pyramid | Disabled | Enabled (+7% ROI step) |

### BNB Daily Trading Config

| Param | Value |
|---|---|
| Entry margin | 5% of $10k |
| Leverage | 3x |
| Entry size | $1,500 |
| Trend | 1D MA3 > MA5 > MA7 (long) / MA3 < MA5 < MA7 (short) |
| Entry signal | 12h: MA3 near MA7 (<1%) AND price near MA3 (<1%) |
| Max entries/day | 2, 6h cooldown |
| TP/SL | Dynamic ATR-based (SLx3, TPx3 ATR) |

## Backtest Results

### Pyramid Strategy (TRX + XAU Portfolio)

| Metric | Value |
|---|---|
| **Portfolio CAGR** | **+45.7%** |
| **Portfolio Max DD** | **18.9%** |

| Coin | CAGR | Max DD | Leverage |
|---|---|---|---|
| TRX-L | +36.2% | 27.4% | 2.0x |
| XAU-L | +32.3% | 32.5% | 2.0x |

| Year | TRX | XAU | Portfolio |
|---|---|---|---|
| 2018 | +0.0% | +0.0% | +0.0% |
| 2019 | -4.4% | +0.0% | +0.0% |
| 2020 | +41.3% | +0.0% | +0.0% |
| 2021 | +13.3% | +1.7% | +27.4% |
| 2022 | -10.7% | -3.2% | -7.7% |
| 2023 | +27.7% | +20.8% | +24.8% |
| 2024 | +312.6% | +52.6% | +207.2% |
| 2025 | +27.8% | +113.0% | +44.9% |
| 2026 | +9.8% | +13.4% | +10.8% |

### Daily Trading (BNB)

| Metric | Value |
|---|---|
| **CAGR** | **+10.3%** |
| **Max DD** | **19.3%** |
| Final | $29,227 (2.92x) |
| WR | 68.8% (75W/34L) |

| Year | Return |
|---|---|
| 2021 | +7.4% |
| 2022 | +32.3% |
| 2023 | +32.6% |
| 2024 | -1.5% |
| 2025 | +48.5% |
| 2026 | +6.0% |

## State

- Firebase Firestore (primary) → `trading_state/{coin}` for entries, `{coin}_daily` for daily counter
- Local JSON fallback: `_trading_state.json`

## Data Sources

Priority: OKX → CoinMarketCap → CoinGecko → Binance (local cache)

- `fetch_candles_okx()` — primary (daily bars)
- `fetch_candles_cmc()` — fallback 1
- `fetch_candles_coingecko()` — fallback 2
- `fetch_binance()` — last resort (12h→1d aggregation)

## Tests

```bash
python3 scripts/test/test_all.py             # 190+ tests
python3 scripts/test/test_daily_trading.py   # 50+ tests
```

## Workflows

- `.github/workflows/crypto-trading.yml` — `workflow_dispatch` / `repository_dispatch: trigger-trading`
- `.github/workflows/daily-trading.yml` — `workflow_dispatch` / `repository_dispatch: trigger-daily-trading`

## Deploy

```bash
git add -A && git commit -m "deploy: <desc>" && git push origin master
gh workflow run "Crypto Trading System"
gh workflow run "Daily Trading (BNB)"
```

## Lưu ý sử dụng

1. **Backtest trước khi deploy**: Mọi thay đổi entry_conditions trong `backtest_shared.py` đều ảnh hưởng đồng thời backtest và live. Luôn chạy `combined_backtest.py` và `backtest_daily_trading.py` trước khi push.

2. **Kiểm tra test suite**: Chạy `python3 scripts/test/test_all.py` và `python3 scripts/test/test_daily_trading.py`, đảm bảo 0 failures trước mỗi lần deploy.

3. **Secrets bắt buộc** (GitHub Secrets):
   - `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` — giao dịch OKX
   - `FIREBASE_SERVICE_ACCOUNT` — lưu trạng thái trade
   - `DISCORD_TRADING_WEBHOOK_URL` — thông báo Discord
   - `COINGECKO_API_KEY` (optional) — data fallback

4. **Pyramid kiểm soát rủi ro**:
   - Long: max margin 75%, short: max margin 40%
   - Short có cooldown 2 ngày giữa các lần entry
   - TRX: trailing stop 82%, XAU: MA40/MA90 crossover exit
   - XAU pyramid tự động thêm entry khi ROI đạt +8%, +15%, +22%...

5. **BNB Daily kiểm soát rủi ro**:
   - Max 2 entries/ngày, cooldown 6h giữa entries
   - TP/SL động dựa trên ATR 12h (TP = 3x ATR, SL = 3x ATR)
   - Fallback TP 6%, SL 3% khi không có ATR
   - Khi direction flip (LONG→SHORT hoặc ngược lại), đóng toàn bộ position cũ

6. **Không chạy thủ công trên OKX**: System tự động check signal và execute qua GitHub Actions. Chỉ trigger thủ công khi cần test khẩn cấp.

## Changelog

### v0.2 (2026-06-30)
- BNB daily trading: 5% margin, 3x leverage, OCO algo orders
- Crypto trading: TRX + XAU long only (MA pullback + pyramid)
- XAU pyramid: tự động thêm entry mỗi +7% ROI
- Fixed: leverage set before order, avg_ep None crash, backtest exit price consistency
- Dynamic ATR-based TP/SL for BNB
- 0 test failures across both suites
