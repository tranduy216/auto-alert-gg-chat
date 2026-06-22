# Crypto Trading Alert System — v11

Hệ thống cảnh báo giao dịch crypto tự động với chiến lược **4-Mode BTC Regime**.

## Overview

- **Coins:** ETH, BNB, TRX
- **Strategy:** 4-mode per BTC regime × direction
- **Performance:** CAGR +34.4%, Avg DD 47.1%, SL Rate 3.4%
- **Tests:** 41/41 passing

## Quick Start

```bash
pip install -r requirements.txt
python3 scripts/backtest_bull_snowball.py --parallel
python3 -m unittest tests.test_crypto_trading tests.test_utils -v
```

## Performance

| Coin | CAGR | Max DD | SL Rate | Final |
|------|------|--------|---------|-------|
| ETH | +25.6% | 43.7% | 7.4% | $33,969 |
| BNB | +47.4% | 53.9% | 2.7% | $80,158 |
| TRX | +30.3% | 43.8% | 0.0% | $41,281 |
| **Avg** | **+34.4%** | **47.1%** | **3.4%** | **$51,803** |

## Documentation

- **[CryptoTrading.md](CryptoTrading.md)** — Strategy details, config, performance
