# Auto Alert GG Chat — Crypto Trading System

## Architecture

```
backtest_shared.py    ← shared: sma, atr, entry_conditions, constants
    ├── crypto_trading.py     (LIVE pyramid: TRX long, XAU long)
    ├── combined_backtest.py  (backtest per coin, portfolio)
    └── pooled_backtest.py    (pooled multi-coin backtest)
```

## Strategies

| Strategy | Coins | Direction | Leverage | Entry | Exit |
|---|---|---|---|---|---|
| **Pyramid** | TRX, XAU | Long-only | 3x | MA pullback (entry_conditions) | Trailing/MA cross + TP ladder |

### Pyramid Strategy Config

| Param | TRX | XAU |
|---|---|---|
| MA Period | 15 | 20 |
| MA Buffer | 5% | 5% |
| Vol Bars | 3 | 3 |
| Leverage | 3x | 3x |
| Max Margin (per coin) | 75% (225% exposure @ 3x) | 75% (225% exposure @ 3x) |
| Exit Mode | Trailing (82% of peak → 18% price DD, ~54% ROI DD @ 3x) | MA Cross (MA40/MA90) |
| TP Schedule | 10/20/30/40/50% | - |
| Pyramid | Disabled | Enabled (+7% ROI step) |

## Backtest Results

### Pyramid Strategy (TRX + XAU Portfolio)

| Metric | Value |
|---|---|
| **Portfolio CAGR** | **+61.7%** |
| **Portfolio Max DD** | **25.5%** |

| Coin | CAGR | Max DD | Leverage |
|---|---|---|---|
| TRX-L | +47.7% | 38.3% | 3.0x |
| XAU-L | +43.1% | 47.5% | 3.0x |

| Year | TRX | XAU | Portfolio |
|---|---|---|---|
| 2021 | +22.5% | +2.2% | +44.1% |
| 2022 | -15.8% | -5.3% | -12.1% |
| 2023 | +60.8% | +33.2% | +50.3% |
| 2024 | +328.5% | +79.8% | +244.2% |
| 2025 | +36.9% | +150.6% | +57.0% |
| 2026 | +24.9% | +14.5% | +22.0% |

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
python3 scripts/test/test_all.py
```

## Workflows

- `.github/workflows/crypto-trading.yml` — `workflow_dispatch` / `repository_dispatch: trigger-trading`
- `.github/workflows/daily-rss-digest.yml` — 2 lần/ngày, gửi tin tức và snapshot hàng hóa
- Cloudflare Worker (`cloudflare-worker.js`) — cron every 30min triggers `trigger-trading`

### Commodity snapshot

`scripts/utils/commodity_prices.py` lấy giá futures công khai từ Yahoo Finance
(không cần secret) và so sánh giá đóng cửa gần nhất với dữ liệu 1 năm:

- mốc 3 tháng, 6 tháng và 1 năm;
- đánh dấu `cao nhất`/`thấp nhất` trong từng mốc hoặc hiển thị phần trăm thay đổi;
- bao phủ kim loại, năng lượng, gạo, đường, cà phê, ngô, lúa mì và heo hơi.

RSS Commodities được lọc thêm theo các sự kiện cung–cầu như thời tiết, mùa vụ,
tồn kho, dịch bệnh, cắt giảm sản lượng, hạn chế xuất khẩu, đình công và logistics.
Giá futures là giá tham chiếu có thể trễ; hợp đồng không có dữ liệu sẽ được bỏ qua
để không làm hỏng toàn bộ bản tin.

## Deploy

```bash
git add -A && git commit -m "deploy: <desc>" && git push origin master
gh workflow run "Crypto Trading System"
```

## Usage Notes

1. **Backtest before deploy**: Any changes to `entry_conditions` in `backtest_shared.py` affect both backtest and live. Always run `combined_backtest.py` before pushing.

2. **Run test suite**: Run `python3 scripts/test/test_all.py`, ensure 0 failures before each deploy.

3. **Required Secrets** (GitHub Secrets):
   - `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` — OKX trading
   - `FIREBASE_SERVICE_ACCOUNT` — trade state persistence
   - `DISCORD_TRADING_WEBHOOK_URL` — Discord notifications
   - `COINGECKO_API_KEY` (optional) — data fallback

4. **Pyramid Risk Controls**:
   - Long: max margin 75% per coin (225% exposure @ 3x)
   - TRX: trailing stop at 82% of peak (18% price drawdown, ~54% ROI drawdown @ 3x), XAU: MA40/MA90 crossover exit
   - XAU pyramid auto-adds entry at +8%, +15%, +22% ROI...

5. **Do not trade manually on OKX**: The system auto-checks signals and executes via GitHub Actions. Only trigger manually for emergency testing.

## Changelog

### v0.4 (2026-07-14)
- Removed BNB daily trading (workflow, scripts, tests, cloudflare trigger)
- Increased TRX/XAU leverage from 2x to 3x

### v0.3 (2026-07-01)
- Added max total exposure cap to BNB daily trading: 150% of $10k (50% margin @ 3x)
- Cap applied in both live and backtest

### v0.2 (2026-06-30)
- BNB daily trading: 5% margin, 3x leverage, OCO algo orders
- Crypto trading: TRX + XAU long only (MA pullback + pyramid)
- XAU pyramid: auto-add entry every +7% ROI
- Fixed: leverage set before order, avg_ep None crash, backtest exit price consistency
- Dynamic ATR-based TP/SL for BNB
- 0 test failures across both suites
