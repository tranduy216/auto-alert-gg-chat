# Crypto Trading Alert System — v12

Hệ thống cảnh báo giao dịch crypto tự động — 4-mode BTC regime.

## Performance

| Coin | CAGR | Max DD | SL Rate | Final |
|------|------|--------|---------|-------|
| ETH | +37.3% | 38.4% | 0.0% | $54,688 |
| BNB | +32.0% | 61.5% | 5.1% | $44,341 |
| TRX | +44.6% | 51.2% | 0.0% | $72,405 |
| **Avg** | **+38.0%** | **50.4%** | **1.7%** | **$57,145** |

## Quick Start

```bash
pip install -r requirements.txt
python3 scripts/backtest_bull_snowball.py --parallel
python3 -m unittest tests.test_crypto_trading tests.test_utils -v  # 41/41
```
