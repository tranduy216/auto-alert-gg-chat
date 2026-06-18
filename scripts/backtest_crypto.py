#!/usr/bin/env python3
"""Backtest crypto_trading v6 strategy with bull/bear period support."""

import json
import os
import sys
from datetime import datetime
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests as req_lib

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, evaluate_exit_v6, _aggregate_daily_to_3d,
    COINS, SYMBOL_MAP, SHORT_ALLOWED,
    SHORT_TREND_FAST, SHORT_TREND_SLOW,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
    get_coin_profile,
)

LOOKBACK_DAYS = 400
MIN_3D_PERIODS = 25

BINANCE_MAX_LIMIT = 1000

PERIODS = {
    "BEAR": {
        "label": "Recent 400 days (bear/mixed)",
        "start_time": None,
        "limit": 400,
    },
    "BULL_2023": {
        "label": "Bull 2023 (Jan 2023 – Feb 2024)",
        "start_time": int(datetime(2023, 1, 1).timestamp() * 1000),
        "limit": 400,
    },
    "2021_2023": {
        "label": "2021–2023",
        "start_time": int(datetime(2021, 1, 1).timestamp() * 1000),
        "limit": BINANCE_MAX_LIMIT,
    },
    "2024_2026": {
        "label": "2024–2026",
        "start_time": int(datetime(2024, 1, 1).timestamp() * 1000),
        "limit": BINANCE_MAX_LIMIT,
    },
}


def _fetch_klines_backtest(symbol: str, interval: str = "1d", limit: int = 400,
                           start_time: int | None = None) -> list[dict]:
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, BINANCE_MAX_LIMIT)}
    if start_time:
        params["startTime"] = start_time
    resp = req_lib.get(
        "https://api.binance.com/api/v3/klines",
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in data
    ]


def _fetch_all_klines(symbol: str, limit: int = 1000,
                      start_time: int | None = None) -> list[dict]:
    candles = []
    remaining = limit
    cur_start = start_time
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        batch = _fetch_klines_backtest(symbol, "1d", take + 50, cur_start)
        if len(batch) <= 1:
            break
        candles.extend(batch)
        remaining -= len(batch)
        cur_start = batch[-1]["open_time"] + 1
        if len(candles) >= limit:
            break
    return candles[:limit]


def backtest_coin(coin: str, start_time: int | None = None,
                  limit: int = LOOKBACK_DAYS) -> dict:
    profile = get_coin_profile(coin)
    symbol = SYMBOL_MAP[coin]
    daily_all = _fetch_all_klines(symbol, limit, start_time)
    if start_time:
        daily_all = daily_all[:limit]
    else:
        daily_all = daily_all[-limit:]

    first_date = datetime.utcfromtimestamp(daily_all[0]["open_time"] / 1000).strftime("%Y-%m-%d")
    last_date = datetime.utcfromtimestamp(daily_all[-1]["open_time"] / 1000).strftime("%Y-%m-%d")

    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0,
             "trailing_stop": None, "highest_since_entry": None,
             "short_loss_streak": 0, "short_cooldown_until": None,
             "long_loss_streak": 0, "long_cooldown_until": None}
    trades = []
    equity_curve = [1.0]

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
        trend_label, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
        ts_val = trend_strength(trend_score)
        rsi_3d = compute_rsi(closes_3d, 14)

        # 1D indicators (all available data)
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

        dt = daily_slice[-1]["open_time"]
        if isinstance(dt, int):
            date_str = datetime.utcfromtimestamp(dt / 1000).strftime("%Y-%m-%d")
        else:
            date_str = str(dt)

        prev_pos_state = state["position_state"]
        entry_price = state["entry_price"]
        remaining_size = state["remaining_size"]
        trailing_stop = state.get("trailing_stop")
        highest_since_entry = state.get("highest_since_entry")

        if prev_pos_state == "FLAT":
            # Long cooldown check
            _long_allowed = True
            if state.get("long_cooldown_until"):
                _cd = state["long_cooldown_until"]
                if isinstance(_cd, str) and dt and isinstance(dt, int):
                    _cd_ms = int(datetime.fromisoformat(_cd).timestamp() * 1000)
                    if dt < _cd_ms:
                        _long_allowed = False
                elif isinstance(_cd, (int, float)) and isinstance(dt, int):
                    if dt < _cd:
                        _long_allowed = False
            entry_long = compute_entry_v6_long(
                trend_score, rsi_1d, current_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
                trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
            ) if _long_allowed else False
            # Short cooldown check
            _short_allowed = coin in SHORT_ALLOWED
            if _short_allowed and state.get("short_cooldown_until"):
                _cd = state["short_cooldown_until"]
                if isinstance(_cd, str) and dt and isinstance(dt, int):
                    _cd_ms = int(datetime.fromisoformat(_cd).timestamp() * 1000)
                    if dt < _cd_ms:
                        _short_allowed = False
                elif isinstance(_cd, (int, float)) and isinstance(dt, int):
                    if dt < _cd:
                        _short_allowed = False
            entry_short = (
                compute_entry_v6_short(
                    trend_score, rsi_1d, current_close, ma20_1d, trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
                    trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
                ) if _short_allowed else False
            )
            pos_state, action = resolve_action_v6(
                trend_score, entry_long, entry_short, prev_pos_state,
            )
            if action == "OPEN_LONG_ENTRY_1":
                entry_price = current_close
                remaining_size = 1.0
                trailing_stop = None
                highest_since_entry = None
                trades.append({"date": date_str, "type": "LONG_OPEN", "price": current_close, "size": 1.0, "reason": f"TrendScore={trend_score}"})
            elif action == "OPEN_SHORT_ENTRY_1":
                entry_price = current_close
                remaining_size = 1.0
                trailing_stop = None
                highest_since_entry = None
                trades.append({"date": date_str, "type": "SHORT_OPEN", "price": current_close, "size": 1.0, "reason": f"TrendScore={trend_score}"})
            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size,
                          "trailing_stop": trailing_stop, "highest_since_entry": highest_since_entry})
        else:
            is_long = prev_pos_state.startswith("LONG")
            if entry_price and entry_price > 0:
                pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long else ((entry_price - current_close) / entry_price * 100)
            else:
                pnl_pct = 0.0

            exit_action, reduce_pct, exit_reason, new_ts, new_he = evaluate_exit_v6(
                prev_pos_state, entry_price, current_close, remaining_size,
                ma7_3d, ma20_3d, trend_score, ts_val, rsi_3d,
                recent_10d_low, recent_10d_high,
                trailing_stop, highest_since_entry,
                max_loss_pct=profile["max_loss_pct"],
                trailing_pct=profile["trailing_pct"],
                initial_stop_pct=profile["initial_stop_pct"],
                hard_stop_pct=profile["hard_stop_pct"],
            )
            trailing_stop = new_ts
            highest_since_entry = new_he

            if exit_action == "HOLD":
                pos_state = prev_pos_state
                action = "HOLD"
            else:
                if exit_action == "EXIT_ALL":
                    pnl = pnl_pct
                    trades.append({"date": date_str, "type": "CLOSE", "price": current_close, "size": remaining_size, "pnl_pct": round(pnl, 2), "reason": exit_reason})
                    # Direction-specific cooldown tracking
                    if "SHORT" in prev_pos_state:
                        _sls = state.get("short_loss_streak", 0)
                        if pnl > 0:
                            state["short_loss_streak"] = 0
                            state["short_cooldown_until"] = None
                        else:
                            _sls += 1
                            state["short_loss_streak"] = _sls
                            if _sls >= SHORT_COOLDOWN_LOSSES:
                                from datetime import timedelta
                                _cd = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)
                                state["short_cooldown_until"] = _cd.isoformat()
                    else:  # LONG
                        _lls = state.get("long_loss_streak", 0)
                        if pnl > 0:
                            state["long_loss_streak"] = 0
                            state["long_cooldown_until"] = None
                        else:
                            _lls += 1
                            state["long_loss_streak"] = _lls
                            if _lls >= LONG_COOLDOWN_LOSSES:
                                from datetime import timedelta
                                _cd = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=LONG_COOLDOWN_DAYS)
                                state["long_cooldown_until"] = _cd.isoformat()
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None

                if remaining_size < 0.01 and pos_state != "FLAT":
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None

            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size,
                          "trailing_stop": trailing_stop, "highest_since_entry": highest_since_entry})

        if state["position_state"] != "FLAT" and state["entry_price"] and state["remaining_size"] > 0:
            is_long = state["position_state"].startswith("LONG")
            upnl = ((current_close - state["entry_price"]) / state["entry_price"] * 100) if is_long else ((state["entry_price"] - current_close) / state["entry_price"] * 100)
            equity_curve.append(1.0 + upnl / 100 * state["remaining_size"] * profile["leverage"])
        else:
            equity_curve.append(1.0)

    return {"coin": coin, "trades": trades, "equity_curve": equity_curve,
            "period": f"{first_date} → {last_date}"}


def compute_metrics(result: dict) -> dict:
    trades = result["trades"]
    closes = [t for t in trades if t["type"] == "CLOSE"]

    if not closes:
        return {"coin": result["coin"], "total_trades": 0, "total_pnl_pct": 0,
                "message": "No trades", "period": result["period"]}

    pnls = [t["pnl_pct"] for t in closes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(closes) * 100 if closes else 0
    avg_win = mean(wins) if wins else 0
    avg_loss = mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")

    eq = result["equity_curve"]
    peak = eq[0]
    max_dd = 0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    returns = [(eq[i] - eq[i-1]) / eq[i-1] for i in range(1, len(eq)) if eq[i-1] > 0]
    sharpe = 0
    if len(returns) > 1 and stdev(returns) > 0:
        sharpe = (mean(returns) / stdev(returns)) * (365 ** 0.5)

    # Count direction bias
    long_trades = len([t for t in closes if "LONG" in str(t.get("reason", "")) or t["price"] > 0])
    short_trades = len([t for t in closes if "SHORT" in str(t.get("reason", "")) or t["price"] < 0])

    return {
        "coin": result["coin"],
        "total_trades": len(closes),
        "total_pnl_pct": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "period": result["period"],
        "message": None,
    }


def print_report(metrics: dict):
    if metrics.get("message"):
        print(f"  {metrics['coin']:6s} | {metrics['message']}")
        return
    dd_str = f"DD={metrics['max_drawdown_pct']:.1f}%"
    sharpe_str = f"S={metrics['sharpe_ratio']:.2f}"
    print(f"  {metrics['coin']:6s} | "
          f"Trades={metrics['total_trades']:2d} | "
          f"PnL={metrics['total_pnl_pct']:+6.2f}% | "
          f"Win={metrics['win_rate_pct']:4.0f}% | "
          f"AvgW={metrics['avg_win_pct']:+5.2f}% | "
          f"AvgL={metrics['avg_loss_pct']:+5.2f}% | "
          f"PF={metrics['profit_factor']:<5.2f} | "
          f"{dd_str:>8s} | {sharpe_str}")


def main():
    print("Crypto Trading Strategy Backtest (v6 trend-following)")
    print(f"{'='*70}")

    for period_key, period_info in PERIODS.items():
        print(f"\n{'='*70}")
        print(f"  Period: {period_info['label']}")
        print(f"{'='*70}")

        all_metrics = []
        for coin in COINS:
            try:
                result = backtest_coin(coin, period_info["start_time"],
                                       period_info.get("limit", LOOKBACK_DAYS))
                metrics = compute_metrics(result)
                all_metrics.append(metrics)
                print_report(metrics)
            except Exception as e:
                print(f"  {coin}: ERROR – {e}", file=sys.stderr)

        # Period summary
        print(f"  {'─'*68}")
        total_pnl_all = sum(m["total_pnl_pct"] for m in all_metrics if not m.get("message"))
        n_active = sum(1 for m in all_metrics if not m.get("message"))
        avg_pnl = total_pnl_all / n_active if n_active else 0
        avg_pf = mean([m["profit_factor"] for m in all_metrics if not m.get("message") and m.get("profit_factor", 0) != float("inf")]) if n_active else 0
        print(f"  TOTAL   | Coins={n_active} | Sum PnL={total_pnl_all:+7.2f}% | Avg PnL={avg_pnl:+6.2f}% | Avg PF={avg_pf:.2f}")

    # Cross-period comparison
    print(f"\n{'='*70}")
    print("  CROSS-PERIOD COMPARISON (PnL %)")
    print(f"{'='*70}")
    print(f"  {'Coin':>6s}  ", end="")
    for pk in PERIODS:
        print(f" {pk:>20s}  ", end="")
    print()
    print(f"  {'─'*6}  ", end="")
    for _ in PERIODS:
        print(f" {'─'*20}  ", end="")
    print()

    # Need to re-run for cross-period view... or store results
    # Simple approach: re-run
    for coin in COINS:
        print(f"  {coin:>6s}  ", end="")
        for pk, pi in PERIODS.items():
            try:
                res = backtest_coin(coin, pi["start_time"],
                                    pi.get("limit", LOOKBACK_DAYS))
                m = compute_metrics(res)
                if m.get("message"):
                    print(f" {'No trades':>20s}  ", end="")
                else:
                    print(f" {m['total_pnl_pct']:>+19.2f}%  ", end="")
            except Exception as e:
                print(f" {'ERROR':>20s}  ", end="")
        print()


if __name__ == "__main__":
    main()
