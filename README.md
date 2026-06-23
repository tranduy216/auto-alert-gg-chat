# Crypto Trading Alert System — Baseline v13

BTC ADX-safe 3-tier strategy. 57/57 tests. 40.9% avg CAGR.

| Coin | CAGR | Max DD | 2022 | Final |
|------|------|--------|------|-------|
| ETH | **+38.0%** | 47.5% | +4% | $55,590 |
| BNB | **+43.6%** | 41.4% | -0.5% | $75,898 |
| TRX | **+41.1%** | 40.0% | -10% | $65,606 |
| **Avg** | **+40.9%** | **43.0%** | **-2%** | **$65,698** |

```bash
pip install -r requirements.txt
python3 -m unittest tests.test_crypto_trading tests.test_utils -v
python3 scripts/backtest_bull_snowball.py --parallel
```

Full spec: [CryptoTrading.md](CryptoTrading.md)
