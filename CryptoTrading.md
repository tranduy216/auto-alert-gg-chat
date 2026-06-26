# Crypto Trading Pyramid Strategy

## Overview

Multi-coin pyramid strategy với shared capital pool. Long TRX/PAXG khi gần MA, short BTC khi bear. Tất cả logic entry tập trung ở `backtest_shared.entry_conditions()` — backtest + live trading dùng chung.

## Portfolio

| Coin | Direction | Leverage | MA | Buffer | Pyramid ROI |
|------|-----------|----------|----|--------|-------------|
| TRX | Long | 1.8x | 15 | 5% | 3% |
| PAXG | Long | 1.8x | 15 | 5% | 3% |
| BTC | Short | 1.6x | 5 | 5% | 3% |

## Entry Logic (`entry_conditions`)

Shared function ở `scripts/backtest_shared.py:147`:

```
near_ma  = abs(close - ma) / ma <= buffer
vol_cond = (vol[i] + vol[i-1]) / 2 > vol_ma20
can_enter_long  = not is_short
can_enter_short = is_short and not btc_bull
should_enter = can_enter AND near_ma AND vol_cond AND cooldown AND mult > 0
```

### Extension Block

- **Long:** block thêm entry nếu `(cc - lowest_ep) / lowest_ep * 100 > 25%`
- **Short:** block thêm entry nếu `(highest_ep - cc) / highest_ep * 100 > 25%`

### Winner Multiplier

```
avg ROI > 15 → 2.5x
avg ROI > 10 → 2.0x
avg ROI >  5 → 1.5x
avg ROI >  0 → 1.2x
avg ROI > -5 → 0.75x
else         → 0.5x
```

## Exit Logic

### Long: Trailing Stop

Trail 20% từ high (`cc <= e['hi'] * 0.80`). Không take profit ladder.

### Short: TP Ladder

| Stage | ROI | % Position |
|-------|-----|-----------|
| 1 | 4% | 20% |
| 2 | 8% | 20% |
| 3 | 12% | 20% |
| 4 | 16% | 20% |
| 5 | 20% | 20% |
| **Total** | | **100%** |

Short cũng exit forced khi BTC > MA200 (regime turn bull).

### Pyramid

Thêm entry mới khi ROI của entry trước đó >= `pyr_roi` (default 3%).
Entry size = `eq * ENTRY_PCT / lev * mult`. Cap: tổng margin ≤ 75% total asset value.

## Fee Model

`fee_factor = 1 - 2 * FEE_RATE * lev` (FEE_RATE = 0.0005 = 0.05% mỗi side).

## Backtest Results

### Per-coin (standalone $10k mỗi coin)

| Strategy | CAGR | Max DD | Config |
|----------|------|--------|--------|
| TRX-L | +36.2% | −29.1% | ma=15, buf=5%, pyr=3, lev=1.8 |
| PAXG-L | +37.1% | −25.9% | ma=15, buf=5%, pyr=3, lev=1.8 |
| BTC-S | +6.3% | −16.4% | ma=5, buf=5%, pyr=3, lev=1.6 |
| **Portfolio (equal-weight)** | **+33.9%** | **−16.4%** | |

### Pooled ($10k shared, FCFS signals)

| Year | Return |
|------|--------|
| 2021 | +0.4% |
| 2022 | **+17.6%** |
| 2023 | +11.5% |
| 2024 | **+237.2%** |
| 2025 | **+95.4%** |
| 2026 | +9.2% |
| **CAGR** | **+57.7%** |
| Max DD | −24.7% |
| Final | **$94,645** |

## File Map

| File | Role | Lines |
|------|------|-------|
| `scripts/backtest_shared.py` | Constants, helpers, `entry_conditions` | 187 |
| `scripts/combined_backtest.py` | Per-coin backtest (calls `entry_conditions`) | 225 |
| `scripts/pooled_backtest.py` | Pooled shared-capital backtest | 231 |
| `scripts/crypto_trading.py` | Live trading (calls `entry_conditions`) | 130 |
| `scripts/live_pyramid.py` | Live signal generator (calls `entry_conditions`) | 130 |
| `scripts/crypto_trading_legacy.py` | Preserved old system for legacy scripts | 2254 |
| `scripts/trading_config.py` | Coin profiles, SHORT_ALLOWED | 140 |
| `scripts/test/test_all.py` | Unit tests (72 tests, 0 failures) | 175 |

## Key Principle

**Backtest = Live.** `entry_conditions()` ở `backtest_shared.py` là single source of truth cho entry logic. Backtest (`combined_backtest.py`), live trading (`crypto_trading.py`), và signal generator (`live_pyramid.py`) đều gọi function này — không có gap nào giữa historical và live.
