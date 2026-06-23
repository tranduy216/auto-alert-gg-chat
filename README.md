# Crypto Trading Alert System — v13

BTC ADX-safe 3-tier strategy. 57/57 tests. 40.5% avg CAGR.

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | +38.2% | 50.4% | +10.3% | $57K |
| BNB | +43.6% | 41.7% | -0.5% | $72K |
| TRX | +39.7% | 41.6% | -9.2% | $58K |
| **Avg** | **+40.5%** | **44.6%** | **+0.2%** | **$62K** |

```bash
pip install -r requirements.txt
python3 -m unittest tests.test_crypto_trading tests.test_utils -v
python3 scripts/backtest_bull_snowball.py --parallel
```

Full spec: [CryptoTrading.md](CryptoTrading.md)
