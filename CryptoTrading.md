# Crypto Trading — v13 BTC ADX-Safe Strategy

**Baseline:** 2026-06-23

## Strategy

3-tier based on BTC trend strength (MA50 vs MA120, ADX 14):

| BTC State | Condition | Long | Short |
|-----------|-----------|------|-------|
| **Bull** | ADX ≥ 22, MA50 > MA120 | 3.5x snowball 3 lvls, staggered TP 10/20/30%, trail 11%/50% | Blocked |
| **Bear** | ADX ≥ 22, MA50 < MA120 | ETH: 2x trail7%/TP40%. BNB/TRX: SAFE isolated | ETH: 3.5x snowball, score≥70 |
| **Safe** | ADX < 22 | 1.5x, 3.5% entry, SL 3.3%, SAFE TP, MA buf 2% | 1.5x isolated |

## Per-Coin Config

| | ETH | BNB | TRX |
|---|:---:|:---:|:---:|
| Bull lev | 3.5x | 3.5x | 3.5x |
| Bull SL | no SL (max 5%) | 20% | 12% |
| Entry size | 8% × 1.3 | 25% × 1.3 | 25% × 1.3 |
| Snowball | 3 lvls × 0.06 | 3 lvls × 0.06 | 3 lvls × 0.06 |
| Staggered TP | 10/10, 20/10, 30/10% | same | same |
| Trail | 11% @40% close 50% | same | same |
| ADX min | 12 | 15 | 18 |
| Short | Yes (score≥70) | No | No |
| Bear long | 2x/trail7%/TP40% | SAFE isolated | Cash |
| Cooldown | 3 bars | 1 bar | 1 bar |

Safe mode: 1.5x, SL 3.3%, entry 3.5%, TP sum=100%, peak DD 5%, MA buf 2%.

## Performance (2021–2025)

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +140% | +187% | +142% | +156% |
| 2022 | +10% | -0.5% | -12% | -1% |
| 2023 | +26% | +5% | +36% | +22% |
| 2024 | +52% | +99% | +81% | +77% |
| 2025 | +10% | +28% | +11% | +16% |
| **CAGR** | **+38.2%** | **+43.6%** | **+38.0%** | **+39.9%** |

| Coin | Max DD | Final ($10K→) |
|------|:------:|:-------------:|
| ETH | 50.4% | $57,419 |
| BNB | 41.7% | $72,109 |
| TRX | 53.6% | $54,840 |
| **Avg** | **48.6%** | **$61,456** |

## Usage

```bash
python3 -m unittest tests.test_crypto_trading tests.test_utils -v  # 57/57
python3 scripts/backtest_bull_snowball.py --parallel   # ~27s
```
