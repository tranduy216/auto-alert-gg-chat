#!/usr/bin/env python3
"""Backtest crypto_trading v4/v5 strategy over historical data."""

import json
import os
import sys
from datetime import datetime
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests as req_lib

from crypto_trading import (
    sma, compute_atr, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, compute_reaction_score_long, compute_reaction_score_short,
    compute_resistance, compute_support, compute_break_score_long,
    compute_break_score_short, compute_atr_score,
    compute_entry1_signal_long, compute_entry1_signal_short,
    resolve_action_v4, evaluate_exit_v5, compute_next_rules,
    _aggregate_daily_to_3d,
    SYMBOL_MAP, LEVERAGE,
)

BACKTEST_COINS = ["ETH", "BNB", "SOL"]
LOOKBACK_DAYS = 400
MIN_3D_PERIODS = 25


def _fetch_klines_backtest(symbol: str, interval: str = "1d", limit: int = 400) -> list[dict]:
    """Fetch historical klines with a configurable limit."""
    resp = req_lib.get(
        f"https://api.binance.com/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in data
    ]


def backtest_coin(coin: str) -> dict:
    print(f"\n=== Backtesting {coin} ===")
    symbol = SYMBOL_MAP[coin]

    # Fetch 1D historical data
    print(f"  Fetching {LOOKBACK_DAYS}d of 1D data…")
    daily_all = _fetch_klines_backtest(symbol, "1d", LOOKBACK_DAYS)
    print(f"  Got {len(daily_all)} candles")
    daily_all = daily_all[-LOOKBACK_DAYS:]

    closes_1d_all = [c["close"] for c in daily_all]

    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0}
    trades = []
    equity_curve = [1.0]

    INITIAL_DAYS = MIN_3D_PERIODS * 3

    for day_idx in range(INITIAL_DAYS, len(daily_all)):
        daily_slice = daily_all[:day_idx + 1]
        candles_1d = daily_slice[-30:]
        candles_3d = _aggregate_daily_to_3d(daily_slice)

        if len(candles_3d) < MIN_3D_PERIODS:
            continue

        current_close = candles_1d[-1]["close"]

        # -- 3D indicators --
        closes_3d = [c["close"] for c in candles_3d]
        ma3_3d = (sma(closes_3d, 3)[-1] or closes_3d[-1])
        ma7_3d = (sma(closes_3d, 7)[-1] or closes_3d[-1])
        ma10_3d = (sma(closes_3d, 10)[-1] or closes_3d[-1])
        ma20_3d = (sma(closes_3d, 20)[-1] or closes_3d[-1])
        trend_label, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
        ts_val = trend_strength(trend_score)
        rsi_3d = compute_rsi(closes_3d, 14)

        # -- 1D indicators --
        closes_1d = [c["close"] for c in candles_1d]
        highs_1d = [c["high"] for c in candles_1d]
        lows_1d = [c["low"] for c in candles_1d]
        volumes_1d = [c["volume"] for c in candles_1d]

        ma3_1d = (sma(closes_1d, 3)[-1] or closes_1d[-1])
        ma7_1d = (sma(closes_1d, 7)[-1] or closes_1d[-1])
        ma10_1d = (sma(closes_1d, 10)[-1] or closes_1d[-1])
        vol_ma20 = (sma(volumes_1d, 20)[-1] or volumes_1d[-1])

        last_low = lows_1d[-1]
        last_high = highs_1d[-1]
        last_volume = volumes_1d[-1]
        atr_1d = compute_atr(candles_1d, 14)

        volume_score = compute_volume_score(last_volume, vol_ma20)
        reaction_score_long = compute_reaction_score_long(current_close, last_low, ma3_1d)
        reaction_score_short = compute_reaction_score_short(current_close, last_high, ma3_1d)

        resistance = compute_resistance(candles_1d, ma7_1d, ma10_1d)
        support = compute_support(candles_1d, ma7_1d, ma10_1d)
        break_score_long = compute_break_score_long(current_close, resistance, atr_1d)
        break_score_short = compute_break_score_short(current_close, support, atr_1d)
        atr_score = compute_atr_score(atr_1d, current_close)

        entry1_long = compute_entry1_signal_long(current_close, ma7_1d, volume_score)
        entry1_short = compute_entry1_signal_short(current_close, ma7_1d, volume_score)

        ts_long = max(0.0, ts_val)
        ts_short = max(0.0, -ts_val)
        p_long_entry2 = min(1.0, max(0.0, 0.35 * ts_long + 0.25 * reaction_score_long + 0.25 * volume_score + 0.15 * atr_score))
        p_short_entry2 = min(1.0, max(0.0, 0.35 * ts_short + 0.25 * reaction_score_short + 0.25 * volume_score + 0.15 * atr_score))
        p_long_entry3 = min(1.0, max(0.0, 0.30 * ts_long + 0.20 * reaction_score_long + 0.30 * volume_score + 0.20 * break_score_long))
        p_short_entry3 = min(1.0, max(0.0, 0.30 * ts_short + 0.20 * reaction_score_short + 0.30 * volume_score + 0.20 * break_score_short))

        dt = daily_slice[-1]["open_time"]
        if isinstance(dt, int):
            date_str = datetime.utcfromtimestamp(dt / 1000).strftime("%Y-%m-%d")
        else:
            date_str = str(dt)

        prev_pos_state = state["position_state"]
        entry_price = state["entry_price"]
        remaining_size = state["remaining_size"]

        if prev_pos_state == "FLAT":
            pos_state, action = resolve_action_v4(
                trend_score, entry1_long, entry1_short,
                p_long_entry2, p_short_entry2, p_long_entry3, p_short_entry3,
                prev_pos_state,
            )
            if action == "OPEN_LONG_ENTRY_1":
                entry_price = current_close
                remaining_size = 1.0
                trades.append({"date": date_str, "type": "LONG_OPEN", "price": current_close, "size": 1.0, "reason": f"TrendScore={trend_score}"})
            elif action == "OPEN_SHORT_ENTRY_1":
                entry_price = current_close
                remaining_size = 1.0
                trades.append({"date": date_str, "type": "SHORT_OPEN", "price": current_close, "size": 1.0, "reason": f"TrendScore={trend_score}"})
            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size})
        else:
            is_long = prev_pos_state.startswith("LONG")
            if entry_price and entry_price > 0:
                pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long else ((entry_price - current_close) / entry_price * 100)
            else:
                pnl_pct = 0.0

            exit_action, reduce_pct, exit_reason = evaluate_exit_v5(
                prev_pos_state, entry_price, current_close, remaining_size,
                ma3_3d, ma7_3d, ma10_3d, ma20_3d, rsi_3d, trend_score, ts_val,
            )

            if exit_action == "HOLD":
                add_cond = (
                    (p_long_entry2 >= 0.70 and prev_pos_state == "LONG_ENTRY_1") or
                    (p_long_entry3 >= 0.75 and prev_pos_state == "LONG_ENTRY_2") or
                    (p_short_entry2 >= 0.70 and prev_pos_state == "SHORT_ENTRY_1") or
                    (p_short_entry3 >= 0.75 and prev_pos_state == "SHORT_ENTRY_2")
                )
                if add_cond:
                    dir = "LONG" if is_long else "SHORT"
                    trades.append({"date": date_str, "type": f"{dir}_ADD", "price": current_close, "size": remaining_size, "reason": "add entry"})
                pos_state = prev_pos_state
                action = "HOLD"
            else:
                if exit_action == "EXIT_ALL":
                    pnl = pnl_pct
                    trades.append({"date": date_str, "type": "CLOSE", "price": current_close, "size": remaining_size, "pnl_pct": round(pnl, 2), "reason": exit_reason})
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
                elif exit_action in ("TAKE_PROFIT_1", "TAKE_PROFIT_2"):
                    cut = remaining_size * 0.3
                    remaining_size = round(remaining_size - cut, 4)
                    dir = "LONG" if is_long else "SHORT"
                    trades.append({"date": date_str, "type": f"TP_{exit_action[-1]}", "price": current_close, "size": cut, "reason": exit_reason})
                    pos_state = prev_pos_state
                elif exit_action == "OVER_EXTEND":
                    cut = remaining_size * 0.25
                    remaining_size = round(remaining_size - cut, 4)
                    dir = "LONG" if is_long else "SHORT"
                    trades.append({"date": date_str, "type": "OVER_EXTEND", "price": current_close, "size": cut, "reason": exit_reason})
                    pos_state = prev_pos_state

                if remaining_size < 0.01 and pos_state != "FLAT":
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None

            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size})

        # Equity curve: track P&L of current positions
        if state["position_state"] != "FLAT" and state["entry_price"] and state["remaining_size"] > 0:
            is_long = state["position_state"].startswith("LONG")
            upnl = ((current_close - state["entry_price"]) / state["entry_price"] * 100) if is_long else ((state["entry_price"] - current_close) / state["entry_price"] * 100)
            equity_curve.append(1.0 + upnl / 100 * state["remaining_size"])
        else:
            equity_curve.append(1.0)

    return {"coin": coin, "trades": trades, "equity_curve": equity_curve}


def compute_metrics(result: dict) -> dict:
    trades = result["trades"]
    closes = [t for t in trades if t["type"] == "CLOSE"]
    
    if not closes:
        return {"coin": result["coin"], "total_trades": 0, "message": "No trades"}

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
    }


def print_report(metrics: dict):
    print(f"\n{'='*50}")
    print(f"  Backtest Results: {metrics['coin']}")
    print(f"{'='*50}")
    if metrics.get("message"):
        print(f"  {metrics['message']}")
        return
    print(f"  Total Trades:     {metrics['total_trades']}")
    print(f"  Total PnL:        {metrics['total_pnl_pct']:+.2f}%")
    print(f"  Win Rate:         {metrics['win_rate_pct']:.1f}%")
    print(f"  Avg Win:          {metrics['avg_win_pct']:+.2f}%")
    print(f"  Avg Loss:         {metrics['avg_loss_pct']:+.2f}%")
    print(f"  Profit Factor:    {metrics['profit_factor']:.2f}")
    print(f"  Max Drawdown:     {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio:     {metrics['sharpe_ratio']:.2f}")


def main():
    print("Crypto Trading Strategy Backtest (v4+v5)")
    print(f"Coins: {', '.join(BACKTEST_COINS)}")
    print(f"Period: last {LOOKBACK_DAYS} days of daily data\n")

    all_metrics = []
    for coin in BACKTEST_COINS:
        try:
            result = backtest_coin(coin)
            metrics = compute_metrics(result)
            all_metrics.append(metrics)
            print_report(metrics)
        except Exception as e:
            print(f"\n  Error backtesting {coin}: {e}", file=sys.stderr)

    print(f"\n{'='*50}")
    print("  SUMMARY")
    print(f"{'='*50}")
    for m in all_metrics:
        if m.get("message"):
            print(f"  {m['coin']}: {m['message']}")
        else:
            print(f"  {m['coin']}: PnL={m['total_pnl_pct']:+.2f}% | "
                  f"Trades={m['total_trades']} | "
                  f"Win={m['win_rate_pct']:.0f}% | "
                  f"DD={m['max_drawdown_pct']:.1f}% | "
                  f"Sharpe={m['sharpe_ratio']:.2f}")


if __name__ == "__main__":
    main()
