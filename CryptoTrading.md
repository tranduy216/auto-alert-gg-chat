# Crypto Trading — v13 BTC ADX-Safe Strategy

**Baseline:** 2026-06-23

## Strategy

3-tier based on BTC trend strength (MA50 vs MA120, ADX 14):

| BTC State | Condition | Long | Short |
|-----------|-----------|------|-------|
| **Bull** | ADX ≥ 22, MA50 > MA120 | 3.5x snowball 4 lvls, staggered TP 10/20/30%, trail 11%/50% | Blocked |
| **Bear** | ADX ≥ 22, MA50 < MA120 | ETH: 2x trail7%/TP40%. BNB/TRX: SAFE isolated | ETH: 3.5x snowball, score≥70 |
| **Safe** | ADX < 22 | 1.5x, 3.5% entry, SL 3.3%, SAFE TP, MA buf 2% | 1.5x isolated |

---

## Per-Coin Config

| | ETH | BNB | TRX |
|---|:---:|:---:|:---:|
| Bull lev | 3.5x | 3.5x | 3.5x |
| Bull SL | no SL (max 5%) | 20% | 12% |
| Entry size | 8% × 1.3 | 25% × 1.3 | 25% × 1.3 |
| Snowball | 4 lvls 0.07 | 4 lvls 0.07 | 4 lvls 0.07 |
| ADX min | 12 | 15 | 18 |
| Snow score | 60 | 65 | 65 |
| Entry score | 65 | 65 | 65 |
| MA buffer | 0% | 1% | 1% |
| Short | Yes (score≥70) | No | No |
| Bear long | 2x/trail7%/TP40% | SAFE isolated | Cash |
| Cooldown | 3 bars | 1 bar | 1 bar |

Global: MAX_POS 120%, init 0.10, trail 11% @40% close 50%, cooldown 5 bars.

Safe: 1.5x, SL 3.3%, entry 3.5%, TP 3/7/20/25/30%(sum=100%), peak DD 5%.

## Performance (2021–2025)

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +135% | +147% | +120% | +134% |
| 2022 | +13% | -1% | -13% | -0% |
| 2023 | +19% | +6% | +40% | +22% |
| 2024 | +56% | +109% | +87% | +84% |
| 2025 | +13% | +31% | +11% | +18% |
| **CAGR** | **+38.9%** | **+41.7%** | **+36.9%** | **+39.2%** |

| Coin | Max DD | Final ($10K→) |
|------|:------:|:-------------:|
| ETH | 50.8% | $58,273 |
| BNB | 46.6% | $64,968 |
| TRX | 55.1% | $53,859 |
| **Avg** | **50.8%** | **$59,033** |

## Usage

```bash
# Tests (46/46)
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Backtest
python3 scripts/backtest_bull_snowball.py --parallel
```
