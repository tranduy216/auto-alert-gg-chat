# Crypto Trading Pyramid Strategy

## Overview

Multi-coin pyramid strategy với shared capital pool. Long TRX/XAU khi gần MA, short BTC khi bear. Tất cả logic entry tập trung ở `backtest_shared.entry_conditions()` — backtest + live trading dùng chung.

## Portfolio

| Coin | Direction | Leverage | MA | Buffer | Exit | Filters |
|------|-----------|----------|----|--------|------|---------|
| TRX | Long | 2x | 15 | 5% | TP 5-stage (10/20/30/40/50% → 5/10/15/20/10%), trail 18% | vol_bars=3 |
| XAU | Long | 2x | 20 | 5% | MA cross (40/90) + buffer 3% | Lower High, pyramid entry_mult=1.5 |
| BTC | Short | 2.5x | 10 | 5% | TP 3-stage (4/8/12% → 30/40/30%), trail 20% | short_mult=3.0, pyramid entry_mult=0.7, pyr_step=8, pyr_cap=3 |

## Entry Logic (`entry_conditions`)

Shared function ở `scripts/backtest_shared.py:457`:

```
near_ma     = abs(close - ma) / ma <= buffer
vol_cond    = avg(last N volumes) > vma (N = vol_bars, default 2)
can_long    = not is_short
can_short   = is_short and not btc_bull
should_enter = can_X AND near_ma AND vol_cond AND mult > 0
```

### Additional Filters

- **MA Slope** (`ma_slope`): long chỉ entry khi MA đang tăng (`
ma[idx] > ma[idx-1]`)
- **Lower High** (`lower_high`): long chỉ entry khi không có lower high pattern (3 đỉnh giảm dần)
- **Asym Buffer** (`asym_buffer`): dùng buffer=2% khi close dưới MA, buffer gốc khi trên MA
- **Green Candle** (`green_min_count`/`green_window`): yêu cầu N green candles trong window bars gần nhất

### Extension Block

- **Long:** block thêm entry nếu `(cc - lowest_ep) / lowest_ep * 100 > EXT_BLOCK_PCT` (default 25%)
- **Short:** block thêm entry nếu `(highest_ep - cc) / highest_ep * 100 > EXT_BLOCK_PCT`

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

### Long: TP Ladder + Trailing

TRX dùng TP 5-stage + trailing:

| Stage | ROI | % Position |
|-------|-----|-----------|
| 1 | 10% | 5% |
| 2 | 20% | 10% |
| 3 | 30% | 15% |
| 4 | 40% | 20% |
| 5 | 50% | 10% |
| **Total** | | **60%** |

Sau TP, trailing 18% từ peak (`close <= peak * 0.82`).

XAU dùng MA cross exit: đóng khi MA40 cross xuống dưới MA90 + buffer 3%.

### Short: TP Ladder + Trailing

| Stage | ROI | % Position |
|-------|-----|-----------|
| 1 | 4% | 30% |
| 2 | 8% | 40% |
| 3 | 12% | 30% |
| **Total** | | **100%** |

Trailing 20% từ trough (`close >= trough * 1.08`). Short cũng exit forced khi BTC > MA200 (regime turn bull).

### Pyramid

Thêm entry mới khi ROI >= pyr_step (config per coin, default 8%). Entry size = `eq * ENTRY_PCT / lev * mult * pyramid.entry_mult`. Cap pyramid theo `pyramid.pyr_cap`.

## Fee Model

`fee_factor = 1 - 2 * FEE_RATE * lev` (FEE_RATE = 0.0005 = 0.05% mỗi side).

## File Map

| File | Role | Lines |
|------|------|-------|
| `scripts/backtest_shared.py` | Constants, helpers, `entry_conditions`, `fetch_candles` (OKX→CMC→CoinGecko) | 545 |
| `scripts/combined_backtest.py` | Per-coin backtest (calls `entry_conditions`) | 323 |
| `scripts/pooled_backtest.py` | Pooled shared-capital backtest | 392 |
| `scripts/crypto_trading.py` | Live trading (calls `entry_conditions`) | 472 |
| `scripts/live_pyramid.py` | Live signal generator (calls `entry_conditions`) | 124 |
| `scripts/crypto_trading_legacy.py` | Preserved old system for legacy scripts | 2254 |
| `scripts/trading_config.py` | Coin profiles, SHORT_ALLOWED | 155 |
| `scripts/test/test_all.py` | Unit tests (139+ tests, 0 failures) | 670 |

## Key Principle

**Backtest = Live.** `entry_conditions()` ở `backtest_shared.py` là single source of truth cho entry logic. Backtest (`combined_backtest.py`), live trading (`crypto_trading.py`), và signal generator (`live_pyramid.py`) đều gọi function này — không có gap nào giữa historical và live.
