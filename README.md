# Crypto Trading Alert System — v15

Double-snowball (bull + bounce) with per-coin config tuning. 41.3% avg CAGR.

## Results (2021-2025)

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | **+43.6%** | 39.5% | +72% | $69,651 |
| BNB | **+42.8%** | 41.4% | -0.5% | $67,673 |
| TRX | **+37.4%** | 33.9% | -9.8% | $54,872 |
| **Avg** | **+41.3%** | **38.3%** | — | **$64,065** |

## Key Features

- **Bull snowball**: 4-stage entries (0.10 + 3×0.06) at 3.5x with staggered TP (10/20/30%) + 11% trailing
- **Bounce snowball**: 3 same-sized entries (0.09 each) at per-coin lev (TRX 2.8x) with 80% TP 5→25% + 3% price trail
- **Bear Short Hedge**: ETH-only 3.5x short during BTC bear (12% SL, snowball trailing)
- **Safe mode**: 1.5x isolated entries on weak BTC trend (ADX < 22) — matches backtest
- Per-coin peak DD, MA buffers, trail activation configs

```bash
pip install -r requirements.txt
python3 scripts/backtest_bull_snowball.py --parallel
```

Full spec: [CryptoTrading.md](CryptoTrading.md)
