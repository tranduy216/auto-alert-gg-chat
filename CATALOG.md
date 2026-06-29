# Auto Alert GG Chat — Crypto Trading System

## Architecture

```
backtest_shared.py    ← shared: sma, atr, entry_conditions, constants
    ├── crypto_trading.py     (LIVE pyramid: TRX long, XAU long)
    ├── combined_backtest.py  (backtest per coin)
    ├── pooled_backtest.py    (pooled multi-coin backtest)
    ├── daily_trading.py      (LIVE 12h/1D hybrid: BNB long+short)
    └── backtest_daily_trading.py
```

## Strategies

| Strategy | Coins | Direction | Leverage | Entry | Exit |
|---|---|---|---|---|---|
| **Pyramid** | TRX, XAU | Long-only | 2x | MA pullback (entry_conditions) | Trailing/MA cross + TP ladder |
| **Daily** | BNB | Long + Short | 3x | 1D MA3>MA5>MA7 trend, 12h pullback to MA3 | OCO (ATR-based TP/SL) |

## BNB Daily Trading Config

| Param | Value |
|---|---|
| Entry margin | 5% of $10k |
| Leverage | 3x |
| Entry size | $1,500 |
| Trend | 1D MA3 > MA5 > MA7 (long) / MA3 < MA5 < MA7 (short) |
| Entry signal | 12h: MA3 near MA7 (<1%) AND price near MA3 (<1%) |
| Max entries/day | 2, 6h cooldown |
| TP/SL | Dynamic ATR-based (SL×3, TP×3 ATR) |

## BNB Backtest Results (v0.1-baseline)

| Metric | Value |
|---|---|
| CAGR | +10.3% |
| Max DD | 19.3% |
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

## Tests

```bash
python3 scripts/test/test_all.py             # 190+ tests
python3 scripts/test/test_daily_trading.py   # 50+ tests
```

## Workflows

- `.github/workflows/crypto-trading.yml` — `workflow_dispatch` / `repository_dispatch`
- `.github/workflows/daily-trading.yml` — `workflow_dispatch` / `repository_dispatch: trigger-daily-trading`

## Deploy

```bash
git add -A && git commit -m "deploy: <desc>" && git push origin master
gh workflow run "Crypto Trading System"
gh workflow run "Daily Trading (BNB)"
```

## Changelog

### v0.1-baseline (2026-06-29)
- BNB daily trading: 5% margin, 3x leverage
- Crypto trading: TRX + XAU long only (BTC removed)
- Fixed: leverage set before order, avg_ep None crash, backtest exit price consistency
- 0 test failures across both suites
