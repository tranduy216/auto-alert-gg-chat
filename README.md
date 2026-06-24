# Crypto Trading Alert System — Baseline v15

BTC ADX-safe 3-tier strategy + Bear Short Hedge. 39.1% avg CAGR.

## Results (2021-2025)

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | **+38.9%** | 45.1% | +54% | $58,235 |
| BNB | **+42.8%** | 41.4% | -0.5% | $67,541 |
| TRX | **+35.7%** | 36.7% | -12% | $51,391 |
| **Avg** | **+39.1%** | **41.1%** | **+14%** | **$59,056** |

## Key Features

- **Bear Short Hedge**: Protective ETH short during BTC bear (2x, 6% SL) — eliminated 2022 losses
- Snowball compounding entries with staggered TP (10/20/30%) + 11% trailing stop
- 3-mode system: Bull/Bear (ADX >= 22), Safe (ADX < 22), Bounce (BTC bear long)
- Per-coin config tuning (TP schedules, peak DD thresholds, MA buffers)

```bash
pip install -r requirements.txt
python3 scripts/backtest_bull_snowball.py --parallel
```

Full spec: [CryptoTrading.md](CryptoTrading.md)
