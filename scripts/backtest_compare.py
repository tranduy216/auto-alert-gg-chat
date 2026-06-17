#!/usr/bin/env python3
"""Compare original vs proposed rule changes for crypto_trading strategy."""

import sys
from datetime import datetime
from statistics import mean, stdev

import requests as req_lib

from crypto_trading import (
    sma, compute_atr, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, compute_reaction_score_long, compute_reaction_score_short,
    compute_resistance, compute_support, compute_break_score_long,
    compute_break_score_short, compute_atr_score,
    compute_entry1_signal_long, compute_entry1_signal_short,
    resolve_action_v4, _aggregate_daily_to_3d,
    SYMBOL_MAP,
)

BACKTEST_COINS = ["ETH", "BNB"]
LOOKBACK_DAYS = 400


def _fetch_klines_bt(symbol: str, interval: str = "1d", limit: int = 400) -> list[dict]:
    resp = req_lib.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
         "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
        for k in resp.json()
    ]


# ---------------------------------------------------------------------------
# Original entry logic (v4) – unchanged
# ---------------------------------------------------------------------------
def entry_v4(trend_score, entry1_long, entry1_short, prev_pos_state,
             p_le2, p_se2, p_le3, p_se3):
    return resolve_action_v4(trend_score, entry1_long, entry1_short,
                             p_le2, p_se2, p_le3, p_se3, prev_pos_state)


# ---------------------------------------------------------------------------
# Proposed entry logic (v6) – stricter
# ---------------------------------------------------------------------------
TREND_THRESH_V6 = 3          # ±2 → ±3
E2_THRESH_V6 = 0.80          # 0.70 → 0.80
E3_THRESH_V6 = 0.85          # 0.75 → 0.85


def entry_v6(trend_score, entry1_long, entry1_short, prev_pos_state,
             p_le2, p_se2, p_le3, p_se3):
    if prev_pos_state == "FLAT":
        if trend_score >= TREND_THRESH_V6 and entry1_long:
            return ("LONG_ENTRY_1", "OPEN_LONG_ENTRY_1")
        if trend_score <= -TREND_THRESH_V6 and entry1_short:
            return ("SHORT_ENTRY_1", "OPEN_SHORT_ENTRY_1")
        return ("FLAT", "NO_TRADE")

    if prev_pos_state == "LONG_ENTRY_1":
        if p_le2 >= E2_THRESH_V6:
            return ("LONG_ENTRY_2", "ADD_LONG_ENTRY_2")
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        if trend_score < 0:
            return ("FLAT", "REDUCE_LONG")
        return ("LONG_ENTRY_1", "HOLD")

    if prev_pos_state == "LONG_ENTRY_2":
        if p_le3 >= E3_THRESH_V6:
            return ("LONG_ENTRY_3", "ADD_LONG_ENTRY_3")
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        return ("LONG_ENTRY_2", "HOLD")

    if prev_pos_state == "LONG_ENTRY_3":
        if trend_score < -2:
            return ("FLAT", "EXIT_LONG")
        return ("LONG_ENTRY_3", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_1":
        if p_se2 >= E2_THRESH_V6:
            return ("SHORT_ENTRY_2", "ADD_SHORT_ENTRY_2")
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        if trend_score > 0:
            return ("FLAT", "REDUCE_SHORT")
        return ("SHORT_ENTRY_1", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_2":
        if p_se3 >= E3_THRESH_V6:
            return ("SHORT_ENTRY_3", "ADD_SHORT_ENTRY_3")
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        return ("SHORT_ENTRY_2", "HOLD")

    if prev_pos_state == "SHORT_ENTRY_3":
        if trend_score > 2:
            return ("FLAT", "EXIT_SHORT")
        return ("SHORT_ENTRY_3", "HOLD")

    return ("FLAT", "NO_TRADE")


# ---------------------------------------------------------------------------
# Exit logic variants
# ---------------------------------------------------------------------------

def exit_v5(prev_pos_state, entry_price, current_price, remaining_size,
            ma3, ma7, ma10, ma20, rsi, trend_score, ts_val):
    """Original exit rules."""
    from crypto_trading import evaluate_exit_v5
    return evaluate_exit_v5(prev_pos_state, entry_price, current_price,
                            remaining_size, ma3, ma7, ma10, ma20,
                            rsi, trend_score, ts_val)


def exit_v6(prev_pos_state, entry_price, current_price, remaining_size,
            ma3, ma7, ma10, ma20, rsi, trend_score, ts_val):
    """Stricter exit: tighter stop, earlier trend exit."""
    if prev_pos_state == "FLAT" or entry_price is None or entry_price <= 0:
        return ("HOLD", 0.0, "")

    is_long = prev_pos_state.startswith("LONG")
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if is_long \
              else ((entry_price - current_price) / entry_price * 100)

    # 1. Hard Stop Loss: -6% (was -8%)
    if pnl_pct <= -6:
        return ("EXIT_ALL", 1.0, f"Stop loss at {pnl_pct:.1f}%")

    # 2. Emergency exit
    if is_long:
        if ma3 < ma7 < ma10 and ts_val < -0.4:
            return ("EXIT_ALL", 1.0, f"Emergency exit")
    else:
        if ma3 > ma7 > ma10 and ts_val > 0.4:
            return ("EXIT_ALL", 1.0, f"Emergency exit")

    # 3. Trend exit: MA3 < MA10 (was MA3 < MA7) – earlier exit
    if is_long:
        if ma3 < ma10:
            return ("EXIT_ALL", 1.0, f"Trend exit MA3<MA10")
    else:
        if ma3 > ma10:
            return ("EXIT_ALL", 1.0, f"Trend exit MA3>MA10")

    # 4. Score exit – unchanged
    if is_long:
        if ts_val < 0.2:
            return ("EXIT_ALL", 1.0, f"Score exit {ts_val:.1f}")
    else:
        if ts_val > -0.2:
            return ("EXIT_ALL", 1.0, f"Score exit {ts_val:.1f}")

    # 5. Take Profit – unchanged
    if pnl_pct >= 25:
        return ("TAKE_PROFIT_2", remaining_size * 0.3, f"TP2 {pnl_pct:.1f}%")
    if pnl_pct >= 15:
        return ("TAKE_PROFIT_1", remaining_size * 0.3, f"TP1 {pnl_pct:.1f}%")

    # 6. Over-extension – unchanged
    if is_long:
        if current_price > ma20 * 1.25 or rsi > 80:
            return ("OVER_EXTEND", remaining_size * 0.25, "Over-extended")
    else:
        if current_price < ma20 * 0.75 or rsi < 20:
            return ("OVER_EXTEND", remaining_size * 0.25, "Over-extended")

    return ("HOLD", 0.0, "")


# ---------------------------------------------------------------------------
# Backtest engine (parameterised)
# ---------------------------------------------------------------------------

def backtest_coin(coin: str, entry_fn, exit_fn, label: str) -> dict:
    symbol = SYMBOL_MAP[coin]
    daily_all = _fetch_klines_bt(symbol, "1d", LOOKBACK_DAYS)
    daily_all = daily_all[-LOOKBACK_DAYS:]

    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0}
    closes = []

    MIN_INIT = 75

    for day_idx in range(MIN_INIT, len(daily_all)):
        daily_slice = daily_all[:day_idx + 1]
        candles_1d = daily_slice[-30:]
        candles_3d = _aggregate_daily_to_3d(daily_slice)
        if len(candles_3d) < 20:
            continue

        current_close = candles_1d[-1]["close"]

        # 3D indicators
        closes_3d = [c["close"] for c in candles_3d]
        ma3_3d = (sma(closes_3d, 3)[-1] or closes_3d[-1])
        ma7_3d = (sma(closes_3d, 7)[-1] or closes_3d[-1])
        ma10_3d = (sma(closes_3d, 10)[-1] or closes_3d[-1])
        ma20_3d = (sma(closes_3d, 20)[-1] or closes_3d[-1])
        _, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
        ts_val = trend_strength(trend_score)
        rsi_3d = compute_rsi(closes_3d, 14)

        # 1D indicators
        closes_1d = [c["close"] for c in candles_1d]
        highs_1d = [c["high"] for c in candles_1d]
        lows_1d = [c["low"] for c in candles_1d]
        volumes_1d = [c["volume"] for c in candles_1d]

        ma3_1d = (sma(closes_1d, 3)[-1] or closes_1d[-1])
        ma7_1d = (sma(closes_1d, 7)[-1] or closes_1d[-1])
        ma10_1d = (sma(closes_1d, 10)[-1] or closes_1d[-1])
        vol_ma20 = (sma(volumes_1d, 20)[-1] or volumes_1d[-1])
        atr_1d = compute_atr(candles_1d, 14)

        volume_score = compute_volume_score(volumes_1d[-1], vol_ma20)
        reaction_score_long = compute_reaction_score_long(current_close, lows_1d[-1], ma3_1d)
        reaction_score_short = compute_reaction_score_short(current_close, highs_1d[-1], ma3_1d)

        resistance = compute_resistance(candles_1d, ma7_1d, ma10_1d)
        support = compute_support(candles_1d, ma7_1d, ma10_1d)
        break_score_long = compute_break_score_long(current_close, resistance, atr_1d)
        break_score_short = compute_break_score_short(current_close, support, atr_1d)
        atr_score = compute_atr_score(atr_1d, current_close)

        entry1_long = compute_entry1_signal_long(current_close, ma7_1d, volume_score)
        entry1_short = compute_entry1_signal_short(current_close, ma7_1d, volume_score)

        ts_long = max(0.0, ts_val)
        ts_short = max(0.0, -ts_val)
        p_le2 = min(1.0, max(0.0, 0.35 * ts_long + 0.25 * reaction_score_long + 0.25 * volume_score + 0.15 * atr_score))
        p_se2 = min(1.0, max(0.0, 0.35 * ts_short + 0.25 * reaction_score_short + 0.25 * volume_score + 0.15 * atr_score))
        p_le3 = min(1.0, max(0.0, 0.30 * ts_long + 0.20 * reaction_score_long + 0.30 * volume_score + 0.20 * break_score_long))
        p_se3 = min(1.0, max(0.0, 0.30 * ts_short + 0.20 * reaction_score_short + 0.30 * volume_score + 0.20 * break_score_short))

        prev_pos_state = state["position_state"]
        entry_price = state["entry_price"]
        remaining_size = state["remaining_size"]

        if prev_pos_state == "FLAT":
            pos_state, action = entry_fn(trend_score, entry1_long, entry1_short,
                                         prev_pos_state, p_le2, p_se2, p_le3, p_se3)
            if action in ("OPEN_LONG_ENTRY_1",):
                entry_price = current_close
                remaining_size = 1.0
                state["entry_price"] = entry_price
                state["remaining_size"] = remaining_size
            elif action in ("OPEN_SHORT_ENTRY_1",):
                entry_price = current_close
                remaining_size = 1.0
                state["entry_price"] = entry_price
                state["remaining_size"] = remaining_size
            state["position_state"] = pos_state
        else:
            is_long = prev_pos_state.startswith("LONG")
            pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long \
                      else ((entry_price - current_close) / entry_price * 100) if entry_price else 0

            exit_action, reduce_pct, _ = exit_fn(
                prev_pos_state, entry_price, current_close, remaining_size,
                ma3_3d, ma7_3d, ma10_3d, ma20_3d, rsi_3d, trend_score, ts_val,
            )

            if exit_action == "HOLD":
                pos_state, action = entry_fn(trend_score, entry1_long, entry1_short,
                                             prev_pos_state, p_le2, p_se2, p_le3, p_se3)
                state["position_state"] = pos_state
            else:
                if exit_action == "EXIT_ALL":
                    closes.append(pnl_pct)
                    state["position_state"] = "FLAT"
                    state["remaining_size"] = 1.0
                    state["entry_price"] = None
                elif exit_action in ("TAKE_PROFIT_1", "TAKE_PROFIT_2", "OVER_EXTEND"):
                    cut = remaining_size * reduce_pct
                    remaining_size = round(remaining_size - cut, 4)
                    state["remaining_size"] = remaining_size
                    if remaining_size < 0.01:
                        state["position_state"] = "FLAT"
                        state["remaining_size"] = 1.0
                        state["entry_price"] = None

    return {"coin": coin, "closes": closes, "label": label}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(res: dict) -> dict:
    closes = res["closes"]
    n = len(closes)
    if n == 0:
        return {**res, "trades": 0, "pnl": 0, "win_rate": 0, "avg_win": 0,
                "avg_loss": 0, "profit_factor": 0}

    wins = [p for p in closes if p > 0]
    losses = [p for p in closes if p <= 0]
    total_pnl = sum(closes)
    win_rate = len(wins) / n * 100
    avg_win = mean(wins) if wins else 0
    avg_loss = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")

    return {
        **res,
        "trades": n,
        "pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(pf, 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

VARIANTS = [
    ("v4+v5 (original)", entry_v4, exit_v5),
    ("v6 (stricter entry + tighter exit)", entry_v6, exit_v6),
]

def main():
    print("=" * 72)
    print("  Strategy Comparison: Original vs Proposed")
    print("=" * 72)
    print()

    for label, entry_fn, exit_fn in VARIANTS:
        print(f"\n  {'─'*68}")
        print(f"  {label}")
        print(f"  {'─'*68}")
        all_m = []
        for coin in BACKTEST_COINS:
            res = backtest_coin(coin, entry_fn, exit_fn, label)
            m = compute_metrics(res)
            all_m.append(m)
            print(f"    {coin:6s} | Trades={m['trades']:2d} | "
                  f"PnL={m['pnl']:+.1f}% | Win={m['win_rate']:4.0f}% | "
                  f"AvgW={m['avg_win']:+.1f}% | AvgL={m['avg_loss']:+.1f}% | "
                  f"PF={m['profit_factor']:.2f}")

        total_pnl = sum(m['pnl'] for m in all_m)
        print(f"    {'─'*60}")
        print(f"    TOTAL  | PnL={total_pnl:+.1f}% (3 coins combined)")

    print()
    print("=" * 72)
    print("  Proposed changes:")
    print("  • Entry: TrendScore ±2 → ±3 (strong trends only)")
    print("  • Add E2: 0.70 → 0.80, Add E3: 0.75 → 0.85")
    print("  • Stop loss: -8% → -6%")
    print("  • Trend exit: MA3<MA7 → MA3<MA10 (earlier)")
    print("=" * 72)


if __name__ == "__main__":
    main()
