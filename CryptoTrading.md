# Crypto Trading — HYBRID Strategy v12

**Baseline:** 2026-06-22

## Strategy Overview

| BTC | Coin | Direction | Leverage | SL | Trail | Snowball |
|-----|------|-----------|:--------:|:--:|:-----:|:--------:|
| Bull | All | Long | 3.5x | ETH=max_loss 5%, BNB=20%, TRX=12% | 11% @30% ROI, close 50% | 4 levels |
| Bull | ETH/TRX | Short | 3.5x | 10% | TP 8/15/25/40%, trail 4-6.5% | — |
| Bear | ETH | Long | 2.0x | 7% | trail 7%, TP 40%/50% | — |
| Bear | BNB | Long (CT) | 2.0x | 9% | staggered TP 7/15/25/40%, trail 7% | — |
| Bear | TRX | — | — | — | cash | — |

BNB BTC bear override: ADX≥20, buffer 2.5%, lev 3.0x, max_loss 25%.

---

## Config

| Coin | ADX | MA buf | Snow score | Entry | Short | BTC bear |
|------|:---:|:------:|:----------:|:-----:|:-----:|:--------:|
| ETH | 12 | 0% | 60 | 65 | Yes | 2x/7%/trail7%/TP40% |
| BNB | 15 | 1% | 65 | 65 | No | CT: 2x/9%/staggered TP 70% |
| TRX | 18 | 1% | 65 | 65 | No | Cash |

Cooldown: ETH=3, BNB=1, TRX=1 bars.

## Performance

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +168% | +179% | +139% | +162% |
| 2022 | +21% | -23% | -7% | -3% |
| 2023 | +15% | +4% | +29% | +16% |
| 2024 | +31% | +108% | +139% | +93% |
| 2025 | +17% | +15% | +9% | +14% |
| **CAGR** | **+37.3%** | **+32.0%** | **+44.6%** | **+38.0%** |

| Coin | Max DD | SL Rate | Final ($10K→) |
|------|:------:|:-------:|:-------------:|
| ETH | 38.4% | 0.0% | $54,688 |
| BNB | 61.5% | 5.1% | $44,341 |
| TRX | 51.2% | 0.0% | $72,405 |
| **Avg** | **50.4%** | **1.7%** | **$57,145** |

## Usage

```bash
# Unit tests (41/41)
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Backtest
python3 scripts/backtest_bull_snowball.py --parallel

# Single coin
python3 scripts/backtest_bull_snowball.py --coin ETH --years 2022,2023,2024,2025
```
