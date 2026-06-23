# Crypto Trading Alert System — v13

BTC ADX-based 3-tier strategy: aggressive bull/bear + safe mode.

## Performance

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | +34.7% | 51.5% | +19.9% | $107K |
| BNB | +41.7% | 46.6% | -0.6% | $120K |
| TRX | +36.7% | 52.8% | -8.2% | $99K |
| **Avg** | **+37.7%** | **50.3%** | **+3.7%** | **$109K** |

## Quick Start

```bash
pip install -r requirements.txt
python3 scripts/backtest_bull_snowball.py --parallel
python3 -m unittest tests.test_crypto_trading tests.test_utils -v  # 46/46
```
