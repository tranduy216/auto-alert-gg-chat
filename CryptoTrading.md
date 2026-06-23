# Crypto Trading — v13 BTC ADX-Safe Strategy

**Baseline:** 2026-06-22

## Strategy Overview

3-tier system based on BTC trend strength:

| BTC State | Condition | Strategy |
|-----------|-----------|----------|
| **Bull (strong)** | ADX ≥ 22, MA50 > MA120 | Long: 3.5x snowball, staggered TP 10/20/30%, trail 11% |
| **Bear (strong)** | ADX ≥ 22, MA50 < MA120 | Short: 3.5x snowball, staggered TP 10/20/30%, trail 11%. ETH bear mode 2x/7%trail/TP40% |
| **Safe (weak)** | ADX < 22 | Isolated: 1.5x, 3.5% entry, SL 3.3%, MA buf 2% |

BNB BTC bear long: isolated 2x, 5% entry, SL 4.5%, MA buf 2.5%.

---

## Config

| Coin | ADX | Snow score | Entry | Short | Bear long |
|------|:---:|:----------:|:-----:|:-----:|:---------:|
| ETH | 12 | 60 | 65 | Yes | 2x/7%/trail7%/TP40% |
| BNB | 15 | 65 | 65 | No | 2x/4.5%/isolated TP sum=100% |
| TRX | 18 | 65 | 65 | No | Cash |

Snowball: 4 levels (5/10/15/20%), 0.07 each, init 0.10. Pos 1.3x.

Safe mode: 1.5x, SL 3.3%, entry 3.5%, TP 3/7/20/25/30%(sum=100%), peak DD 5%.

## Performance

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +125% | +147% | +115% | +129% |
| 2022 | +20% | -1% | -8% | +4% |
| 2023 | +18% | +6% | +39% | +21% |
| 2024 | +21% | +109% | +82% | +71% |
| 2025 | +17% | +31% | +11% | +20% |
| **CAGR** | **+34.7%** | **+41.7%** | **+36.7%** | **+37.7%** |

| Coin | Max DD | Final ($10K→) |
|------|:------:|:-------------:|
| ETH | 51.5% | $107,481 |
| BNB | 46.6% | $119,784 |
| TRX | 52.8% | $98,765 |
| **Avg** | **50.3%** | **$108,677** |

## Usage

```bash
# Tests (46/46)
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Backtest
python3 scripts/backtest_bull_snowball.py --parallel
```
