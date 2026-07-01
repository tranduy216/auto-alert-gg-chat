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
| Max Margin (per coin) | 75% (150% exposure @ 2x) | 75% (150% exposure @ 2x) |
| Exit Mode | Trailing (82% of peak → 18% price DD, ~36% ROI DD @ 2x) | MA Cross (MA40/MA90) |
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
| Max total exposure | 150% of $10k (50% margin @ 3x) |
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
| 2021 | +13.3% | +1.7% | +27.4% |
| 2022 | -10.7% | -3.2% | -7.7% |
| 2023 | +27.7% | +20.8% | +24.8% |
| 2024 | +312.6% | +52.6% | +207.2% |
| 2025 | +27.8% | +113.0% | +44.9% |
| 2026 | +9.8% | +13.4% | +10.8% |

### Daily Trading (BNB)

| Metric | Value |
|---|---|
| **CAGR** | **+10.4%** |
| **Max DD** | **19.3%** |
| Final | $29,226 (2.92x) |
| WR | 69.1% (76W/34L) |

| Year | Return |
|---|---|
| 2021 | +7.4% |
| 2022 | +32.3% |
| 2023 | +29.4% |
| 2024 | +2.3% |
| 2025 | +46.2% |
| 2026 | +6.2% |

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

## Usage Notes

1. **Backtest before deploy**: Any changes to `entry_conditions` in `backtest_shared.py` affect both backtest and live. Always run `combined_backtest.py` and `backtest_daily_trading.py` before pushing.

2. **Run test suite**: Run `python3 scripts/test/test_all.py` and `python3 scripts/test/test_daily_trading.py`, ensure 0 failures before each deploy.

3. **Required Secrets** (GitHub Secrets):
   - `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` — OKX trading
   - `FIREBASE_SERVICE_ACCOUNT` — trade state persistence
   - `DISCORD_TRADING_WEBHOOK_URL` — Discord notifications
   - `COINGECKO_API_KEY` (optional) — data fallback

4. **Pyramid Risk Controls**:
   - Long: max margin 75% (150% exposure @ 2x), short: max margin 40% (80% exposure @ 2x)
   - Short: 2-day cooldown between entries
   - TRX: trailing stop at 82% of peak (18% price drawdown, ~36% ROI drawdown @ 2x), XAU: MA40/MA90 crossover exit
   - XAU pyramid auto-adds entry at +8%, +15%, +22% ROI...

5. **BNB Daily Risk Controls**:
   - Max 2 entries/day, 6h cooldown, total exposure cap 150% of $10k
   - Dynamic TP/SL based on 12h ATR (TP = 3x ATR, SL = 3x ATR)
   - Fallback TP 6%, SL 3% when ATR unavailable
   - On direction flip (LONG→SHORT or vice versa), close all existing positions

6. **Do not trade manually on OKX**: The system auto-checks signals and executes via GitHub Actions. Only trigger manually for emergency testing.

## Changelog

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
