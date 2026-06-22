# Crypto Trading — HYBRID Strategy v11

**Baseline:** 2026-06-22

## Strategy Overview

4-mode system based on BTC regime × direction per coin:

| BTC | Direction | Leverage | SL | Trail | Snowball |
|-----|-----------|:--------:|:--:|:-----:|:--------:|
| Bull | Long | 3.5x | ETH=no SL, BNB/TRX=40% | 11% @40-50% ROI, close 40% | Yes (5 levels) |
| Bull | Short | 2.0x | 8-10% | TP schedule, no trail | No |
| Bear | Long (BNB) | 2.0x | 8% | Fixed TP 50%@15%, no trail | No |
| Bear | Long (ETH) | — | — | cash | — |
| Bear | Long (TRX) | — | — | cash | — |

Coin regime: MA50 > MA120 * (1 + buffer). Buffer: ETH=0%, BNB=1%, TRX=1%.

---

## Per-Coin Config

| Coin | ADX | MA buf | Snow score | Entry score | Short | BTC bear long |
|------|:---:|:------:|:----------:|:-----------:|:-----:|:-------------:|
| ETH | 12 | 0% | 65 | 65 | Yes | No (cash) |
| BNB | 15 | 1% | 65 | 65 | No | Yes (2x/8%/TP50%@15%) |
| TRX | 18 | 1% | 65 | 65 | No | No (cash) |

### Entry Cooldown

ETH=3 bars, BNB=1 bar, TRX=1 bar.

### BTC Bear Override

When BTC is bear, BNB bull entries tighten: ADX≥20, buffer 2.5%, lev 3.0x, max_loss 25%.

---

## Performance (2021–2025)

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +109% | +511% | +74% | +231% |
| 2022 | +28% | -3% | -6% | +6% |
| 2023 | -0.5% | -1% | +17% | +5% |
| 2024 | -8% | +28% | +105% | +42% |
| 2025 | +39% | +11% | +7% | +19% |
| **CAGR** | **+25.6%** | **+47.4%** | **+30.3%** | **+34.4%** |

| Coin | Max DD | SL Rate | Final ($10K→) |
|------|:------:|:-------:|:-------------:|
| ETH | 43.7% | 7.4% | $33,969 |
| BNB | 53.9% | 2.7% | $80,158 |
| TRX | 43.8% | 0.0% | $41,281 |
| **Avg** | **47.1%** | **3.4%** | **$51,803** |

---

## Project Structure

```
scripts/
├── trading_config.py           ← Single source of truth
├── crypto_trading.py           ← Production implementation
├── backtest_bull_snowball.py   ← Backtest (matches production)
├── breaking_news.py            ← News alerts
├── rss_digest.py               ← RSS feed parser
└── reset_states.py             ← Firestore state reset

tests/
├── test_crypto_trading.py      ← Unit tests (33 tests)
└── test_utils.py               ← Utility tests (8 tests)
```

## Usage

```bash
# Unit tests (41/41)
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Backtest — all coins, all years
python3 scripts/backtest_bull_snowball.py --parallel

# Backtest — specific coin, specific years
python3 scripts/backtest_bull_snowball.py --coin ETH --years 2022,2023,2024,2025

# Tune config → edit trading_config.py → rm -rf scripts/.cache
```
