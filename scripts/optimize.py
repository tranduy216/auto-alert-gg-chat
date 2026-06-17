"""Parameter sweep: find optimal SL, TP, entry thresholds. Fetches data once."""
import os, sys, itertools
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
    resolve_action_v4, _aggregate_daily_to_3d,
    COINS, SYMBOL_MAP, LEVERAGE,
)
from backtest_crypto import MIN_3D_PERIODS

def fetch_all(symbol, start_ms):
    params = {"symbol": symbol, "interval": "1d", "limit": 450}
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

def run_backtest(daily_all, sl_pct, tp1_pct, entry2_thresh, entry3_thresh):
    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0}
    trades = []
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
        p_long_entry2 = min(1.0, max(0.0, 0.35*ts_long + 0.25*reaction_score_long + 0.25*volume_score + 0.15*atr_score))
        p_short_entry2 = min(1.0, max(0.0, 0.35*ts_short + 0.25*reaction_score_short + 0.25*volume_score + 0.15*atr_score))
        p_long_entry3 = min(1.0, max(0.0, 0.30*ts_long + 0.20*reaction_score_long + 0.30*volume_score + 0.20*break_score_long))
        p_short_entry3 = min(1.0, max(0.0, 0.30*ts_short + 0.20*reaction_score_short + 0.30*volume_score + 0.20*break_score_short))

        prev_pos_state = state["position_state"]
        entry_price = state["entry_price"]
        remaining_size = state["remaining_size"]

        if prev_pos_state == "FLAT":
            pos_state, action = resolve_action_v4(
                trend_score, entry1_long, entry1_short,
                p_long_entry2, p_short_entry2, p_long_entry3, p_short_entry3,
                prev_pos_state,
            )
            if action in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                entry_price = current_close
                remaining_size = 1.0
                trades.append({"type": "OPEN", "price": current_close})
            state.update({"position_state": pos_state or prev_pos_state,
                          "entry_price": entry_price, "remaining_size": remaining_size})
        else:
            is_long = prev_pos_state.startswith("LONG")
            if entry_price and entry_price > 0:
                pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long else ((entry_price - current_close) / entry_price * 100)
            else:
                pnl_pct = 0.0

            exit_action = "HOLD"
            exit_reason = ""

            if pnl_pct <= -abs(sl_pct):
                exit_action = "EXIT_ALL"
                exit_reason = f"SL"
            if exit_action == "HOLD" and is_long and ma3_1d < ma10_1d:
                exit_action = "EXIT_ALL"
                exit_reason = "MA"
            elif exit_action == "HOLD" and not is_long and ma3_1d > ma10_1d:
                exit_action = "EXIT_ALL"
                exit_reason = "MA"
            if exit_action == "HOLD" and is_long and ts_val < 0.2:
                exit_action = "EXIT_ALL"
                exit_reason = "SCORE"
            elif exit_action == "HOLD" and not is_long and ts_val > -0.2:
                exit_action = "EXIT_ALL"
                exit_reason = "SCORE"
            if exit_action == "HOLD" and pnl_pct >= tp1_pct:
                exit_action = "TAKE_PROFIT"
                exit_reason = "TP"

            if exit_action == "HOLD":
                pos_state = prev_pos_state
                if p_long_entry2 >= entry2_thresh and prev_pos_state == "LONG_ENTRY_1":
                    pos_state = "LONG_ENTRY_2"
                elif p_long_entry3 >= entry3_thresh and prev_pos_state == "LONG_ENTRY_2":
                    pos_state = "LONG_ENTRY_3"
                elif p_short_entry2 >= entry2_thresh and prev_pos_state == "SHORT_ENTRY_1":
                    pos_state = "SHORT_ENTRY_2"
                elif p_short_entry3 >= entry3_thresh and prev_pos_state == "SHORT_ENTRY_2":
                    pos_state = "SHORT_ENTRY_3"
                else:
                    pos_state = prev_pos_state
            else:
                if exit_action == "EXIT_ALL":
                    if abs(pnl_pct) > 0.1:
                        trades.append({"type": "CLOSE", "pnl_pct": round(pnl_pct, 2), "reason": exit_reason})
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
                elif exit_action == "TAKE_PROFIT":
                    cut = remaining_size * 0.3
                    remaining_size = round(remaining_size - cut, 4)
                    pos_state = prev_pos_state
                if remaining_size < 0.01 and pos_state != "FLAT":
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size})

    closes = [t for t in trades if t.get("type") == "CLOSE"]
    pnls = [t["pnl_pct"] for t in closes]
    if not pnls:
        return None
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total_pnl = sum(pnls)
    win_rate = len(wins) / len(closes) * 100
    avg_win = mean(wins) if wins else 0
    avg_loss = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")

    return {"trades": len(closes), "pnl": round(total_pnl, 2),
            "wr": round(win_rate, 1), "avg_w": round(avg_win, 2),
            "avg_l": round(avg_loss, 2), "pf": round(pf, 2)}

def main():
    print("Fetching ETH data 2021-2026...")
    start_ms = int(datetime(2021, 1, 1).timestamp() * 1000)
    fetch_start = start_ms - (450 * 86400_000)
    daily_all = fetch_all("ETHUSDT", fetch_start)
    daily_all = [d for d in daily_all if d["open_time"] < int(datetime(2026, 6, 18).timestamp() * 1000)]
    print(f"  {len(daily_all)} candles loaded")

    sl_vals = [-4, -5, -6, -7, -8, -10, -12]
    tp_vals = [6, 8, 10, 12, 15]
    e2_vals = [0.70, 0.75, 0.80, 0.85]
    e3_vals = [0.75, 0.80, 0.85, 0.90]

    results = []
    total = len(sl_vals) * len(tp_vals) * len(e2_vals) * len(e3_vals)
    count = 0

    for sl, tp, e2, e3 in itertools.product(sl_vals, tp_vals, e2_vals, e3_vals):
        count += 1
        if count % 50 == 0:
            print(f"  [{count}/{total}]")
        r = run_backtest(daily_all, sl, tp, e2, e3)
        if r and r["trades"] >= 3:
            score = r["pf"] * max(r["pnl"], 0) / 100
            results.append((score, sl, tp, e2, e3, r))

    results.sort(key=lambda x: -x[0])

    print(f"\n{'='*90}")
    print(f"  TOP PARAMETER SETS (ETH 2021-2026)")
    print(f"{'='*90}")
    print(f"  {'Rank':<5} {'SL%':<5} {'TP%':<5} {'E2':<5} {'E3':<5} | "
          f"{'Trades':<7} {'PnL%':<8} {'WR%':<5} {'AvgW':<7} {'AvgL':<7} {'PF':<6}")
    print(f"  {'─'*5} {'─'*5} {'─'*5} {'─'*5} {'─'*5} | "
          f"{'─'*7} {'─'*8} {'─'*5} {'─'*7} {'─'*7} {'─'*6}")
    for i, (score, sl, tp, e2, e3, r) in enumerate(results[:20]):
        print(f"  {i+1:<5} {sl:<5} {tp:<5} {e2:<5.2f} {e3:<5.2f} | "
              f"{r['trades']:<7} {r['pnl']:<+8.2f}% {r['wr']:<5.1f} "
              f"{r['avg_w']:<+7.2f}% {r['avg_l']:<+7.2f}% {r['pf']:<6.2f}")

    profitable = [r for r in results if r[1] > 0]  # score > 0 means pnl > 0
    print(f"\n  Profitable combos: {len(profitable)}/{total}")
    if profitable:
        best = profitable[0]
        print(f"  Best: SL={best[1]}% TP={best[2]}% E2={best[3]} E3={best[4]} | PnL={best[5]['pnl']}% PF={best[5]['pf']}")

if __name__ == "__main__":
    main()
