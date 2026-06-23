# Crypto Trading Alert System — v13

BTC ADX-based 3-tier strategy. 46/46 tests. 39.2% avg CAGR.

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | +38.9% | 50.8% | +12.8% | $58K |
| BNB | +41.7% | 46.6% | -0.6% | $65K |
| TRX | +36.9% | 55.1% | -12.9% | $54K |
| **Avg** | **+39.2%** | **50.8%** | **-0.2%** | **$59K** |

```bash
pip install -r requirements.txt
python3 scripts/backtest_bull_snowball.py --parallel
python3 -m unittest tests.test_crypto_trading tests.test_utils -v
```
