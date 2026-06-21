# Crypto Trading — HYBRID Strategy

**Baseline:** 2026-06-22

## Strategy Overview

HYBRID strategy — tự động chọn chiến lược theo per-coin regime (MA50 vs MA120 trên 12h):

| Regime | Strategy |
|--------|----------|
| **BULL** (MA50 > MA120 + buffer) | Snowball entries + trailing stop, no SL, max loss 10% |
| **BEAR** (MA50 < MA120) | Trading: SL + TP + trailing stop |

BTC regime override: khi BTC đang BEAR → bull entries bị strict hơn (ADX+3, buffer+3%, lev→2x).

---

## Per-Coin Config

| Coin | ADX | MA buf | Snow score | Short | BTC override |
|------|:---:|:------:|:----------:|:-----:|:------------:|
| ETH | 12 | — | 65 | Yes | No |
| BNB | 15 | 1% | 65 | No | Yes |
| TRX | 22 | 3% | 72 | No | Yes |

### Global Constants

| Param | Value |
|-------|-------|
| BULL initial entry | 0.06 |
| BULL snowball levels | +5%, +10%, +15%, +20%, +25%, +30%, +40% |
| BULL snowball size | 0.05 each |
| BULL trail distance | 9% |
| BULL trail activation | 40% ROI |
| BULL trail close | 30% |
| BULL trail cooldown | 5 bars |
| BULL max loss | 10% |
| BULL leverage | 3.5x |
| BEAR TP | (8%,10%), (15%,15%), (25%,20%), (40%,25%) |
| BEAR trail | 4% (ETH), 6.5% (BNB/TRX) |

---

## Performance (2022–2025)

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2022 | +57% | -17% | 0% | +13% |
| 2023 | -4% | -1% | +7% | +1% |
| 2024 | +5% | +147% | +111% | +88% |
| 2025 | +48% | +33% | +4% | +28% |
| **CAGR** | **23.7%** | **28.4%** | **23.6%** | **25.2%** |

| Coin | Max DD | SL Rate |
|------|:------:|:-------:|
| ETH | 59.6% | 14.3% |
| BNB | 38.1% | 1.2% |
| TRX | 33.1% | 0.0% |

---

## Project Structure

```
scripts/
├── trading_config.py           ← Single source of truth (all constants)
├── crypto_trading.py           ← Production implementation
└── backtest_bull_snowball.py   ← Backtest (matches production)

tests/
├── test_crypto_trading.py      ← Unit tests (33 tests)
├── test_utils.py               ← Utility tests (8 tests)
└── utils/
    ├── verify_crypto_trading_logic.py  ← Logic verification (90 checks)
    └── compare_bh_yearly.py            ← Buy & Hold comparison
```

## Usage

```bash
# Unit tests
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Logic verification
python3 tests/utils/verify_crypto_trading_logic.py

# Backtest — all years
python3 scripts/backtest_bull_snowball.py --parallel

# Backtest — specific coin, specific years
python3 scripts/backtest_bull_snowball.py --coin ETH --years 2022,2023,2024,2025

# Tune config → edit trading_config.py → cache tự invalidate
```
