# Crypto Trading — v13 BTC ADX-Safe Strategy

**Baseline:** 2026-06-23

## Strategy

3-tier based on BTC trend strength (MA50 vs MA120):

| BTC State | Condition | Long | Short |
|-----------|-----------|------|-------|
| **Bull (strong)** | ADX ≥ 22, MA50 > MA120 | 3.5x snowball, staggered TP 10/20/30%, trail 11%/50% | Blocked |
| **Bear (strong)** | ADX ≥ 22, MA50 < MA120 | ETH: 2x trail7%/TP40%. BNB: isolated 2x | 3.5x snowball + trail (ETH) |
| **Safe (weak)** | ADX < 22 | 1.5x, 3.5% entry, SL 3.3%, MA buf 2%, isolated | 1.5x isolated |

BNB bear: 2x, 5% entry, SL 4.5%, TP sum=100% (3/7/20/25/30%), peak DD 5%.

---

## Config

| Coin | ADX | MA buf | Snow score | Entry | Short | Bear long |
|------|:---:|:------:|:----------:|:-----:|:-----:|:---------:|
| ETH | 12 | 0% | 60 | 65 | Yes | 2x/7%/trail7%/TP40% |
| BNB | 15 | 1% | 65 | 65 | No | 2x/4.5%/isolated TP 100% |
| TRX | 18 | 1% | 65 | 65 | No | Cash |

Snowball: 4 levels (5/10/15/20%), 0.07 each, init 0.10. Pos 1.3x.
Safe: 1.5x, SL 3.3%, entry 3.5%, TP sum=100%, peak DD 5%.
Cooldown: ETH=3, BNB=1, TRX=1 bars.

## Performance

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
| ETH | 50.8% | $162,408 |
| BNB | 46.6% | $119,784 |
| TRX | 55.1% | $100,963 |
| **Avg** | **50.8%** | **$127,718** |

## Usage

```bash
# Tests (46/46)
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Backtest
python3 scripts/backtest_bull_snowball.py --parallel
```
