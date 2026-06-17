"""Quick test of v6 strategy on ETH 2021-2026."""
import os, sys, json
from datetime import datetime
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, evaluate_exit_v6, _aggregate_daily_to_3d,
    SYMBOL_MAP, SHORT_ALLOWED,
    SHORT_TREND_FAST, SHORT_TREND_SLOW,
)
from backtest_crypto import MIN_3D_PERIODS

def fetch_all(symbol, start_ms):
    params = {"symbol": symbol, "interval": "1d", "limit": 1500}
    if start_ms:
        params["startTime"] = start_ms
    resp = req_lib.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return [
        {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in data
    ]

def run_backtest(daily_all):
    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0,
             "trailing_stop": None, "highest_since_entry": None}
    trades = []
    INITIAL_DAYS = MIN_3D_PERIODS * 3

    for day_idx in range(INITIAL_DAYS, len(daily_all)):
        daily_slice = daily_all[:day_idx + 1]
        candles_3d = _aggregate_daily_to_3d(daily_slice)
        if len(candles_3d) < MIN_3D_PERIODS:
            continue

        current_close = daily_slice[-1]["close"]

        # 3D indicators
        closes_3d = [c["close"] for c in candles_3d]
        ma7_3d = (sma(closes_3d, 7)[-1] or closes_3d[-1])
        ma10_3d = (sma(closes_3d, 10)[-1] or closes_3d[-1])
        ma20_3d = (sma(closes_3d, 20)[-1] or closes_3d[-1])
        _, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
        ts_val = trend_strength(trend_score)
        rsi_3d = compute_rsi(closes_3d, 14)

        # 1D indicators (use all available daily data)
        closes_1d = [c["close"] for c in daily_slice]
        highs_1d = [c["high"] for c in daily_slice]
        lows_1d = [c["low"] for c in daily_slice]
        volumes_1d = [c["volume"] for c in daily_slice]
        ma20_1d_all = sma(closes_1d, 20)
        ma50_1d_all = sma(closes_1d, 50)
        ma20_1d = ma20_1d_all[-1] if ma20_1d_all[-1] is not None else closes_1d[-1]
        ma50_1d = ma50_1d_all[-1] if ma50_1d_all[-1] is not None else closes_1d[-1]
        trend_ma_fast_1d = (sma(closes_1d, SHORT_TREND_FAST)[-1] or None)
        trend_ma_slow_1d = sma(closes_1d, SHORT_TREND_SLOW)[-1] or ma50_1d
        vol_ma20 = (sma(volumes_1d, 20)[-1] or volumes_1d[-1])
        volume_score = compute_volume_score(volumes_1d[-1], vol_ma20)
        rsi_1d = compute_rsi(closes_1d, 14)
        recent_10d_low = min(lows_1d[-10:]) if len(lows_1d) >= 10 else current_close * 0.95
        recent_10d_high = max(highs_1d[-10:]) if len(highs_1d) >= 10 else current_close * 1.05

        prev_pos_state = state["position_state"]
        entry_price = state["entry_price"]
        remaining_size = state["remaining_size"]
        trailing_stop = state.get("trailing_stop")
        highest_since_entry = state.get("highest_since_entry")

        if prev_pos_state == "FLAT":
            entry_long = compute_entry_v6_long(
                trend_score, rsi_1d, current_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
            )
            entry_short = compute_entry_v6_short(
                trend_score, rsi_1d, current_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
            )
            pos_state, action = resolve_action_v6(
                trend_score, entry_long, entry_short, prev_pos_state,
            )
            if action in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                entry_price = current_close
                remaining_size = 1.0
                trailing_stop = None
                highest_since_entry = None
                trades.append({"type": "OPEN", "price": current_close, "date": datetime.utcfromtimestamp(daily_slice[-1]["open_time"]/1000).strftime("%Y-%m-%d")})
            state.update({"position_state": pos_state or prev_pos_state,
                          "entry_price": entry_price, "remaining_size": remaining_size,
                          "trailing_stop": trailing_stop, "highest_since_entry": highest_since_entry})
        else:
            is_long = prev_pos_state.startswith("LONG")
            pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long and entry_price and entry_price > 0 else ((entry_price - current_close) / entry_price * 100) if entry_price and entry_price > 0 else 0.0

            exit_action, reduce_pct, exit_reason, new_trailing_stop, new_highest = evaluate_exit_v6(
                prev_pos_state, entry_price, current_close, remaining_size,
                ma7_3d, ma20_3d, trend_score, ts_val, rsi_3d,
                recent_10d_low, recent_10d_high,
                trailing_stop, highest_since_entry,
            )
            trailing_stop = new_trailing_stop
            highest_since_entry = new_highest

            if exit_action == "HOLD":
                pos_state = prev_pos_state
            else:
                if exit_action == "EXIT_ALL":
                    trades.append({"type": "CLOSE", "price": current_close, "pnl_pct": round(pnl_pct, 2), "reason": exit_reason,
                                   "date": datetime.utcfromtimestamp(daily_slice[-1]["open_time"]/1000).strftime("%Y-%m-%d")})
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
                if remaining_size < 0.01 and pos_state != "FLAT":
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size,
                          "trailing_stop": trailing_stop, "highest_since_entry": highest_since_entry})

    closes = [t for t in trades if t.get("type") == "CLOSE"]
    pnls = [t["pnl_pct"] for t in closes]
    if not pnls:
        print("  No trades")
        return None

    total_pnl = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(closes) * 100
    avg_win = mean(wins) if wins else 0
    avg_loss = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")
    max_dd = max((0,))  # simplified

    print(f"  Trades={len(closes):2d} | PnL={total_pnl:+7.2f}% | "
          f"WR={win_rate:4.0f}% | AvgW={avg_win:+5.2f}% | AvgL={avg_loss:+5.2f}% | PF={pf:.2f}")
    for t in closes:
        print(f"    {t.get('date','')}: {t['reason']:20s} PnL={t['pnl_pct']:+6.2f}%")
    return total_pnl

def main():
    print("Fetching ETH data 2021-2026...")
    start_ms = int(datetime(2020, 6, 1).timestamp() * 1000)  # buffer for lookback
    daily_all = fetch_all("ETHUSDT", start_ms)
    daily_all = [d for d in daily_all if d["open_time"] < int(datetime(2026, 6, 18).timestamp() * 1000)]
    print(f"  {len(daily_all)} candles")

    years = [(2021, 1609459200000, 1640995200000), (2022, 1640995200000, 1672531200000),
             (2023, 1672531200000, 1704067200000), (2024, 1704067200000, 1735689600000),
             (2025, 1735689600000, 1767225600000), (2026, 1767225600000, None)]

    print(f"\n{'='*70}")
    print(f"  ETH fixed-strategy yearly backtest")
    print(f"{'='*70}")
    total_all = 0
    for yr, s, e in years:
        lookback = 90 * 86400_000  # 90 days for 3D lookback
        yr_data = [d for d in daily_all if d["open_time"] >= s - lookback and (e is None or d["open_time"] < e)]
        print(f"\n  {yr} ({len(yr_data)} candles):")
        r = run_backtest(yr_data)
        if r is not None:
            total_all += r
    print(f"\n  TOTAL PnL: {total_all:+.2f}%")

if __name__ == "__main__":
    main()
