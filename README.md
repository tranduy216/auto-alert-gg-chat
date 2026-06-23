# Crypto Trading Alert System — v13

BTC ADX-based 3-tier strategy. 57/57 tests. 39.1% avg CAGR.

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | +38.8% | 51.4% | +12.8% | $58K |
| BNB | +41.7% | 46.6% | -0.6% | $65K |
| TRX | +36.9% | 55.1% | -12.9% | $54K |
| **Avg** | **+39.1%** | **51.0%** | **-0.2%** | **$59K** |

```bash
pip install -r requirements.txt
python3 -m unittest tests.test_crypto_trading tests.test_utils -v
python3 scripts/backtest_bull_snowball.py --parallel
```
