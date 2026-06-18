#!/usr/bin/env python3
"""Comprehensive v6 parameter sweep: MA pairs, entry thresholds, coins, leverage, stop params.

Phases:
  1. Core: MA pairs × entry thresholds × volume score (fixed stop params)
  2. Leverage: best from Phase 1 × leverage values
  3. Stop: best from Phase 2 × max_loss/trailing/hard_stop
  4. Coins: best from Phase 3 × SOL vs BTC
"""

import itertools
import os
import sys
from datetime import datetime, timedelta
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, _aggregate_daily_to_3d,
    COINS, SYMBOL_MAP, SHORT_ALLOWED, LEVERAGE as CURRENT_LEVERAGE,
    SHORT_TREND_FAST, SHORT_TREND_SLOW,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

BINANCE_MAX_LIMIT = 1000
MIN_3D_PERIODS = 25

PERIODS = {
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

# ---------- data cache ----------
_data_cache: dict = {}

def fetch_all_klines(symbol: str, limit: int = 1000, start_time: int | None = None) -> list[dict]:
    key = (symbol, limit, start_time)
    if key in _data_cache:
        return _data_cache[key]
    candles = []
    remaining = limit
    cur_start = start_time
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        params = {"symbol": symbol, "interval": "1d", "limit": take + 50}
        if cur_start:
            params["startTime"] = cur_start
        resp = req_lib.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        batch = [
            {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in data
        ]
        if len(batch) <= 1:
            break
        candles.extend(batch)
        remaining -= len(batch)
        cur_start = batch[-1]["open_time"] + 1
        if len(candles) >= limit:
            break
    result = candles[:limit]
    _data_cache[key] = result
    return result


# ======================= PARAMETERIZED STRATEGY =======================

def entry_condition_long(
    trend_score: int, rsi_1d: float, close: float, ma20_1d: float,
    trend_ma_slow: float, trend_ma_fast: float | None, volume_score: float,
    trend_min: int = 1, vol_min: float = 0.3,
) -> bool:
    if trend_score < trend_min:
        return False
    if trend_ma_fast is not None and trend_ma_fast < trend_ma_slow:
        return False
    if close < ma20_1d:
        return False
    if close < trend_ma_slow:
        return False
    if volume_score < vol_min:
        return False
    return True

def entry_condition_short(
    trend_score: int, rsi_1d: float, close: float, ma20_1d: float,
    trend_ma_slow: float, trend_ma_fast: float | None, volume_score: float,
    trend_max: int = -3, vol_min: float = 0.3,
) -> bool:
    if trend_score > trend_max:
        return False
    if trend_ma_fast is not None and trend_ma_fast > trend_ma_slow:
        return False
    if close > ma20_1d:
        return False
    if close > trend_ma_slow:
        return False
    if volume_score < vol_min:
        return False
    return True

def exit_condition_v6(
    position_state: str, entry_price: float | None, current_price: float,
    remaining_size: float, ma7_3d: float, ma20_3d: float, trend_score: int,
    ts_val: float, rsi_3d: float, trailing_stop: float | None,
    highest_since_entry: float | None,
    max_loss_pct: float = 0.06, trailing_pct: float = 0.85, hard_stop_pct: float = 0.78,
) -> tuple[str, float, str, float | None, float | None]:
    if position_state == "FLAT" or entry_price is None or entry_price <= 0:
        return ("HOLD", 0.0, "", trailing_stop, highest_since_entry)
    is_long = position_state.startswith("LONG")
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if is_long \
              else ((entry_price - current_price) / entry_price * 100)
    best_price = max(highest_since_entry or entry_price, current_price) if is_long \
                 else min(highest_since_entry or entry_price, current_price)
    new_stop = trailing_stop
    if new_stop is None:
        new_stop = round(entry_price * (trailing_pct if is_long else (2 - trailing_pct)), 2)
    if is_long:
        if best_price > (highest_since_entry or entry_price):
            trail_buffer = best_price * trailing_pct
            if trail_buffer > new_stop:
                new_stop = round(trail_buffer, 2)
    else:
        if best_price < (highest_since_entry or entry_price):
            trail_buffer = best_price * (2 - trailing_pct)
            if trail_buffer < new_stop:
                new_stop = round(trail_buffer, 2)
    if pnl_pct <= -max_loss_pct * 100:
        return ("EXIT_ALL", 1.0, f"Max loss {max_loss_pct*100:.0f}% stop", new_stop, best_price)
    hard_level = round(entry_price * (hard_stop_pct if is_long else (2 - hard_stop_pct)), 2)
    if is_long:
        effective_stop = max(new_stop or 0, hard_level)
        if current_price <= effective_stop:
            trigger = "Hard stop" if effective_stop == hard_level else "Trailing stop"
            return ("EXIT_ALL", 1.0, f"{trigger}", new_stop, best_price)
    else:
        effective_stop = min(new_stop or 999999, hard_level)
        if current_price >= effective_stop:
            trigger = "Hard stop" if effective_stop == hard_level else "Trailing stop"
            return ("EXIT_ALL", 1.0, f"{trigger}", new_stop, best_price)
    if is_long and ma7_3d < ma20_3d:
        return ("EXIT_ALL", 1.0, "Trend reversal MA7<MA20", new_stop, best_price)
    if not is_long and ma7_3d > ma20_3d:
        return ("EXIT_ALL", 1.0, "Trend reversal MA7>MA20", new_stop, best_price)
    if is_long and ts_val < -0.3:
        return ("EXIT_ALL", 1.0, f"Score collapse {ts_val:.1f}<-0.3", new_stop, best_price)
    if not is_long and ts_val > 0.3:
        return ("EXIT_ALL", 1.0, f"Score collapse {ts_val:.1f}>+0.3", new_stop, best_price)
    return ("HOLD", 0.0, "", new_stop, best_price)


# ======================= BACKTEST CORE =======================

def backtest_coin_params(
    coin: str, daily_all: list[dict],
    ma_fast: int, ma_slow: int,
    trend_min_long: int, trend_max_short: int,
    vol_min: float,
    max_loss_pct: float, trailing_pct: float, hard_stop_pct: float,
    leverage: float,
    enable_short: bool = True,
) -> dict:
    first_date = datetime.utcfromtimestamp(daily_all[0]["open_time"] / 1000).strftime("%Y-%m-%d")
    last_date = datetime.utcfromtimestamp(daily_all[-1]["open_time"] / 1000).strftime("%Y-%m-%d")

    max_loss_pct = max_loss_pct / 100.0 if max_loss_pct > 1 else max_loss_pct
    max_loss_pct = max_loss_pct  # already in decimal (0.06 = 6%)

    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0,
             "trailing_stop": None, "highest_since_entry": None,
             "short_loss_streak": 0, "short_cooldown_until": None,
             "long_loss_streak": 0, "long_cooldown_until": None}
    trades = []
    equity_curve = [1.0]
    INITIAL_DAYS = MIN_3D_PERIODS * 3

    short_allowed = coin in SHORT_ALLOWED and enable_short

    for day_idx in range(INITIAL_DAYS, len(daily_all)):
        daily_slice = daily_all[:day_idx + 1]
        candles_3d = _aggregate_daily_to_3d(daily_slice)
        if len(candles_3d) < MIN_3D_PERIODS:
            continue

        current_close = daily_slice[-1]["close"]
        closes_3d = [c["close"] for c in candles_3d]
        ma7_3d = (sma(closes_3d, 7)[-1] or closes_3d[-1])
        ma10_3d = (sma(closes_3d, 10)[-1] or closes_3d[-1])
        ma20_3d = (sma(closes_3d, 20)[-1] or closes_3d[-1])
        _, trend_score = evaluate_trend_3d(ma7_3d, ma10_3d, ma20_3d)
        ts_val = trend_strength(trend_score)
        rsi_3d = compute_rsi(closes_3d, 14)

        closes_1d = [c["close"] for c in daily_slice]
        highs_1d = [c["high"] for c in daily_slice]
        lows_1d = [c["low"] for c in daily_slice]
        volumes_1d = [c["volume"] for c in daily_slice]

        ma20_1d_all = sma(closes_1d, 20)
        ma50_1d_all = sma(closes_1d, 50)
        ma20_1d = ma20_1d_all[-1] if ma20_1d_all[-1] is not None else closes_1d[-1]
        ma50_1d = ma50_1d_all[-1] if ma50_1d_all[-1] is not None else closes_1d[-1]
        trend_ma_fast_1d = (sma(closes_1d, ma_fast)[-1] or None)
        trend_ma_slow_1d = sma(closes_1d, ma_slow)[-1] or ma50_1d
        vol_ma20 = (sma(volumes_1d, 20)[-1] or volumes_1d[-1])
        volume_score = compute_volume_score(volumes_1d[-1], vol_ma20)
        rsi_1d = compute_rsi(closes_1d, 14)
        recent_10d_low = min(lows_1d[-10:]) if len(lows_1d) >= 10 else current_close * 0.95
        recent_10d_high = max(highs_1d[-10:]) if len(highs_1d) >= 10 else current_close * 1.05

        dt = daily_slice[-1]["open_time"]
        date_str = datetime.utcfromtimestamp(dt / 1000).strftime("%Y-%m-%d") if isinstance(dt, int) else str(dt)

        prev_pos_state = state["position_state"]
        entry_price = state["entry_price"]
        remaining_size = state["remaining_size"]
        trailing_stop = state.get("trailing_stop")
        highest_since_entry = state.get("highest_since_entry")

        if prev_pos_state == "FLAT":
            _long_allowed = True
            if state.get("long_cooldown_until"):
                _cd = state["long_cooldown_until"]
                if isinstance(_cd, str) and dt and isinstance(dt, int):
                    _cd_ms = int(datetime.fromisoformat(_cd).timestamp() * 1000)
                    if dt < _cd_ms: _long_allowed = False
                elif isinstance(_cd, (int, float)) and isinstance(dt, int):
                    if dt < _cd: _long_allowed = False

            entry_long = entry_condition_long(
                trend_score, rsi_1d, current_close, ma20_1d,
                trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
                trend_min_long, vol_min,
            ) if _long_allowed else False

            _s_allowed = short_allowed
            if _s_allowed and state.get("short_cooldown_until"):
                _cd = state["short_cooldown_until"]
                if isinstance(_cd, str) and dt and isinstance(dt, int):
                    _cd_ms = int(datetime.fromisoformat(_cd).timestamp() * 1000)
                    if dt < _cd_ms: _s_allowed = False
                elif isinstance(_cd, (int, float)) and isinstance(dt, int):
                    if dt < _cd: _s_allowed = False
            entry_short = (
                entry_condition_short(
                    trend_score, rsi_1d, current_close, ma20_1d,
                    trend_ma_slow_1d, trend_ma_fast_1d, volume_score,
                    trend_max_short, vol_min,
                ) if _s_allowed else False
            )

            if entry_long:
                pos_state, action = "LONG_ENTRY_1", "OPEN_LONG_ENTRY_1"
                entry_price = current_close
                remaining_size = 1.0
                trailing_stop = None
                highest_since_entry = None
                trades.append({"date": date_str, "type": "LONG_OPEN", "price": current_close, "size": 1.0, "reason": f"TS={trend_score}"})
            elif entry_short:
                pos_state, action = "SHORT_ENTRY_1", "OPEN_SHORT_ENTRY_1"
                entry_price = current_close
                remaining_size = 1.0
                trailing_stop = None
                highest_since_entry = None
                trades.append({"date": date_str, "type": "SHORT_OPEN", "price": current_close, "size": 1.0, "reason": f"TS={trend_score}"})
            else:
                pos_state, action = "FLAT", "NO_TRADE"

            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size,
                          "trailing_stop": trailing_stop, "highest_since_entry": highest_since_entry})

        else:
            is_long = prev_pos_state.startswith("LONG")
            pnl_pct = ((current_close - entry_price) / entry_price * 100) if is_long and entry_price and entry_price > 0 \
                      else ((entry_price - current_close) / entry_price * 100) if not is_long and entry_price and entry_price > 0 \
                      else 0.0

            exit_action, reduce_pct, exit_reason, new_ts, new_he = exit_condition_v6(
                prev_pos_state, entry_price, current_close, remaining_size,
                ma7_3d, ma20_3d, trend_score, ts_val, rsi_3d,
                trailing_stop, highest_since_entry,
                max_loss_pct, trailing_pct, hard_stop_pct,
            )
            trailing_stop = new_ts
            highest_since_entry = new_he

            if exit_action == "HOLD":
                pos_state = prev_pos_state
                action = "HOLD"
            else:
                if exit_action == "EXIT_ALL":
                    trades.append({"date": date_str, "type": "CLOSE", "price": current_close, "size": remaining_size, "pnl_pct": round(pnl_pct, 2), "reason": exit_reason})
                    if "SHORT" in prev_pos_state:
                        _sls = state.get("short_loss_streak", 0)
                        if pnl_pct > 0:
                            state["short_loss_streak"] = 0; state["short_cooldown_until"] = None
                        else:
                            _sls += 1; state["short_loss_streak"] = _sls
                            if _sls >= SHORT_COOLDOWN_LOSSES:
                                state["short_cooldown_until"] = (datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)).isoformat()
                    else:
                        _lls = state.get("long_loss_streak", 0)
                        if pnl_pct > 0:
                            state["long_loss_streak"] = 0; state["long_cooldown_until"] = None
                        else:
                            _lls += 1; state["long_loss_streak"] = _lls
                            if _lls >= LONG_COOLDOWN_LOSSES:
                                state["long_cooldown_until"] = (datetime.utcfromtimestamp(dt / 1000) + timedelta(days=LONG_COOLDOWN_DAYS)).isoformat()
                    pos_state = "FLAT"
                    remaining_size = 0.0
                    entry_price = None
                    action = "EXIT_LONG" if is_long else "EXIT_SHORT"

            state.update({"position_state": pos_state, "entry_price": entry_price, "remaining_size": remaining_size,
                          "trailing_stop": trailing_stop, "highest_since_entry": highest_since_entry})

        if state["position_state"] != "FLAT" and state["entry_price"] and state["remaining_size"] > 0:
            _il = state["position_state"].startswith("LONG")
            upnl = ((current_close - state["entry_price"]) / state["entry_price"] * 100) if _il else \
                   ((state["entry_price"] - current_close) / state["entry_price"] * 100)
            equity_curve.append(1.0 + upnl / 100 * state["remaining_size"] * leverage)
        else:
            equity_curve.append(1.0)

    return {"coin": coin, "trades": trades, "equity_curve": equity_curve,
            "period": f"{first_date} → {last_date}"}


# ======================= METRICS =======================

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
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd: max_dd = dd
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
        "period": result["period"],
        "message": None,
    }

def portfolio_score(metrics_list: list[dict]) -> float:
    avg_pnl = mean([m["total_pnl_pct"] for m in metrics_list if not m.get("message")])
    avg_pf = mean([m["profit_factor"] for m in metrics_list if not m.get("message") and m["profit_factor"] != float("inf")])
    avg_dd = mean([m["max_drawdown_pct"] for m in metrics_list if not m.get("message")])
    avg_sharpe = mean([m["sharpe_ratio"] for m in metrics_list if not m.get("message")])
    if avg_dd <= 0:
        return avg_pnl * avg_pf * avg_sharpe
    return avg_pnl * avg_pf * avg_sharpe / avg_dd


# ======================= PRINTING =======================

def print_config(label: str, params: dict):
    print(f"  {label}")
    for k, v in params.items():
        print(f"    {k}: {v}")
    print()

def print_comparison(results: list[tuple], top_n: int = 10):
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"  {'Rank':<5} {'Score':>8} {'PnL%':>8} {'WR%':>6} {'PF':>6} {'DD%':>7} {'Sharpe':>7} {'Trades':>7}  Config")
    print(f"  {'─'*5} {'─'*8} {'─'*8} {'─'*6} {'─'*6} {'─'*7} {'─'*7} {'─'*7}  {'─'*30}")
    for i, row in enumerate(results[:top_n]):
        score, pnl, wr, pf, dd, sharpe, nt, cfg_str = row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]
        print(f"  {i+1:<5} {score:>8.2f} {pnl:>+8.2f}% {wr:>5.1f}% {pf:>6.2f} {dd:>6.2f}% {sharpe:>7.2f} {nt:>5d}  {cfg_str}")


# ======================= MAIN =======================

def run_sweep(
    coin_list: list[str],
    params_grid: list[dict],
    period_key: str,
    period_info: dict,
    disable_short: bool = False,
) -> list[tuple]:
    print(f"\n  {'─'*70}")
    print(f"  Period: {period_info['label']} | Coins: {', '.join(coin_list)}")
    print(f"  Combos: {len(params_grid)}")
    print(f"  {'─'*70}")

    all_results = []
    total = len(params_grid)

    for idx, params in enumerate(params_grid):
        ma_fast = params.get("ma_fast", 12)
        ma_slow = params.get("ma_slow", 25)
        t_min_long = params.get("trend_min_long", 1)
        t_max_short = params.get("trend_max_short", -3)
        vol_min = params.get("vol_min", 0.3)
        max_loss = params.get("max_loss_pct", 0.06)
        trail = params.get("trailing_pct", 0.85)
        hard = params.get("hard_stop_pct", 0.78)
        lev = params.get("leverage", 2.5)

        if idx % 5 == 0:
            print(f"    [{idx+1}/{total}] ...", end="\r")

        metrics_list = []
        for coin in coin_list:
            symbol = coin if coin.startswith("1000") else f"{coin}USDT"
            map_key = coin
            try:
                raw = fetch_all_klines(symbol, period_info["limit"], period_info["start_time"])
                if period_info["start_time"]:
                    daily_all = raw[:period_info["limit"]]
                else:
                    daily_all = raw[-period_info["limit"]:]
                result = backtest_coin_params(
                    coin, daily_all,
                    ma_fast, ma_slow,
                    t_min_long, t_max_short, vol_min,
                    max_loss, trail, hard, lev,
                    enable_short=not disable_short,
                )
                metrics = compute_metrics(result)
                metrics_list.append(metrics)
            except Exception as e:
                metrics_list.append({"coin": coin, "message": str(e), "total_pnl_pct": 0, "profit_factor": 0, "max_drawdown_pct": 0, "sharpe_ratio": 0, "total_trades": 0})

        valid = [m for m in metrics_list if not m.get("message")]
        if valid:
            total_pnl = sum(m["total_pnl_pct"] for m in valid)
            avg_wr = mean([m["win_rate_pct"] for m in valid])
            avg_pf = mean([m["profit_factor"] for m in valid if m["profit_factor"] != float("inf")])
            avg_dd = mean([m["max_drawdown_pct"] for m in valid])
            avg_sharpe = mean([m["sharpe_ratio"] for m in valid])
            total_nt = sum(m["total_trades"] for m in valid)
            score_val = total_pnl * avg_pf * avg_sharpe / (avg_dd + 1)
            cfg_str = f"MA{ma_fast}_{ma_slow}_T{t_min_long}_{t_max_short}_V{vol_min}_L{lev}_SL{max_loss}_TR{trail}_HS{hard}"
            all_results.append((score_val, total_pnl, avg_wr, avg_pf, avg_dd, avg_sharpe, total_nt, cfg_str, valid, params))

    all_results.sort(key=lambda x: x[0], reverse=True)
    print(f"    [{total}/{total}] Done.")

    top_n = min(15, len(all_results))
    print_comparison(all_results, top_n)
    return all_results


def phase1_core(period_key: str, period_info: dict, coin_list: list[str]):
    """Core sweep: MA pairs × entry thresholds × volume score."""
    print(f"\n{'='*70}")
    print(f"  PHASE 1: CORE PARAMETERS")
    print(f"  MA pairs × Entry thresholds × Volume score")
    print(f"{'='*70}")

    ma_pairs = [(10, 20), (8, 15), (12, 25)]
    trend_mins_long = [0, 1, 2]
    trend_maxs_short = [-3, -2]
    vol_mins = [0.2, 0.3]

    params_grid = []
    for ma_f, ma_s in ma_pairs:
        for tml in trend_mins_long:
            for tms in trend_maxs_short:
                for vm in vol_mins:
                    params_grid.append({
                        "ma_fast": ma_f, "ma_slow": ma_s,
                        "trend_min_long": tml, "trend_max_short": tms,
                        "vol_min": vm,
                        "max_loss_pct": 0.06, "trailing_pct": 0.85, "hard_stop_pct": 0.78,
                        "leverage": 2.5,
                    })

    return run_sweep(coin_list, params_grid, period_key, period_info)


def phase2_stops(period_key: str, period_info: dict, coin_list: list[str],
                 best_core: dict):
    """Sweep stop params around best core config."""
    print(f"\n{'='*70}")
    print(f"  PHASE 2: STOP PARAMETER TUNING")
    print(f"  Base core config: MA{best_core['ma_fast']}_{best_core['ma_slow']} "
          f"T{best_core['trend_min_long']}_{best_core['trend_max_short']} "
          f"V{best_core['vol_min']}")
    print(f"{'='*70}")

    max_losses = [0.04, 0.05, 0.06, 0.07]
    trail_pcts = [0.80, 0.85, 0.90]
    hard_stops = [0.75, 0.78, 0.82]
    leverages = [2.0, 2.5, 3.0, 3.5, 4.0]

    params_grid = []
    for ml in max_losses:
        for tr in trail_pcts:
            for hs in hard_stops:
                params_grid.append({
                    **best_core,
                    "max_loss_pct": ml, "trailing_pct": tr, "hard_stop_pct": hs,
                    "leverage": 2.5,
                })
    for lev in leverages:
        params_grid.append({
            **best_core,
            "max_loss_pct": 0.06, "trailing_pct": 0.85, "hard_stop_pct": 0.78,
            "leverage": lev,
        })

    return run_sweep(coin_list, params_grid, period_key, period_info)


def phase3_coins(period_key: str, period_info: dict,
                 best_params: dict, coin_lists: list[tuple[str, list[str]]]):
    """Compare coin lists."""
    print(f"\n{'='*70}")
    print(f"  PHASE 3: COIN LIST COMPARISON")
    print(f"  Params: MA{best_params['ma_fast']}_{best_params['ma_slow']} "
          f"T{best_params['trend_min_long']}_{best_params['trend_max_short']} "
          f"L{best_params['leverage']}")
    print(f"{'='*70}")

    results = []
    for label, clist in coin_lists:
        print(f"\n  Coins: {label} → {', '.join(clist)}")
        raw = run_sweep(clist, [best_params], period_key, period_info)
        if raw:
            results.append((label, raw[0]))

    print(f"\n  {'─'*50}")
    print(f"  COIN LIST COMPARISON")
    print(f"  {'─'*50}")
    print(f"  {'List':<20} {'PnL%':>8} {'WR%':>6} {'PF':>6} {'DD%':>7} {'Sharpe':>7} {'Trades':>7}")
    print(f"  {'─'*20} {'─'*8} {'─'*6} {'─'*6} {'─'*7} {'─'*7} {'─'*7}")
    for label, (score, pnl, wr, pf, dd, sharpe, nt, cfg_str, valid_m, _) in results:
        print(f"  {label:<20} {pnl:>+8.2f}% {wr:>5.1f}% {pf:>6.2f} {dd:>6.2f}% {sharpe:>7.2f} {nt:>5d}")
    return results


def main():
    print(f"{'='*70}")
    print(f"  V6 STRATEGY PARAMETER SWEEP")
    print(f"  Sweeping MA pairs, entry thresholds, stops, coins, leverage")
    print(f"  on 2021–2023 and 2024–2026 data")
    print(f"{'='*70}")

    CORE_COINS = ["ETH", "BNB", "PAXG", "TRX", "SOL"]
    COIN_SOL = ("SOL (current)", ["ETH", "BNB", "PAXG", "TRX", "SOL"])
    COIN_BTC = ("SOL→BTC", ["ETH", "BNB", "PAXG", "TRX", "BTC"])

    all_best = []

    for pkey, pinfo in PERIODS.items():
        print(f"\n{'#'*70}")
        print(f"# PERIOD: {pinfo['label']}")
        print(f"{'#'*70}")

        # Phase 1
        print(f"\n{'='*70}")
        print(f"  PHASE 1: CORE PARAMETER SWEEP")
        print(f"  MA pairs × Entry thresholds × Volume score")
        print(f"{'='*70}")
        p1 = phase1_core(pkey, pinfo, CORE_COINS)
        if not p1:
            print("  No valid results in Phase 1. Skipping.")
            continue
        best_p1_cfg = p1[0][9]  # params dict

        # Phase 2: Stops
        print(f"\n{'='*70}")
        print(f"  PHASE 2: STOP & LEVERAGE SWEEP")
        print(f"  Best core: MA{best_p1_cfg['ma_fast']}_{best_p1_cfg['ma_slow']} "
              f"T{best_p1_cfg['trend_min_long']}_{best_p1_cfg['trend_max_short']}")
        print(f"{'='*70}")
        p2 = phase2_stops(pkey, pinfo, CORE_COINS, best_p1_cfg)
        best_p2_cfg = p2[0][9] if p2 else best_p1_cfg

        # Phase 3: Coins
        print(f"\n{'='*70}")
        print(f"  PHASE 3: COIN LIST COMPARISON")
        print(f"  Best params: MA{best_p2_cfg['ma_fast']}_{best_p2_cfg['ma_slow']} "
              f"L{best_p2_cfg['leverage']} SL{best_p2_cfg['max_loss_pct']}")
        print(f"{'='*70}")
        p3 = phase3_coins(pkey, pinfo, best_p2_cfg, [COIN_SOL, COIN_BTC])
        if p3:
            best_label = max(p3, key=lambda x: x[1][1])
            all_best.append((pkey, pinfo["label"], best_p2_cfg, best_label[0], best_label[1]))

    # Final summary
    print(f"\n\n{'='*70}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*70}")
    for pkey, plabel, cfg, coin_label, (score, pnl, wr, pf, dd, sharpe, nt, _, _, _) in all_best:
        print(f"\n  {plabel}")
        print(f"  {'─'*50}")
        print(f"  Best config:")
        for k, v in cfg.items():
            print(f"    {k}: {v}")
        print(f"  Coin list: {coin_label}")
        print(f"  Performance:")
        print(f"    PnL={pnl:+.2f}% | WR={wr:.1f}% | PF={pf:.2f} | DD={dd:.2f}% | Sharpe={sharpe:.2f} | Trades={nt}")


if __name__ == "__main__":
    main()
