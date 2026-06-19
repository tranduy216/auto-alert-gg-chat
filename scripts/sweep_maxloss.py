#!/usr/bin/env python3
"""Sweep max_loss_pct: 6%, 8%, 10%, 12%, 14%, 16%, 18%, 20% — 2024-2026."""
import sys, os
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
    COINS, SYMBOL_MAP, SHORT_ALLOWED,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

START = int(datetime(2024, 1, 1).timestamp() * 1000)
LIMIT = 1000
BINANCE_MAX_LIMIT = 1000

_cache = {}
def fetch(symbol, limit=LIMIT, st=None):
    key = (symbol, limit, st)
    if key in _cache: return _cache[key]
    candles, remaining, cur = [], limit, st
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        params = {"symbol": symbol, "interval": "1d", "limit": take + 50}
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
    _cache[key] = candles[:limit]
    return _cache[key]

def aggr(daily, n=3):
    r = []
    for i in range(0, len(daily) - n + 1, n):
        b = daily[i:i + n]
        r.append({"open_time": b[0]["open_time"], "open": b[0]["open"],
            "high": max(d["high"] for d in b), "low": min(d["low"] for d in b),
            "close": b[-1]["close"], "volume": sum(d["volume"] for d in b)})
    return r

def bt(coin, ml):
    profile = dict(get_coin_profile(coin))
    profile["max_loss_pct"] = ml
    profile["short_max_loss_pct"] = min(ml, profile.get("short_max_loss_pct", 0.04))

    state = {"position_state": "FLAT", "entry_price": None, "margin_pct": 0.0,
             "trailing_stop": None, "highest_since_entry": None,
             "short_loss_streak": 0, "short_cooldown_until": None,
             "long_loss_streak": 0, "long_cooldown_until": None}
    trades, eq, da = [], 1.0, fetch(SYMBOL_MAP[coin])
    eqs = [eq]
    INITIAL = 75

    for idx in range(INITIAL, len(da)):
        ds = da[:idx + 1]
        c3 = aggr(ds, 3)
        if len(c3) < 25: continue
        cc = ds[-1]["close"]
        cl3 = [c["close"] for c in c3]
        m_f = sma(cl3, 7)[-1] or cl3[-1]
        m_m = sma(cl3, 10)[-1] or cl3[-1]
        m_s = sma(cl3, 20)[-1] or cl3[-1]
        tl, ts = evaluate_trend_3d(m_f, m_m, m_s)
        tsv = trend_strength(ts)
        rsi3 = compute_rsi(cl3, 14)

        c1 = [c["close"] for c in ds]; h1 = [c["high"] for c in ds]
        l1 = [c["low"] for c in ds]; v1 = [c["volume"] for c in ds]
        ma20_1d = (sma(c1, 20)[-1] or c1[-1])
        ma7_1d = (sma(c1, 7)[-1] or c1[-1])
        ma10_1d = (sma(c1, 10)[-1] or c1[-1])
        ma50_1d = (sma(c1, 50)[-1] or c1[-1])
        ma200_1d = (sma(c1, 200)[-1] or None)
        tf = (sma(c1, 12)[-1] or None)
        ms = sma(c1, 25)[-1] or ma50_1d
        vm = sma(v1, 20)[-1] or v1[-1]
        v5a = sum(v1[-6:-1]) / 5 if len(v1) >= 6 else v1[-1]
        vs_ = compute_volume_score(v1[-1], vm)
        rsi1 = compute_rsi(c1, 14)
        atr1 = compute_atr(ds, 14) if len(ds) >= 15 else 0
        r10l = min(l1[-10:]) if len(l1) >= 10 else cc * .95
        r10h = max(h1[-10:]) if len(h1) >= 10 else cc * 1.05
        dt = ds[-1]["open_time"]
        pps, ep = state["position_state"], state["entry_price"]

        if pps == "FLAT":
            lok = True
            if state.get("long_cooldown_until"):
                cd = state["long_cooldown_until"]
                cd_ms = int(cd.timestamp() * 1000) if hasattr(cd, "timestamp") else int(cd)
                if dt < cd_ms: lok = False
            el = compute_entry_v6_long(ts, rsi1, cc, ma20_1d, ms, tf, vs_,
                trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
                rsi_max=profile.get("rsi_max_long", 90),
                ma7_1d=ma7_1d, ma200_1d=ma200_1d, last_volume=v1[-1], vol_5d_avg=v5a,
                use_ma200_filter=False, use_pullback_filter=False,
                use_volume_expan=False, min_entry_score=profile.get("min_entry_score", 0)) if lok else False
            sok = coin in SHORT_ALLOWED
            if sok and state.get("short_cooldown_until"):
                cd = state["short_cooldown_until"]
                cd_ms = int(cd.timestamp() * 1000) if hasattr(cd, "timestamp") else int(cd)
                if dt < cd_ms: sok = False
            es = compute_entry_v6_short(ts, rsi1, cc, ma20_1d, ms, tf, vs_,
                trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
                rsi_min=profile.get("rsi_min_short", 10)) if sok else False
            ps_, act = resolve_action_v6(ts, el, es, pps)
            if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                sc = _entry_score_v7_long(ts, cc, ma7_1d, ma10_1d, ma20_1d, ma200_1d, tf, ms, vs_, v1[-1], v5a, rsi1)
                sz = get_position_size(ts, coin) * get_allocation_multiplier(sc)
                if act.startswith("OPEN_SHORT"): sz *= profile.get("short_size_mult", .5)
                is_sh = act.startswith("OPEN_SHORT")
                state.update({"position_state": ps_, "entry_price": cc, "margin_pct": sz,
                              "entry_trend": ts, "trailing_stop": None, "highest_since_entry": cc,
                              "is_short": is_sh, "entry_score": sc})
                trades.append({"type": "LONG_OPEN" if not is_sh else "SHORT_OPEN", "size": sz})
        else:
            is_sp = state.get("is_short", False); is_lp = not is_sp
            mp = state.get("margin_pct", .034); et = state.get("entry_trend", 0)
            eml = profile.get("short_max_loss_pct", ml) if is_sp else ml
            tm = get_trailing_multiplier(et)
            eft = (profile.get("short_trailing_pct", profile["trailing_pct"]) if is_sp else profile["trailing_pct"]) * tm
            pnl = 0.
            if ep and ep > 0: pnl = ((cc - ep) / ep * 100) if is_lp else ((ep - cc) / ep * 100)
            ea, rp, er, nts, nhe = evaluate_exit_v6(pps, ep, cc, 1., m_f, m_s, ts, tsv, rsi3,
                r10l, r10h, state.get("trailing_stop"), state.get("highest_since_entry"),
                max_loss_pct=eml, trailing_pct=eft, initial_stop_pct=profile["initial_stop_pct"],
                hard_stop_pct=profile["hard_stop_pct"], atr_1d=atr1,
                trail_atr_mult=profile.get("trail_atr_mult", 0),
                use_profit_locking=profile.get("use_profit_locking", False))
            if ea != "HOLD":
                is_se = state.get("is_short", False)
                pn = ((cc - state["entry_price"]) / state["entry_price"] * 100) if not is_se else ((state["entry_price"] - cc) / state["entry_price"] * 100)
                eq *= (1 + pn * mp * profile["leverage"] / 100)
                trades.append({"type": "CLOSE", "pnl_pct": pn, "size": mp})
                if is_se:
                    sls = state.get("short_loss_streak", 0)
                    if pn > 0: state["short_loss_streak"] = 0; state["short_cooldown_until"] = None
                    else:
                        sls += 1; state["short_loss_streak"] = sls
                        if sls >= SHORT_COOLDOWN_LOSSES:
                            state["short_cooldown_until"] = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)
                else:
                    lls = state.get("long_loss_streak", 0)
                    if pn > 0: state["long_loss_streak"] = 0; state["long_cooldown_until"] = None
                    else:
                        lls += 1; state["long_loss_streak"] = lls
                        if lls >= LONG_COOLDOWN_LOSSES:
                            state["long_cooldown_until"] = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=LONG_COOLDOWN_DAYS)
                pps, ep = "FLAT", None
            state.update({"position_state": pps, "entry_price": ep, "trailing_stop": nts, "highest_since_entry": nhe})

        if state["position_state"] != "FLAT" and state.get("entry_price"):
            is_l = not state.get("is_short", False)
            upnl = ((cc - state["entry_price"]) / state["entry_price"] * 100) if is_l else ((state["entry_price"] - cc) / state["entry_price"] * 100)
            eqs.append(eq * (1 + upnl / 100 * state.get("margin_pct", .034) * profile["leverage"]))
        else:
            eqs.append(eq)

    closes = [t for t in trades if t["type"] == "CLOSE"]
    if not closes: return None
    pnls = [t["pnl_pct"] for t in closes]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    tp = sum(pnls); wr = len(wins) / len(closes) * 100
    aw = mean(wins) if wins else 0; al = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")
    peak = eqs[0]; md = 0
    for v in eqs:
        if v > peak: peak = v
        dd_val = (peak - v) / peak * 100
        if dd_val > md: md = dd_val
    years = len(eqs) / 365
    cagr = ((eq / eqs[0]) ** (1 / years) - 1) * 100 if years > 0 and eqs[0] > 0 else 0
    return {"trades": len(closes), "pnl": tp, "cagr": cagr, "dd": md, "pf": pf, "wr": wr,
            "aw": aw, "al": al}

print("=" * 85)
print("  MAX_LOSS_PCT SWEEP — 2024-2026")
print("=" * 85)

for ml in [0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20]:
    print(f"\n{'─'*85}")
    print(f"  Max Loss: {ml*100:.0f}%")
    print(f"  {'Coin':<6} {'T':>3} {'PnL':>8} {'CAGR':>7} {'DD':>7} {'PF':>6} {'WR':>6} {'AW':>7} {'AL':>7}")
    results = {}
    for coin in COINS:
        r = bt(coin, ml)
        if r:
            results[coin] = r
            print(f"  {coin:<6} {r['trades']:>3} {r['pnl']:+7.1f}% {r['cagr']:+6.1f}% {r['dd']:+6.1f}% {r['pf']:+5.2f} {r['wr']:+5.0f}% {r['aw']:+6.2f}% {r['al']:+6.2f}%")
        else:
            print(f"  {coin:<6} No trades")
    if results:
        avg_c = mean(r["cagr"] for r in results.values())
        avg_d = mean(r["dd"] for r in results.values())
        sum_t = sum(r["trades"] for r in results.values())
        print(f"  {'─'*70}")
        print(f"  AVG    {sum_t:>3} {'':>8} {avg_c:+6.1f}% {avg_d:+6.1f}%")
