#!/usr/bin/env python3
"""Sweep trend MA combos on 36h, keep execution MA15-30-75 on 12h."""
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
    COINS, SYMBOL_MAP, SHORT_ALLOWED,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

SF = 2; BINANCE_MAX_LIMIT = 1000
START = int(datetime(2021, 1, 1).timestamp() * 1000); LIMIT = 4000; CAPITAL = 10000
EXEC_MA = (15, 30, 75)

TREND_COMBOS = [
    ("MA7-15-50", 7, (7, 15, 50)),
    ("MA10-25-50", 10, (10, 25, 50)),
    ("MA15-40-75", 15, (15, 40, 75)),
    ("MA20-50-100", 20, (20, 50, 100)),
    ("MA25-60-120", 25, (25, 60, 120)),
]

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
_cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f: _cache = json.load(f)

def fetch(symbol, limit=LIMIT, st=None):
    key = f"{symbol}_{limit}_{st}"
    if key in _cache: return _cache[key]
    candles, remaining, cur = [], limit, st
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        params = {"symbol": symbol, "interval": "12h", "limit": take + 50}
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
    with open(CACHE_FILE, "w") as f: json.dump(_cache, f)
    return _cache[key]

def aggr(candles, n=3):
    r = []
    for i in range(0, len(candles) - n + 1, n):
        b = candles[i:i + n]
        r.append({"open_time": b[0]["open_time"], "open": b[0]["open"],
            "high": max(d["high"] for d in b), "low": min(d["low"] for d in b),
            "close": b[-1]["close"], "volume": sum(d["volume"] for d in b)})
    return r

print("=" * 105)
print(f"  TREND MA SWEEP on 36h | Execution MA={EXEC_MA[0]}-{EXEC_MA[1]}-{EXEC_MA[2]} on 12h")
print(f"  TRX@12%, BTC@20%, ETH@18%, BNB@16% | Partial TP | min_entry_score=50")
print("=" * 105)

all_results = {}

for name, min_ma, (t_f, t_m, t_s) in TREND_COMBOS:
    # Need at least `min_ma`×3 12h candles for trend initialization
    needed = min_ma * 3
    INITIAL = max(25 * 3, needed)
    
    print(f"\n{'─'*105}")
    print(f"  TREND: {name} (MA{t_f}-{t_m}-{t_s}) | Warmup={INITIAL} candles")
    print(f"  {'Coin':<6} {'Base':>7} {'T':>4} {'PnL':>8} {'CAGR':>7} {'DD':>7} {'PF':>6} {'WR':>6} {'AW':>7} {'AL':>7} {'Final$':>10}")
    print(f"  {'─'*95}")

    combo_results = {}
    for coin in COINS:
        profile = dict(get_coin_profile(coin))
        if coin == "TRX": profile["position_size_base"] = 0.12

        state = {"position_state": "FLAT", "entry_price": None, "margin_pct": 0.0,
                 "trailing_stop": None, "highest_since_entry": None,
                 "short_loss_streak": 0, "short_cooldown_until": None,
                 "long_loss_streak": 0, "long_cooldown_until": None,
                 "remaining_size": 1.0, "tp_stage": 0}
        trades, eq = [], 1.0
        equity_curve = []
        da = fetch(SYMBOL_MAP[coin], LIMIT, START)

        for idx in range(INITIAL, len(da)):
            ds = da[:idx + 1]; c_trend = aggr(ds, 3)
            if len(c_trend) < min_ma: continue
            cc = ds[-1]["close"]
            cl3 = [c["close"] for c in c_trend]
            m_f_t = sma(cl3, t_f)[-1] or cl3[-1]
            m_m_t = sma(cl3, t_m)[-1] or cl3[-1]
            m_s_t = sma(cl3, t_s)[-1] or cl3[-1]
            tl, ts = evaluate_trend_3d(m_f_t, m_m_t, m_s_t)
            tsv = trend_strength(ts); rsi3 = compute_rsi(cl3, 14)

            c1 = [c["close"] for c in ds]; h1 = [c["high"] for c in ds]
            l1 = [c["low"] for c in ds]; v1 = [c["volume"] for c in ds]
            e_f = (sma(c1, EXEC_MA[0])[-1] or c1[-1]); e_m = (sma(c1, EXEC_MA[1])[-1] or c1[-1])
            e_s = (sma(c1, EXEC_MA[2])[-1] or c1[-1])
            ma7 = (sma(c1, 7*SF)[-1] or c1[-1]); ma10 = (sma(c1, 10*SF)[-1] or c1[-1])
            ma50 = (sma(c1, 50*SF)[-1] or c1[-1]); ma200 = (sma(c1, 200*SF)[-1] or None)
            vm = sma(v1, 20*SF)[-1] or v1[-1]
            v5a = sum(v1[-(6*SF):-1]) / (5*SF) if len(v1) >= 6*SF else v1[-1]
            vs_ = compute_volume_score(v1[-1], vm); rsi1 = compute_rsi(c1, 14*SF)
            atr1 = compute_atr(ds, 14*SF) if len(ds) >= 15*SF else 0
            r10l = min(l1[-(10*SF):]) if len(l1) >= 10*SF else cc * .95
            r10h = max(h1[-(10*SF):]) if len(h1) >= 10*SF else cc * 1.05
            dt = ds[-1]["open_time"]
            pps, ep = state["position_state"], state["entry_price"]

            if pps == "FLAT":
                lok = True
                if state.get("long_cooldown_until"):
                    cd = state["long_cooldown_until"]
                    cd_ms = int(cd.timestamp() * 1000) if hasattr(cd, "timestamp") else int(cd)
                    if dt < cd_ms: lok = False
                el = compute_entry_v6_long(ts, rsi1, cc, e_s, e_m, e_f, vs_,
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
                es = compute_entry_v6_short(ts, rsi1, cc, e_s, e_m, e_f, vs_,
                    trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
                    rsi_min=profile.get("rsi_min_short", 10)) if sok else False
                ps_, act = resolve_action_v6(ts, el, es, pps)
                if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                    sc = _entry_score_v7_long(ts, cc, ma7, ma10, e_s, ma200, e_f, e_m, vs_, v1[-1], v5a, rsi1)
                    sz = get_position_size(ts, coin) * get_allocation_multiplier(sc)
                    if act.startswith("OPEN_SHORT"): sz *= profile.get("short_size_mult", .5)
                    is_sh = act.startswith("OPEN_SHORT")
                    state.update({"position_state": ps_, "entry_price": cc, "margin_pct": sz,
                                  "entry_trend": ts, "trailing_stop": None, "highest_since_entry": cc,
                                  "is_short": is_sh, "entry_score": sc,
                                  "remaining_size": 1.0, "tp_stage": 0})
                    trades.append({"type": "LONG_OPEN" if not is_sh else "SHORT_OPEN", "size": sz})
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
                ea, rp, er, nts, nhe = evaluate_exit_v6(pps, ep, cc, rem_sz, m_f_t, m_s_t, ts, tsv, rsi3,
                    r10l, r10h, state.get("trailing_stop"), state.get("highest_since_entry"),
                    max_loss_pct=eml, trailing_pct=eft, initial_stop_pct=profile["initial_stop_pct"],
                    hard_stop_pct=profile["hard_stop_pct"], atr_1d=atr1,
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
                        else: sls += 1; state["short_loss_streak"] = sls
                        if sls >= SHORT_COOLDOWN_LOSSES: state["short_cooldown_until"] = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)
                    else:
                        lls = state.get("long_loss_streak", 0)
                        if pn > 0: state["long_loss_streak"] = 0; state["long_cooldown_until"] = None
                        else: lls += 1; state["long_loss_streak"] = lls
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
        if not closes: print(f"  {coin:<6} {'N/A':>7} {'0':>4}"); continue
        pnls = [t["pnl_pct"] for t in closes]; wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
        tp = sum(pnls); wr = len(wins) / len(pnls) * 100 if pnls else 0
        aw = mean(wins) if wins else 0; al = mean(losses) if losses else 0
        pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")
        peak = equity_curve[0] if equity_curve else eq; md = 0
        for v in equity_curve:
            if v > peak: peak = v
            dd_val = (peak - v) / peak * 100
            if dd_val > md: md = dd_val
        years = len(equity_curve) / (24/12) / 365 if equity_curve else 1
        cagr = ((eq ** (1 / years) - 1) * 100) if years > 0 and eq > 0 else 0
        final = eq * CAPITAL; base = profile.get("position_size_base", 0.034)
        print(f"  {coin:<6} {base*100:6.1f}% {len(closes):>4} {tp:+7.1f}% {cagr:+6.1f}% {md:+6.1f}% {pf:+5.2f} {wr:+5.0f}% {aw:+6.2f}% {al:+6.2f}% ${final:>9,.0f}")
        combo_results[coin] = {"cagr": cagr, "dd": md, "pf": pf, "trades": len(closes), "final": final}

    if combo_results:
        avg_c = mean(r["cagr"] for r in combo_results.values())
        avg_d = mean(r["dd"] for r in combo_results.values())
        total_f = sum(r["final"] for r in combo_results.values())
        print(f"  {'─'*95}")
        print(f"  PORTFOLIO | Avg CAGR={avg_c:+.1f}% | Avg DD={avg_d:.1f}% | ${len(COINS)*CAPITAL:,}→${total_f:,.0f}")
        all_results[name] = {"cagr": avg_c, "dd": avg_d, "total": total_f, "coins": combo_results}

print(f"\n{'='*105}")
print("  RANKING: Trend MA Combinations")
print(f"  {'Rank':<6} {'Trend MA':<18} {'Avg CAGR':>10} {'Avg DD':>10} {'$40K→':>15} {'BTC':>8} {'ETH':>8} {'BNB':>8} {'TRX':>8}")
print(f"  {'─'*100}")
for rank, (name, r) in enumerate(sorted(all_results.items(), key=lambda x: -x[1]["cagr"]), 1):
    coins_str = " ".join(f"{r['coins'].get(c,{}).get('cagr',0):+6.1f}%" for c in COINS)
    print(f"  {rank:<6} {name:<18} {r['cagr']:+9.1f}% {r['dd']:+9.1f}% ${r['total']:>13,.0f}  {coins_str}")
