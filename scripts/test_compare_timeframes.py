#!/usr/bin/env python3
"""Compare CAGR: 1D-3D baseline vs 12h-36h (SF=1.5 vs SF=2) on 3-coin portfolio."""
import sys, os, json
from datetime import datetime, timedelta
from statistics import mean
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, evaluate_exit_v6, _entry_score_v7_long,
    compute_atr, get_coin_profile, get_position_size,
    get_allocation_multiplier, get_trailing_multiplier,
    SHORT_ALLOWED, SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

COINS = ["ETH", "BNB", "TRX"]
SYMBOL_MAP = {c: f"{c}USDT" for c in COINS}
BINANCE_MAX_LIMIT = 1000
START = int(datetime(2021, 1, 1).timestamp() * 1000)
LIMIT = 4000
CAPITAL = 10000

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
_cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        _cache = json.load(f)

_fetch_cache_1d = {}

def fetch(symbol, interval, limit=LIMIT, st=None):
    if interval == "12h":
        key = f"{symbol}_{limit}_{st}"
        if key in _cache: return _cache[key]
    else:
        key = f"{symbol}_{interval}_{limit}_{st}"
        if key in _fetch_cache_1d: return _fetch_cache_1d[key]

    candles, remaining, cur = [], limit, st
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        params = {"symbol": symbol, "interval": interval, "limit": take + 50}
        if cur: params["startTime"] = int(cur)
        r = req_lib.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
        r.raise_for_status()
        batch = []
        for k in r.json():
            batch.append({"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
                          "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])})
        batch.sort(key=lambda x: x["open_time"])
        if len(batch) <= 1: break
        candles.extend(batch)
        remaining -= len(batch)
        cur = batch[-1]["open_time"] + 1
        if len(candles) >= limit: break
    candles = candles[:limit]
    if interval != "12h":
        _fetch_cache_1d[key] = candles
    return candles

def aggr(candles, n):
    r = []
    for i in range(0, len(candles) - n + 1, n):
        b = candles[i:i + n]
        r.append({"open_time": b[0]["open_time"], "open": b[0]["open"],
            "high": max(d["high"] for d in b), "low": min(d["low"] for d in b),
            "close": b[-1]["close"], "volume": sum(d["volume"] for d in b)})
    return r

def backtest(coin, candles, mode):
    """mode: '1d3d' | '12h36h_sf15' | '12h36h_sf2'"""
    if mode == "1d3d":
        sf = 1
        candles_exec = candles["1d"]
        candles_trend = candles["3d"]
        trend_f, trend_m, trend_s = 7, 10, 20
        exec_fast_period, exec_slow_period = 12, 25
        exec_ma20_period = 20
        exec_ma50_period = 50
        exec_ma200_period = 200
        rsi_period = 14
        atr_period = 14
        vol_ma_period = 20
        vol_5d_len = 6
        vol_5d_div = 5
        recent_bars = 10
        atr_range_start = 13
        init = 25 * 3
    elif mode == "12h36h_sf15":
        sf = 1.5
        candles_exec = candles["12h"]
        candles_trend = aggr(candles_exec, 3)
        trend_f, trend_m, trend_s = int(7 * sf), int(10 * sf), int(20 * sf)
        exec_fast_period = int(12 * sf)
        exec_slow_period = int(25 * sf)
        exec_ma20_period = int(20 * sf)
        exec_ma50_period = int(50 * sf)
        exec_ma200_period = int(200 * sf)
        rsi_period = int(14 * sf)
        atr_period = int(14 * sf)
        vol_ma_period = int(20 * sf)
        vol_5d_len = int(6 * sf)
        vol_5d_div = int(5 * sf)
        recent_bars = int(10 * sf)
        atr_range_start = int(14 * sf) - 1
        init = 25 * 3
    else:  # 12h36h_sf2
        sf = 2
        candles_exec = candles["12h"]
        candles_trend = aggr(candles_exec, 3)
        trend_f, trend_m, trend_s = int(7 * sf), int(10 * sf), int(20 * sf)
        exec_fast_period = int(12 * sf)
        exec_slow_period = int(25 * sf)
        exec_ma20_period = int(20 * sf)
        exec_ma50_period = int(50 * sf)
        exec_ma200_period = int(200 * sf)
        rsi_period = int(14 * sf)
        atr_period = int(14 * sf)
        vol_ma_period = int(20 * sf)
        vol_5d_len = int(6 * sf)
        vol_5d_div = int(5 * sf)
        recent_bars = int(10 * sf)
        atr_range_start = int(14 * sf) - 1
        init = 25 * 3

    profile = dict(get_coin_profile(coin))
    if coin == "TRX": profile["position_size_base"] = 0.12

    state = {"position_state": "FLAT", "entry_price": None, "margin_pct": 0.0,
             "trailing_stop": None, "highest_since_entry": None,
             "short_loss_streak": 0, "short_cooldown_until": None,
             "long_loss_streak": 0, "long_cooldown_until": None,
             "remaining_size": 1.0, "tp_stage": 0}
    trades, eq = [], 1.0
    equity_curve = []
    da = candles_exec

    for idx in range(init, len(da)):
        ds = da[:idx + 1]
        c_t = candles_trend[:idx // 3 + 1] if mode.startswith("12h") else candles_trend[:idx + 1]
        if len(c_t) < max(trend_f, trend_m, trend_s): continue
        cc = ds[-1]["close"]
        cl_trend = [c["close"] for c in c_t]
        m_f = sma(cl_trend, trend_f)[-1] or cl_trend[-1]
        m_m = sma(cl_trend, trend_m)[-1] or cl_trend[-1]
        m_sl = sma(cl_trend, trend_s)[-1] or cl_trend[-1]
        tl, ts = evaluate_trend_3d(m_f, m_m, m_sl)
        tsv = trend_strength(ts)
        rsi_trend = compute_rsi(cl_trend, 14)

        c1 = [c["close"] for c in ds]; h1 = [c["high"] for c in ds]
        l1 = [c["low"] for c in ds]; v1 = [c["volume"] for c in ds]
        e_f = (sma(c1, exec_fast_period)[-1] or c1[-1])
        e_m = (sma(c1, exec_slow_period)[-1] or c1[-1])
        e_s = (sma(c1, exec_ma20_period)[-1] or c1[-1])
        ma7 = (sma(c1, int(7 * sf))[-1] or c1[-1])
        ma10 = (sma(c1, int(10 * sf))[-1] or c1[-1])
        ma50 = (sma(c1, exec_ma50_period)[-1] or c1[-1])
        ma200 = (sma(c1, exec_ma200_period)[-1] or None)
        vm = sma(v1, vol_ma_period)[-1] or v1[-1]
        v5a = sum(v1[-vol_5d_len:-1]) / vol_5d_div if len(v1) >= vol_5d_len else v1[-1]
        vs_ = compute_volume_score(v1[-1], vm)
        rsi_exec = compute_rsi(c1, rsi_period)
        atr_val = compute_atr(ds, atr_period) if len(ds) >= atr_period + 1 else 0
        r10l = min(l1[-recent_bars:]) if len(l1) >= recent_bars else cc * .95
        r10h = max(h1[-recent_bars:]) if len(h1) >= recent_bars else cc * 1.05
        dt = ds[-1]["open_time"]
        pps, ep = state["position_state"], state["entry_price"]

        if pps == "FLAT":
            lok = True
            if state.get("long_cooldown_until"):
                cd = state["long_cooldown_until"]
                cd_ms = int(cd.timestamp() * 1000) if hasattr(cd, "timestamp") else int(cd)
                if dt < cd_ms: lok = False
            el = compute_entry_v6_long(ts, rsi_exec, cc, e_s, e_m, e_f, vs_,
                trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
                rsi_max=profile.get("rsi_max_long", 90),
                ma7_1d=ma7, ma200_1d=ma200, last_volume=v1[-1], vol_5d_avg=v5a,
                use_ma200_filter=False, use_pullback_filter=False,
                use_volume_expan=False,
                min_entry_score=profile.get("min_entry_score", 0)) if lok else False
            sok = coin in SHORT_ALLOWED
            if sok and state.get("short_cooldown_until"):
                cd = state["short_cooldown_until"]
                cd_ms = int(cd.timestamp() * 1000) if hasattr(cd, "timestamp") else int(cd)
                if dt < cd_ms: sok = False
            es = compute_entry_v6_short(ts, rsi_exec, cc, e_s, e_m, e_f, vs_,
                trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
                rsi_min=profile.get("rsi_min_short", 10)) if sok else False
            ps_, act = resolve_action_v6(ts, el, es, pps)
            if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                sc = _entry_score_v7_long(ts, cc, ma7, ma10, e_s, ma200, e_f, e_m, vs_, v1[-1], v5a, rsi_exec)
                sz = get_position_size(ts, coin) * get_allocation_multiplier(sc)
                if act.startswith("OPEN_SHORT"): sz *= profile.get("short_size_mult", .5)
                is_sh = act.startswith("OPEN_SHORT")
                state.update({"position_state": ps_, "entry_price": cc, "margin_pct": sz,
                              "entry_trend": ts, "trailing_stop": None, "highest_since_entry": cc,
                              "is_short": is_sh, "entry_score": sc,
                              "remaining_size": 1.0, "tp_stage": 0})
        else:
            is_sp = state.get("is_short", False); is_lp = not is_sp
            mp = state.get("margin_pct", .034); et = state.get("entry_trend", 0)
            eml = profile.get("short_max_loss_pct", profile["max_loss_pct"]) if is_sp else profile["max_loss_pct"]
            tm = get_trailing_multiplier(et)
            eft = (profile.get("short_trailing_pct", profile["trailing_pct"]) if is_sp else profile["trailing_pct"]) * tm
            pnl = 0.
            if ep and ep > 0: pnl = ((cc - ep) / ep * 100) if is_lp else ((ep - cc) / ep * 100)
            rem_sz = state.get("remaining_size", 1.0); tp_s = state.get("tp_stage", 0)
            ml_val = profile["max_loss_pct"] * 100
            tp_sched = [(0.5, 0.15), (1.0, 0.15), (1.5, 0.15), (2.0, 0.25)]
            for si, (mult, cpct) in enumerate(tp_sched):
                if tp_s <= si and pnl >= ml_val * mult:
                    cf = cpct * rem_sz
                    eq *= (1 + pnl * cf * mp * profile["leverage"] / 100)
                    rem_sz -= cf; state["remaining_size"] = rem_sz; state["tp_stage"] = si + 1
                    break
            if state.get("tp_stage", 0) >= 4: eft = 0.97
            ea, rp, er, nts, nhe = evaluate_exit_v6(pps, ep, cc, rem_sz, m_f, m_sl, ts, tsv, rsi_trend,
                r10l, r10h, state.get("trailing_stop"), state.get("highest_since_entry"),
                max_loss_pct=eml, trailing_pct=eft, initial_stop_pct=profile["initial_stop_pct"],
                hard_stop_pct=profile["hard_stop_pct"], atr_1d=atr_val,
                trail_atr_mult=profile.get("trail_atr_mult", 0),
                use_profit_locking=profile.get("use_profit_locking", False))
            if ea != "HOLD":
                is_se = state.get("is_short", False)
                pn = ((cc - state["entry_price"]) / state["entry_price"] * 100) if not is_se else ((state["entry_price"] - cc) / state["entry_price"] * 100)
                rem = state.get("remaining_size", 1.0)
                eq *= (1 + pn * mp * rem * profile["leverage"] / 100)
                trades.append({"type": "CLOSE", "pnl_pct": pn, "size": mp * rem})
                if is_se:
                    sls = state.get("short_loss_streak", 0)
                    if pn > 0: state["short_loss_streak"] = 0; state["short_cooldown_until"] = None
                    else:
                        sls += 1; state["short_loss_streak"] = sls
                        if sls >= SHORT_COOLDOWN_LOSSES: state["short_cooldown_until"] = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)
                else:
                    lls = state.get("long_loss_streak", 0)
                    if pn > 0: state["long_loss_streak"] = 0; state["long_cooldown_until"] = None
                    else:
                        lls += 1; state["long_loss_streak"] = lls
                        if lls >= LONG_COOLDOWN_LOSSES: state["long_cooldown_until"] = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=LONG_COOLDOWN_DAYS)
                pps, ep = "FLAT", None
            state.update({"position_state": pps, "entry_price": ep, "trailing_stop": nts, "highest_since_entry": nhe})

        if state["position_state"] != "FLAT" and state.get("entry_price"):
            is_l = not state.get("is_short", False)
            upnl = ((cc - state["entry_price"]) / state["entry_price"] * 100) if is_l else ((state["entry_price"] - cc) / state["entry_price"] * 100)
            rem = state.get("remaining_size", 1.0)
            equity_curve.append(eq * (1 + upnl / 100 * state.get("margin_pct", 0.034) * rem * profile["leverage"]))
        else:
            equity_curve.append(eq)

    closes = [t for t in trades if t["type"] == "CLOSE"]
    if not closes: return None
    pnls = [t["pnl_pct"] for t in closes]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    tp = sum(pnls); wr = len(wins) / len(pnls) * 100 if pnls else 0
    aw = mean(wins) if wins else 0; al = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")
    peak = equity_curve[0] if equity_curve else eq; md = 0
    for v in equity_curve:
        if v > peak: peak = v
        dd_val = (peak - v) / peak * 100
        if dd_val > md: md = dd_val
    bars_per_day = 1 if mode == "1d3d" else 2
    years = len(equity_curve) / bars_per_day / 365 if equity_curve else 1
    cagr = ((eq ** (1 / years) - 1) * 100) if years > 0 and eq > 0 else 0
    final = eq * CAPITAL
    return {"coin": coin, "eq": eq, "cagr": cagr, "dd": md, "pf": pf, "trades": len(closes),
            "pnl": tp, "wr": wr, "aw": aw, "al": al, "final": final}

MODES = {
    "1D-3D (baseline)": "1d3d",
    "12h-36h SF=1.5": "12h36h_sf15",
    "12h-36h SF=2": "12h36h_sf2",
}

print("=" * 110)
print("  TIMEFRAME COMPARISON: 1D-3D vs 12h-36h (SF=1.5 vs SF=2)")
print("  3 coins: ETH, BNB, TRX | $10K/coin | TRX@12% | Partial TP | min_entry_score=50")
print("=" * 110)

all_results = {}
for mode_name, mode_key in MODES.items():
    print(f"\n{'='*110}")
    print(f"  {mode_name}")
    print(f"  {'─'*105}")
    
    if mode_key == "1d3d":
        print(f"  Trend 3D: MA7-10-20 | Exec 1D: MA12-25 | RSI14 | ATR14")
    elif mode_key == "12h36h_sf15":
        print(f"  Trend 36h: MA10-15-30 | Exec 12h: MA18-37 | RSI21 | ATR21 | SF=1.5")
    else:
        print(f"  Trend 36h: MA14-20-40 | Exec 12h: MA24-50 | RSI28 | ATR28 | SF=2")
    print(f"  {'Coin':<6} {'T':>4} {'PnL':>8} {'CAGR':>7} {'DD':>7} {'PF':>6} {'WR':>6} {'AW':>7} {'AL':>7} {'Final$':>10}")
    print(f"  {'─'*85}")

    mode_results = {}
    for coin in COINS:
        symbol = SYMBOL_MAP[coin]
        if mode_key == "1d3d":
            print(f"    Fetching {coin} (1D+3D)...", end=" ", flush=True)
            try:
                da_1d = fetch(symbol, "1d", 2000, START)
                da_3d = fetch(symbol, "3d", 700, START)
            except Exception as e:
                print(f"FETCH ERROR: {e}")
                continue
            candles = {"1d": da_1d, "3d": da_3d}
            print(f"1D={len(da_1d)} 3D={len(da_3d)}")
        else:
            da_12h = fetch(symbol, "12h", LIMIT, START)
            candles = {"12h": da_12h}
            print(f"12h={len(da_12h)} candles")

        r = backtest(coin, candles, mode_key)
        if r:
            mode_results[coin] = r
            print(f"  {coin:<6} {r['trades']:>4} {r['pnl']:+7.1f}% {r['cagr']:+6.1f}% {r['dd']:+6.1f}% {r['pf']:+5.2f} {r['wr']:+5.0f}% {r['aw']:+6.2f}% {r['al']:+6.2f}% ${r['final']:>9,.0f}")
        else:
            print(f"  {coin:<6} No trades")

    all_results[mode_name] = mode_results

    if mode_results:
        avg_c = mean(r["cagr"] for r in mode_results.values())
        avg_d = mean(r["dd"] for r in mode_results.values())
        total_f = sum(r["final"] for r in mode_results.values())
        print(f"  {'─'*85}")
        print(f"  PORTFOLIO | Avg CAGR={avg_c:+.1f}% | Avg DD={avg_d:.1f}% | ${len(COINS)*CAPITAL:,}→${total_f:,.0f}")

print(f"\n{'='*110}")
print("  COMPARISON MATRIX")
print(f"  {'Mode':<25} {'ETH':>10} {'BNB':>10} {'TRX':>10} {'Avg CAGR':>10} {'Avg DD':>10} {'$30K→':>15}")
print(f"  {'─'*90}")
for mode_name in MODES:
    r = all_results.get(mode_name, {})
    if len(r) < 3: continue
    avg_c = mean(v["cagr"] for v in r.values())
    avg_d = mean(v["dd"] for v in r.values())
    total_f = sum(v["final"] for v in r.values())
    coins_str = " ".join(f"{r.get(c,{}).get('cagr',0):+9.1f}%" for c in COINS)
    print(f"  {mode_name:<25} {coins_str} {avg_c:+9.1f}% {avg_d:+9.1f}% ${total_f:>13,.0f}")

best = max(all_results.items(), key=lambda x: mean(v["cagr"] for v in x[1].values()) if len(x[1]) >= 3 else -999)
print(f"\n  WINNER: {best[0]} — Avg CAGR={mean(v['cagr'] for v in best[1].values()):+.1f}%")
