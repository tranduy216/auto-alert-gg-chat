# Crypto Trading Alert System — Baseline v13

BTC ADX-safe 3-tier strategy. 57/57 tests. 41.0% avg CAGR.

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | **+38.2%** | 47.1% | +4% | $55,897 |
| BNB | **+43.8%** | 41.1% | -0.5% | $76,194 |
| TRX | **+41.1%** | 40.0% | -10% | $65,739 |
| **Avg** | **+41.0%** | **42.7%** | **-2%** | **$65,943** |

```bash
pip install -r requirements.txt
python3 -m unittest tests.test_crypto_trading tests.test_utils -v
python3 scripts/backtest_bull_snowball.py --parallel
```

Full spec: [CryptoTrading.md](CryptoTrading.md)
