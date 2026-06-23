# Crypto Trading Strategy — Specification v13

## Overview

3-tier BTC ADX-based strategy for ETH, BNB, TRX perpetual futures on OKX.
- **Bull/Bear (strong trend):** ADX ≥ 22 — normal aggressive strategy
- **Safe mode (weak/choppy):** ADX < 22 — isolated safe entries only
- **Position limit:** 120% of capital per coin (MAX_POS_PCT)
- **Max open positions:** 5 concurrent

---

## Architecture

```
scripts/
├── trading_config.py          ← Single source of truth for ALL constants
├── backtest_bull_snowball.py  ← Backtest engine (precomputed indicators, ~27s)
├── crypto_trading.py          ← Live production (same logic)
├── utils/
│   ├── discord_webhook.py     ← Discord notifications
│   ├── okx_utils.py           ← OKX exchange API
│   └── firebase_utils.py      ← State persistence
tests/
├── test_crypto_trading.py     ← 57 unit tests
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
| `max_loss` (ROI loss limit) | 0.05 | 0.20 | 0.12 |

### Per-Coin Signals (`COIN_CONFIG`)

| Field | ETH | BNB | TRX |
|-------|:---:|:---:|:---:|
| `adx_min` | 12 | 15 | 20 |
| `snowball_min_score` | 60 | 65 | 65 |
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

### Safe Mode (BTC ADX < 22)
```
lev = 1.5, sl = 3.3%, entry = 3.5%, trail = none
TP = [(3, 0.07), (7, 0.13), (20, 0.30), (25, 0.25), (30, 0.25)]  (sum=100%)
peak_drawdown = 5% (close all if ROI drops 5% from peak)
ma_buffer = 2%
```

---

## Entry Logic (Backtest → Production)

### Entry Priority (evaluated in order)
1. **Safe mode** (`btc_safe`): 1.5x, 3.5% entry, SL 3.3%, SAFE TP
2. **Bear short** (`bear_short`): 3.5x, BULL_INITIAL_SIZE, same as BULL for shorts
3. **BNB bear** (`bnb_bear`): SAFE isolated params
4. **ETH bear** (`eth_bear`): 2x, 7% SL, entry 0.07
5. **Bull** (`_coin_bull`): 3.5x, snowball, staggered TP, trail
6. **Bear (default)**: PROFILE_BEAR or PROFILE_BULL

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
Entry score must be ≥ `entry_score` in COIN_CONFIG.

---

## Exit Logic (Backtest)

### BULL exit (ent_is_bull = True, no_sl)
```
1. max_loss check: if ROI <= -max_loss*100 → close all
2. Staggered TP: if ROI >= 10/20/30% → close 10% each
3. Trail: if pnl_from_entry >= 0.40 AND not in cooldown:
   - tstop = max(high * 0.89, current * 0.89)
   - if low <= tstop: close 50% of remaining
4. Regime exit: if coin regime flips to bear → close all
```

### BEAR exit (ent_is_bull = False, no_sl = False)
```
1. SL check: if ROI <= -sl_roi → close all
2. TP schedule [(8,10%),(15,15%),(25,20%),(40,25%)]
3. Trail: after all TPs done
```

### ETH bear exit
```
1. SL: 7% ROI
2. TP: 50% at 40% ROI
3. Trail: 7% from highest price
```

### Safe / BNB bear exit
```
1. SL: 3.3% ROI
2. Staggered TP: 3/7/20/25/30% sum=100%
3. Peak DD: close all if ROI drops 5% from peak
```

### Trend Reversal Exit
- Here `trend_score` uses `evaluate_trend_3d(mf, mm, ms)`:
  - Short: close if ts >= 2 (bullish reversal)
  - Long: close if ts <= -2 (bearish reversal)

---

## BTC Regime Detection

Backtest:
```python
btc_bull = sma(btc_close, 50) > sma(btc_close, 120)
btc_safe = compute_adx(btc_data, 14) < BTC_ADX_SAFE  # 22
```

Production (main):
```python
_btc_ma50 = sma(_btc_closes, 50)[-1]
_btc_ma200 = sma(_btc_closes, 200)[-1]
_btc_bull = _btc_ma50 > _btc_ma200
```

Note: Production uses MA50 vs MA200 for BTC regime. Backtest uses MA50 vs MA120.
This is the main difference between backtest and production.

---

## Backtest Precomputation (Speed Optimization)

The backtest precomputes ALL indicators once before the main loop, making it O(n) instead of O(n²):

```python
# Precompute before loop (runs once)
pre12 = {p: sma(closes_12h, p) for p in [18,37,30,14,20,400,50,120,40]}
pre_rsi = [compute_rsi(closes_12h[:i+1], 28) for i in range(28, n)]
pre_adx = [compute_adx(da[:i+1], 28) for i in range(29, n)]
pre_sw  = [compute_sideway_score(da[:i+1], SF) for i in range(1, n)]

# In loop (O(1) lookup):
mf = pre24[TMA_F][idx//2] or ct_c[idx//2]
ef = pre12[18][idx] or closes_12h[idx]
rsi1 = pre_rsi[idx]
adx_val = pre_adx[idx]
```

This gives 2.5x speedup (68s → 27s for 3 coins).

---

## Performance (2021–2025)

| Year | ETH | BNB | TRX | Avg |
|------|----:|----:|----:|----:|
| 2021 | +140% | +187% | +157% | +161% |
| 2022 | +10% | -1% | -9% | +0% |
| 2023 | +26% | +5% | +22% | +18% |
| 2024 | +52% | +99% | +95% | +82% |
| 2025 | +10% | +28% | +4% | +14% |
| **CAGR** | **+38.2%** | **+43.6%** | **+39.7%** | **+40.5%** |

| Coin | Max DD | SL Rate | Final ($10K→) |
|------|:------:|:-------:|:-------------:|
| ETH | 50.4% | 2.5% | $57,419 |
| BNB | 41.7% | 2.5% | $72,109 |
| TRX | 41.6% | 0.7% | $57,781 |
| **Avg** | **44.6%** | **1.9%** | **$62,436** |

---

## Edge Cases & Limitations

1. **ADX threshold whipsaw (12% of bars):** When BTC ADX oscillates near 22, strategy flips between safe and aggressive mode frequently. Managed by min bar threshold.

2. **Safe mode dominance (42% of BTC bars):** Conservative mode half the time limits upside in strong trends. Acceptable tradeoff for crash protection.

3. **TRX 2022: -9.2%** — no shorts, no counter-trend longs. TRX sits in cash during BTC bear, missing bounces. But this beats holding (-28%) and counter-trend approaches (-35% to -57%).

4. **ETH max_loss 5%:** Very tight. With 3.5x, 1.4% price drop = stop. This prevents ETH from snowballing in volatile conditions but also caps profits.

5. **Production vs Backtest gap:** Production doesn't have ETH bear mode, safe mode, or BNB bear exit modes. Only the BULL staggered TP + trail is aligned. The backtest's extra modes simulate better protection but aren't live.

---

## Deployment

```bash
# Install
pip install -r requirements.txt

# Test (57/57)
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
