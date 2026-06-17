"""Yearly backtest: 2021–2026. Capital: $10,000, 2.5x leverage, cross margin."""
import os, sys, json
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
    resolve_action_v4, evaluate_exit_v5, _aggregate_daily_to_3d,
    COINS, SYMBOL_MAP, LEVERAGE,
)
from backtest_crypto import _fetch_klines_backtest, backtest_coin, compute_metrics, MIN_3D_PERIODS, LOOKBACK_DAYS

INITIAL_CAPITAL = 10_000

YEARS = [
    ("2021", int(datetime(2021, 1, 1).timestamp() * 1000),
             int(datetime(2022, 1, 1).timestamp() * 1000)),
    ("2022", int(datetime(2022, 1, 1).timestamp() * 1000),
             int(datetime(2023, 1, 1).timestamp() * 1000)),
    ("2023", int(datetime(2023, 1, 1).timestamp() * 1000),
             int(datetime(2024, 1, 1).timestamp() * 1000)),
    ("2024", int(datetime(2024, 1, 1).timestamp() * 1000),
             int(datetime(2025, 1, 1).timestamp() * 1000)),
    ("2025", int(datetime(2025, 1, 1).timestamp() * 1000),
             int(datetime(2026, 1, 1).timestamp() * 1000)),
    ("2026", int(datetime(2026, 1, 1).timestamp() * 1000), None),
]

def backtest_coin_period(coin, start_ms, end_ms):
    """Run backtest on a specific time window. Returns yearly result."""
    symbol = SYMBOL_MAP[coin]
    lookback = 450
    fetch_start = start_ms - (lookback * 86400_000) if start_ms else None
    fetch_limit = lookback + 370

    params = {"symbol": symbol, "interval": "1d", "limit": fetch_limit}
    if fetch_start:
        params["startTime"] = fetch_start
    resp = req_lib.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    daily_all = [
        {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in data
    ]

    if end_ms:
        daily_all = [d for d in daily_all if d["open_time"] < end_ms]

    if len(daily_all) < MIN_3D_PERIODS * 3 + 10:
        return {"coin": coin, "total_trades": 0, "total_pnl_pct": 0, "message": "Insufficient data"}

    first_date = datetime.utcfromtimestamp(daily_all[0]["open_time"] / 1000).strftime("%Y-%m-%d")
    last_date = datetime.utcfromtimestamp(daily_all[-1]["open_time"] / 1000).strftime("%Y-%m-%d")

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
        closes_3d = [c["close"] for c in candles_3d]
        ma3_3d = (sma(closes_3d, 3)[-1] or closes_3d[-1])
        ma7_3d = (sma(closes_3d, 7)[-1] or closes_3d[-1])
        ma10_3d = (sma(closes_3d, 10)[-1] or closes_3d[-1])
        ma20_3d = (sma(closes_3d, 20)[-1] or closes_3d[-1])
        _, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
        ts_val = trend_strength(trend_score)
        rsi_3d = compute_rsi(closes_3d, 14)

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
        date_str = datetime.utcfromtimestamp(dt / 1000).strftime("%Y-%m-%d") if isinstance(dt, int) else str(dt)

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
                trades.append({"date": date_str, "type": "LONG_OPEN", "price": current_close, "size": 1.0})
            elif action == "OPEN_SHORT_ENTRY_1":
                entry_price = current_close
                remaining_size = 1.0
                trades.append({"date": date_str, "type": "SHORT_OPEN", "price": current_close, "size": 1.0})
            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size})
        else:
            is_long = prev_pos_state.startswith("LONG")
            pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long and entry_price and entry_price > 0 else ((entry_price - current_close) / entry_price * 100) if entry_price and entry_price > 0 else 0.0

            exit_action, reduce_pct, exit_reason = evaluate_exit_v5(
                prev_pos_state, entry_price, current_close, remaining_size,
                ma3_3d, ma7_3d, ma10_3d, ma20_3d, rsi_3d, trend_score, ts_val,
            )

            if exit_action == "HOLD":
                pos_state = prev_pos_state
                action = "HOLD"
                if p_long_entry2 >= 0.80 and prev_pos_state == "LONG_ENTRY_1":
                    pos_state, action = "LONG_ENTRY_2", "ADD_LONG_ENTRY_2"
                elif p_long_entry3 >= 0.85 and prev_pos_state == "LONG_ENTRY_2":
                    pos_state, action = "LONG_ENTRY_3", "ADD_LONG_ENTRY_3"
                elif p_short_entry2 >= 0.80 and prev_pos_state == "SHORT_ENTRY_1":
                    pos_state, action = "SHORT_ENTRY_2", "ADD_SHORT_ENTRY_2"
                elif p_short_entry3 >= 0.85 and prev_pos_state == "SHORT_ENTRY_2":
                    pos_state, action = "SHORT_ENTRY_3", "ADD_SHORT_ENTRY_3"
            else:
                if exit_action == "EXIT_ALL":
                    pnl = pnl_pct
                    trades.append({"date": date_str, "type": "CLOSE", "price": current_close, "pnl_pct": round(pnl, 2), "reason": exit_reason})
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
                elif exit_action in ("TAKE_PROFIT_1", "TAKE_PROFIT_2"):
                    cut = remaining_size * 0.3
                    remaining_size = round(remaining_size - cut, 4)
                    trades.append({"date": date_str, "type": f"TP_{exit_action[-1]}", "price": current_close, "size": cut, "reason": exit_reason})
                    pos_state = prev_pos_state
                elif exit_action == "OVER_EXTEND":
                    cut = remaining_size * 0.25
                    remaining_size = round(remaining_size - cut, 4)
                    trades.append({"date": date_str, "type": "OVER_EXTEND", "price": current_close, "size": cut, "reason": exit_reason})
                    pos_state = prev_pos_state
                if remaining_size < 0.01 and pos_state != "FLAT":
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size})

        if state["position_state"] != "FLAT" and state["entry_price"] and state["remaining_size"] > 0:
            is_long = state["position_state"].startswith("LONG")
            upnl = ((current_close - state["entry_price"]) / state["entry_price"] * 100) if is_long else ((state["entry_price"] - current_close) / state["entry_price"] * 100)
            equity_curve.append(1.0 + upnl / 100 * state["remaining_size"])
        else:
            equity_curve.append(1.0)

    closes = [t for t in trades if t["type"] == "CLOSE"]
    pnls = [t["pnl_pct"] for t in closes]
    total_pnl = sum(pnls) if pnls else 0.0
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(closes) * 100 if closes else 0.0
    avg_win = mean(wins) if wins else 0.0
    avg_loss = mean(losses) if losses else 0.0
    profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")

    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    returns = [(equity_curve[i] - equity_curve[i-1]) / equity_curve[i-1] for i in range(1, len(equity_curve)) if equity_curve[i-1] > 0]
    sharpe = (mean(returns) / stdev(returns)) * (365 ** 0.5) if len(returns) > 1 and stdev(returns) > 0 else 0.0

    return {
        "coin": coin, "period": f"{first_date} → {last_date}",
        "total_trades": len(closes), "total_pnl_pct": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1), "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2), "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2), "sharpe_ratio": round(sharpe, 2),
        "trades": trades, "equity_curve": equity_curve, "message": "No trades" if not closes else None,
    }


def main():
    print(f"{'='*80}")
    print(f"  Yearly Backtest: $10,000 capital, {LEVERAGE}x leverage")
    print(f"  Coins: {', '.join(COINS)}")
    print(f"{'='*80}")

    all_results = {}
    for year_label, start_ms, end_ms in YEARS:
        print(f"\n{'─'*80}")
        print(f"  {year_label}")
        print(f"{'─'*80}")
        year_results = []
        for coin in COINS:
            try:
                r = backtest_coin_period(coin, start_ms, end_ms)
                year_results.append(r)
                if r.get("message"):
                    print(f"  {coin:6s} | {r['message']}")
                else:
                    dd_str = f"DD={r['max_drawdown_pct']:.1f}%"
                    sh_str = f"S={r['sharpe_ratio']:.2f}"
                    print(f"  {coin:6s} | Trades={r['total_trades']:2d} | "
                          f"PnL={r['total_pnl_pct']:+7.2f}% | "
                          f"Win={r['win_rate_pct']:4.0f}% | "
                          f"AvgW={r['avg_win_pct']:+5.2f}% | "
                          f"AvgL={r['avg_loss_pct']:+5.2f}% | "
                          f"PF={r['profit_factor']:<5.2f} | {dd_str} | {sh_str}")
            except Exception as e:
                print(f"  {coin:6s} | ERROR – {e}")
        all_results[year_label] = year_results

        active = [r for r in year_results if not r.get("message")]
        if active:
            total_pnl = sum(r["total_pnl_pct"] for r in active)
            avg_pf = mean([r["profit_factor"] for r in active if r["profit_factor"] != float("inf")])
            print(f"  {'─'*68}")
            print(f"  YEAR   | Coins={len(active)} | Sum PnL={total_pnl:+7.2f}% | Avg PF={avg_pf:.2f}")

    # Cross-year comparison
    print(f"\n{'='*80}")
    print(f"  CROSS-YEAR COMPARISON (PnL %)")
    print(f"{'='*80}")
    header = f"  {'Coin':>6s}  "
    for yl, _, _ in YEARS:
        header += f" {yl:>8s}  "
    print(header)
    print(f"  {'─'*6}  " + " ".join([f"{'─'*8}" for _ in YEARS]))
    for coin in COINS:
        line = f"  {coin:>6s}  "
        for yl, _, _ in YEARS:
            results = all_results.get(yl, [])
            for r in results:
                if r["coin"] == coin:
                    if r.get("message"):
                        line += f" {'No trade':>8s}  "
                    else:
                        line += f" {r['total_pnl_pct']:>+7.2f}%  "
                    break
        print(line)

    # Total returns
    print(f"\n{'='*80}")
    print(f"  TOTAL RETURN ESTIMATE")
    print(f"{'='*80}")
    print(f"  Strategy: each coin gets equal capital share = ${INITIAL_CAPITAL // len(COINS):,.0f}")
    print(f"  Portfolio return = equal-weighted average of coin PnL per year")
    print()

    cumulative = INITIAL_CAPITAL
    print(f"  {'Year':>6s} | {'Start':>10s} | {'Return%':>8s} | {'PnL $':>10s} | {'End':>10s}")
    print(f"  {'─'*6} | {'─'*10} | {'─'*8} | {'─'*10} | {'─'*10}")
    for yl, _, _ in YEARS:
        year_start = cumulative
        results = all_results.get(yl, [])
        active = [r for r in results if not r.get("message")]
        if active:
            avg_return = sum(r["total_pnl_pct"] for r in active) / len(active)
        else:
            avg_return = 0.0
        pnl_usd = year_start * avg_return / 100
        cumulative = year_start + pnl_usd
        print(f"  {yl:>6s} | ${year_start:>8,.0f} | {avg_return:>+7.2f}% | ${pnl_usd:>+8,.0f} | ${cumulative:>8,.0f}")

    total_pnl_pct = (cumulative - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    print(f"  {'─'*6} | {'─'*10} | {'─'*8} | {'─'*10} | {'─'*10}")
    print(f"  {'TOTAL':>6s} | ${INITIAL_CAPITAL:>8,.0f} | {total_pnl_pct:>+7.2f}% | ${cumulative - INITIAL_CAPITAL:>+8,.0f} | ${cumulative:>8,.0f}")


if __name__ == "__main__":
    main()
