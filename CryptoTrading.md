# Crypto Trading Strategy — Specification v15 (Bear Short Hedge)

## Overview

3-tier BTC ADX-based strategy for ETH, BNB, TRX perpetual futures on OKX.
- **Bull/Bear (strong trend):** ADX >= 22 — snowball entries (initial + 3 adds) at 3.5x with staggered TP (10/20/30%) + 11% trailing
- **Safe mode (weak/choppy, backtest only):** ADX < 22 — 1.5x isolated entries with tight SL/TP/peak DD
- **Bounce mode (BTC bear):** Defensive long in BTC bear with per-coin lev, TP 5→25%, peak DD, 3% price trail
- **Bear Short Hedge:** Protective short on ETH during BTC bear (ts <= -2) with 3.5x lev, 12% SL, snowball trailing
- **Position limit:** 120% of capital per coin (MAX_POS_PCT)
- **Max open positions:** 5 concurrent

---

## Architecture

```
scripts/
├── trading_config.py          ← Single source of truth for ALL constants (incl. per-coin overrides)
├── trading_rules.py           ← Unified entry/exit logic (detect_bounce, get_entry_rule, process_*_exit)
├── backtest_bull_snowball.py  ← Backtest engine (precomputed indicators, ~27s)
├── crypto_trading.py          ← Live production (same logic + OKX integration)
├── utils/
│   ├── discord_webhook.py     ← Discord notifications
│   ├── okx_utils.py           ← OKX exchange API
│   └── firebase_utils.py      ← State persistence
tests/
├── test_crypto_trading.py     ← 60 unit tests
└── test_utils.py              ← Utility tests
```

**Key rule:** `trading_config.py` is the single source of truth. Both backtest and production import from it. NEVER hardcode values in either file.

---

## Configuration

### Per-Coin Profiles (`PROFILES_BULL`)

| Field | ETH | BNB | TRX |
|-------|:---:|:---:|:---:|
| `lev` (leverage) | 3.5 | 3.5 | 3.5 |
| `sl` (stop loss ROI%) | 10 (unused, no_sl=True) | 20 | 12 |
| `pos_mult` (position multiplier) | 1.3 | 1.3 | 1.3 |
| `initial_exposure` | 0.08 | 0.25 | 0.25 |
| `trail` | 0.11 | 0.11 | 0.11 |
| `trail_activation` (price fraction) | 0.30 | 0.30 | 0.30 |
| `no_sl` | True (uses max_loss) | False | False |
| `max_loss` (ROI loss limit) | 0.10 | 0.20 | 0.12 |

### Per-Coin Signals (`COIN_CONFIG`)

| Field | ETH | BNB | TRX |
|-------|:---:|:---:|:---:|
| `adx_min` | 12 | 15 | 20 |
| `snowball_min_score` | 65 | 65 | 65 |
| `entry_score` | 65 | 65 | 65 |
| `ma_buffer` | 0% | 1% | 1% |
| `bear_short` | True | False | False |

### Entry Cooldown (`ENTRY_COOLDOWN_BARS`)
- ETH: 3 bars (36h)
- BNB: 1 bar (12h)
- TRX: 1 bar (12h)

### Snowball Parameters
- Levels: `[0.05, 0.10, 0.15]` (3 levels: +5%, +10%, +15% price)
- Sizes: `[0.06, 0.06, 0.06, 0.06]` (initial + 3 adds = 0.24 total)
- Initial entry: `BULL_INITIAL_SIZE = 0.10`

### Staggered Take Profit (Before Trail)
`BULL_TP_SCHEDULE = [(10, 0.10), (20, 0.10), (30, 0.10)]`
- Close 10% at +10% ROI, 10% at +20% ROI, 10% at +30% ROI (30% total)
- Remaining 70% enters trailing stop logic

### Trailing Stop
- Distance: 11% from highest price
- Activation: 40% ROI (pnl_from_entry >= 0.40)
- Close: 50% of remaining on each trail trigger
- Cooldown: 5 bars (60h) after each trail close

### BTC Bear Override (BNB only)
`BTC_BEAR_OVERRIDE = {"adx_min": 20, "ma_buffer": 0.025, "bull_lev": 3.0, "max_loss": 0.25}`
- Applied when BTC bear AND coin ≠ ETH
- Tightens BNB bull entries during BTC bear

### Safe Mode (BTC ADX < 22) — Default Config (backtest only)
```
lev = 1.5, sl = 3.3%, entry = 3.5%
TP = [(3, 10%), (5, 20%), (8, 25%), (12, 25%), (20, 20%)]  (80% at 3-12%, max 20%)
peak_drawdown = 2.8% (close all if ROI drops 2.8% from peak)
ma_buffer = 2% (MA50 > MA120 * 1.02)
```

> Note: Safe mode is implemented in the backtest only. Production `analyse_coin()` lacks BTC ADX detection and does not have safe mode. This is a known architectural gap.

### Bounce Mode (ETH/BNB/TRX — BTC bear)
```
lev = per-coin (default 2.0, TRX=2.8), sl = 6.5%, entry = 9.0%
TP = [(5, 10%), (10, 20%), (15, 25%), (20, 15%), (25, 10%)]  (80% at 5→25%)
peak_dd = per-coin (ETH=3.5, BNB=7.0, TRX=7.0)
trail = 3% price (6% ROI at 2x), activates after all TPs or at per-coin ROI (TRX=10%)
snowball: 3 same-sized entries (0.09 each) at +5%/+10% price levels
```

### BNB/TRX Bounce MA Buffer
`BNB_BOUNCE_MA_BUF = 0.018`, `TRX_BOUNCE_MA_BUF = 0.018` — MA50 > MA120 * 1.018 required for bounce entry

---

## ROI Formula

### Isolated mode (safe, bounce entries)
`roi = price_change% × leverage` — position-level ROI, used for SL/TP/peak DD checks.

### Non-isolated mode (bull, bear entries)
`roi = price_change% × position_pct × coin_cap × leverage / BASE` — equity-level ROI (legacy formula).

---

## Entry Logic (Backtest → Production)

### Entry Priority (evaluated in order)
1. **Safe mode** (`btc_safe`): per-coin config (lev/SL/entry/TP/peak DD), score >= per-coin threshold
2. **Bear short** (`bear_short`): 3.5x, BULL_INITIAL_SIZE, snowball + trail like longs (ETH only, BTC strong bear)
3. **Bear Short Hedge**: 2x, 6% SL, 30% position (ETH only, BTC bear, ts <= -2) — protective hedge against drawdowns
4. **TRX safe short**: 2x, SL 7.5%, entry 4%, TRX only in BTC bear
5. **Bounce** (`bounce`): 2x, SL 5.5%, per-coin TP schedule, peak DD, no trailing
6. **Bull** (`is_bull`): 3.5x, snowball, staggered TP, trail
7. **Bear (default)**: PROFILE_BEAR or PROFILE_BULL

### Entry Signal: `_entry_score_v7_long/short()`
```
Components (0-100 scale):
- Trend strength: 40 pts (trend_score mapping)
- MA alignment: 12 pts
- MA200 direction: 12 pts
- Pullback proximity: 16 pts
- Volume composite: 12 pts  
- RSI neutral zone: 8 pts
```
Entry score must be ≥ `entry_score` in COIN_CONFIG. Safe mode requires ≥ `SAFE_ENTRY_SCORE` (75 default, 78 for TRX).

---

## Exit Logic (Backtest)

### BULL exit (ent_is_bull = True, no_sl)
```
1. max_loss check: if ROI <= -max_loss*100 → close all
2. Staggered TP: if ROI >= 10/20/30% → close 10% each
3. Trail: if pnl_from_entry >= 0.40 AND not in cooldown:
   - tstop = max(high * 0.89, current * 0.89)
   - if low <= tstop: close 60% of remaining
4. Regime exit: if coin regime flips to bear → close all
```

### BEAR exit (ent_is_bull = False, no_sl = False)
```
1. SL check: if ROI <= -sl_roi → close all
2. TP schedule [(8,10%),(15,15%),(25,20%),(40,25%)]
3. Trail: after all TPs done
```

### Safe mode exit (isolated, backtest only)
```
1. SL: 3.3% — position ROI formula
2. Staggered TP: 80% at 3-12%, max 20% (SAFE_TP)
3. Peak DD: close all if ROI drops 2.8% from peak (SAFE_PEAK_DD)
```

### Bounce exit (defensive long in BTC bear)
```
1. SL: 6.5% — position ROI formula
2. Staggered TP: 80% at 5→25% (shared BOUNCE_TP for all coins)
3. Peak DD: per-coin threshold (COIN_PEAK_DD: ETH=3.5, BNB=7.0, TRX=7.0)
4. Trailing stop: 3% price, activates after all TPs or at per-coin ROI (TRX=10%)
5. Snowball: up to 3 same-sized (0.09) entries at +5%/+10% price levels
```

### Trend Reversal Exit
- Short: close if ts >= 2 (bullish reversal)
- Long: close if ts <= -2 (bearish reversal)

---

## BTC Regime Detection

Backtest:
```python
btc_bull = sma(btc_close, 50) > sma(btc_close, 120)
btc_safe = compute_adx(btc_data, 14) < BTC_ADX_SAFE  # 22
```

Production:
```python
_btc_ma50 = sma(_btc_closes, 50)[-1]
_btc_ma200 = sma(_btc_closes, 200)[-1]
_btc_bull = _btc_ma50 > _btc_ma200
```

Note: Production uses `MA50 vs MA200` for BTC bull/bear detection.
Backtest uses `MA50 vs MA120` on daily. This is the main remaining difference.
Everything else (bounce regime, safe mode, entry priority) now matches.

---

## Performance (2021–2025, v15 baseline)

### Yearly ROI

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +159% | +193% | +212% | +188% |
| 2022 | +54% | -0.5% | -12% | +14% |
| 2023 | +9% | +5% | +24% | +13% |
| 2024 | +15% | +88% | +37% | +47% |
| 2025 | -2% | +28% | +12% | +13% |

### Final Equity ($10K ->)

| Coin | CAGR | Final | Max DD | SL Rate |
|------|-----:|:----:|:------:|:------:|
| ETH  | +38.9% | $58,235 | 45.1% | 2.0% |
| BNB  | +42.8% | $67,541 | 41.4% | 2.6% |
| TRX  | +35.7% | $51,391 | 36.7% | 5.1% |
| **Avg** | **+39.1%** | **$59,056** | **41.1%** | **3.3%** |

### Per-Mode Stats

| Mode | ETH | BNB | TRX |
|------|:---:|:---:|:---:|
| Safe entries | 33 | 23 | 44 |
| Safe SL rate | 39.4% | 65.2% | 36.4% |
| Safe TP rate | 142.4% | 56.5% | 202.3% |
| Bounce entries | 20 | — | 17 |
| Bounce SL rate | 75.0% | — | 29.4% |
| Bull entries | 22 | 32 | 26 |
| Bear entries | 17 | 19 | 5 |

---

## Deployment

```bash
# Install
pip install -r requirements.txt

# Test (61/61)
python3 -m unittest tests.test_crypto_trading tests.test_utils -v

# Backtest (3 coins, full 5 years, ~27s)
python3 scripts/backtest_bull_snowball.py --parallel

# Single coin, specific years
python3 scripts/backtest_bull_snowball.py --coin ETH --years 2022,2023,2024,2025

# Production (OKX + Discord)
python3 scripts/crypto_trading.py
```

**Environment variables required for production:**
- `DISCORD_TRADING_WEBHOOK_URL` — Discord webhook
- `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` — OKX API
- `FIREBASE_SERVICE_ACCOUNT` — JSON key for Firestore (optional)

**GitHub Actions workflows:**
- `crypto-trading.yml` — Manual/repository_dispatch trigger
- `daily-rss-digest.yml` — RSS news digest (06:00 VNT)
- `breaking-news.yml` — Breaking news monitor (12:00 VNT)
- `okx-test.yml` — OKX API connectivity test
