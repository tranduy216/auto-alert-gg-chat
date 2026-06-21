# Crypto Trading Alert System

Hệ thống cảnh báo giao dịch crypto tự động với chiến lược **Per-Coin Regime Detection**.

## 🎯 Overview

- **Coins:** ETH, BNB, TRX
- **Strategy:** Regime-dependent (Bull/Bear per coin)
- **Performance:** CAGR 31.43%, Max DD 30.62%, SL Rate 14.80%
- **Status:** Production Ready (with 1 critical issue to fix)

## 📁 Project Structure

```
auto-alert-gg-chat/
├── scripts/
│   ├── crypto_trading.py          # Main trading logic
│   ├── backtest_optimal.py        # Backtest framework
│   ├── backtest_fast.py           # Fast backtest (cache, parallel)
│   └── test_*.py                  # Test scripts
├── tests/
│   └── test_crypto_trading.py     # Unit tests (25/25 passing)
├── CryptoTrading.md               # Strategy documentation
├── requirements.txt               # Python dependencies
└── wrangler.toml                  # Cloudflare Workers config
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Backtest

```bash
# Full backtest (all coins, all combos)
python3 scripts/backtest_optimal.py

# Fast backtest (single coin, cached)
python3 scripts/backtest_fast.py --coin ETH
python3 scripts/backtest_fast.py --parallel
```

### 3. Run Unit Tests

```bash
python3 -m unittest tests.test_crypto_trading -v
# Expected: 25/25 tests passing
```

### 4. Deploy to Production

```bash
# Test locally
python3 scripts/crypto_trading.py --test-mode

# Deploy to Cloudflare Workers
npx wrangler deploy
```

## 📊 Performance

| Coin | CAGR | Max DD | SL Rate | Final Equity |
|------|------|--------|---------|--------------|
| ETH | +23.14% | 37.18% | 16.19% | $30,549 |
| BNB | +37.50% | 20.60% | 15.25% | $55,187 |
| TRX | +33.65% | 34.07% | 12.96% | $47,389 |
| **Average** | **+31.43%** | **30.62%** | **14.80%** | **$44,375** |

## 🔗 Documentation

- **[CryptoTrading.md](CryptoTrading.md)** - Chi tiết strategy, configuration, deployment, testing

## ⚠️ Known Issues

🔴 **CRITICAL:** Regime-dependent cooldown shift chưa implement trong production code

Xem chi tiết trong [CryptoTrading.md](CryptoTrading.md#known-issues)

## 📝 License

Private - Internal use only

---

**Last Updated:** 2026-06-21
