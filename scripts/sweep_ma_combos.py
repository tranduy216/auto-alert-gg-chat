#!/usr/bin/env python3
"""Sweep 12h MA combos for execution engine + MA50/150 trend. Analyze CAGR limit."""
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

SF = 2
BINANCE_MAX_LIMIT = 1000
START = int(datetime(2021, 1, 1).timestamp() * 1000); LIMIT = 4000
CAPITAL = 10000

# Trend engine: MA50, MA150 on 36h
TREND_FAST = 50; TREND_MID = 50; TREND_SLOW = 150

COMBOS = {
    "MA10-20-50": (10, 20, 50),
    "MA15-30-75": (15, 30, 75),
    "MA20-40-100": (20, 40, 100),
}

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
_cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        _cache = json.load(f)
    print(f"Loaded cache: {len(_cache)} symbols")

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

print("=" * 95)
print("  MA COMBO SWEEP — 12h Execution + 36h Trend(MA50-150)")
print("  TRX margin reduced to 12% (was 16%)")
print("=" * 95)

all_combo_results = {}

for combo_name, (ma_f, ma_m, ma_s) in COMBOS.items():
    print(f"\n{'─'*95}")
    print(f"  EXECUTION: {combo_name}  |  TREND: MA{TREND_FAST}-MA{TREND_SLOW}")
    print(f"  {'Coin':<6} {'Base':>7} {'T':>4} {'PnL':>8} {'CAGR':>7} {'DD':>7} {'PF':>6} {'WR':>6} {'AW':>7} {'AL':>7} {'Final$':>10}")
    print(f"  {'─'*90}")

    combo_results = {}
    for coin in COINS:
        profile = dict(get_coin_profile(coin))
        if coin == "TRX":
            profile["position_size_base"] = 0.12  # reduced from 16%

        state = {"position_state": "FLAT", "entry_price": None, "margin_pct": 0.0,
                 "trailing_stop": None, "highest_since_entry": None,
                 "short_loss_streak": 0, "short_cooldown_until": None,
                 "long_loss_streak": 0, "long_cooldown_until": None,
                 "remaining_size": 1.0, "tp_stage": 0}
        trades, eq = [], 1.0
        equity_curve = []
        da = fetch(SYMBOL_MAP[coin], LIMIT, START)
        INITIAL = 25 * 3

        for idx in range(INITIAL, len(da)):
            ds = da[:idx + 1]; c_trend = aggr(ds, 3)
            if len(c_trend) < 25: continue
            cc = ds[-1]["close"]
            cl3 = [c["close"] for c in c_trend]
            m_f_t = sma(cl3, TREND_FAST)[-1] or cl3[-1]
            m_s_t = sma(cl3, TREND_SLOW)[-1] or cl3[-1]
            # 2-MA trend: MA50 > MA150 = BULLISH(3), MA50 < MA150 = BEARISH(-3)
            # Use middle MA = (fast+slow)/2 to get 3-level trend via evaluate_trend_3d
            m_mid_t = (m_f_t + m_s_t) / 2
            tl, ts = evaluate_trend_3d(m_f_t, m_mid_t, m_s_t)
            tsv = trend_strength(ts); rsi3 = compute_rsi(cl3, 14)

            c1 = [c["close"] for c in ds]; h1 = [c["high"] for c in ds]
            l1 = [c["low"] for c in ds]; v1 = [c["volume"] for c in ds]
            exec_f = (sma(c1, ma_f)[-1] or c1[-1])
            exec_m = (sma(c1, ma_m)[-1] or c1[-1])
            exec_s = (sma(c1, ma_s)[-1] or c1[-1])
            ma7 = (sma(c1, 7*SF)[-1] or c1[-1])
            ma10 = (sma(c1, 10*SF)[-1] or c1[-1])
            ma50 = (sma(c1, 50*SF)[-1] or c1[-1])
            ma200 = (sma(c1, 200*SF)[-1] or None)
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
                el = compute_entry_v6_long(ts, rsi1, cc, exec_s, exec_m, exec_f, vs_,
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
                es = compute_entry_v6_short(ts, rsi1, cc, exec_s, exec_m, exec_f, vs_,
                    trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
                    rsi_min=profile.get("rsi_min_short", 10)) if sok else False
                ps_, act = resolve_action_v6(ts, el, es, pps)
                if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                    sc = _entry_score_v7_long(ts, cc, ma7, ma10, exec_s, ma200, exec_f, exec_m, vs_, v1[-1], v5a, rsi1)
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

                # Partial TP
                rem_sz = state.get("remaining_size", 1.0)
                tp_s = state.get("tp_stage", 0)
                ml_val = profile["max_loss_pct"] * 100
                tp_sched = [(0.5, 0.15), (1.0, 0.15), (1.5, 0.15), (2.0, 0.25)]
                for si, (mult, cpct) in enumerate(tp_sched):
                    if tp_s <= si and pnl >= ml_val * mult:
                        cf = cpct * rem_sz
                        eq *= (1 + pnl * cf * mp * profile["leverage"] / 100)
                        trades.append({"type": "PARTIAL_EXIT", "pnl_pct": round(pnl, 2)})
                        rem_sz -= cf
                        state["remaining_size"] = rem_sz; state["tp_stage"] = si + 1
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
                rem = state.get("remaining_size", 1.0)
                equity_curve.append(eq * (1 + upnl / 100 * state.get("margin_pct", 0.034) * rem * profile["leverage"]))
            else:
                equity_curve.append(eq)

        closes = [t for t in trades if t["type"] == "CLOSE"]
        if not closes: 
            print(f"  {coin:<6} {'N/A':>7} {'0':>4} {'N/A':>8}")
            continue
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
        years = len(equity_curve) / (24/12) / 365 if equity_curve else 1
        cagr = ((eq ** (1 / years) - 1) * 100) if years > 0 and eq > 0 else 0
        final = eq * CAPITAL
        base = profile.get("position_size_base", 0.034)
        print(f"  {coin:<6} {base*100:6.1f}% {len(closes):>4} {tp:+7.1f}% {cagr:+6.1f}% {md:+6.1f}% {pf:+5.2f} {wr:+5.0f}% {aw:+6.2f}% {al:+6.2f}% ${final:>9,.0f}")
        combo_results[coin] = {"cagr": cagr, "dd": md, "pf": pf, "trades": len(closes), "final": final}

    if combo_results:
        avg_c = mean(r["cagr"] for r in combo_results.values())
        avg_d = mean(r["dd"] for r in combo_results.values())
        total_f = sum(r["final"] for r in combo_results.values())
        print(f"  {'─'*90}")
        print(f"  PORTFOLIO | Avg CAGR={avg_c:+.1f}% | Avg DD={avg_d:.1f}% | ${len(COINS)*CAPITAL:,}→${total_f:,.0f}")
        all_combo_results[combo_name] = {"avg_cagr": avg_c, "avg_dd": avg_d, "total": total_f, "coins": combo_results}

print(f"\n{'='*95}")
print("  SUMMARY: MA COMBO COMPARISON")
print(f"  {'Combo':<18} {'Avg CAGR':>10} {'Avg DD':>10} {'$40K→':>15} {'BTC':>8} {'ETH':>8} {'BNB':>8} {'TRX':>8}")
print(f"  {'─'*90}")
for name, r in all_combo_results.items():
    coins_str = " ".join(f"{r['coins'].get(c,{}).get('cagr',0):+6.1f}%" for c in COINS)
    print(f"  {name:<18} {r['avg_cagr']:+9.1f}% {r['avg_dd']:+9.1f}% ${r['total']:>13,.0f}  {coins_str}")

print(f"\n{'='*95}")
print("  CAGR ANALYSIS — Why not 20%?")
print(f"{'='*95}")
print("""
  1. MARGIN DEPLOYMENT: Only ~17.5% avg margin × 2.5x = ~44% exposure per coin.
     Each trade returns fraction of equity, need EXTREME per-trade PnL for high CAGR.

  2. DRAWDOEN PENALTY: DD eats into compounding. A 40% DD means:
     Recovery = 1/(1-0.4) = 1.67x needed. DD directly steals CAGR.

  3. PARTIAL TP TRADE-OFF: Locking 15% at 3.5%, 7% etc means winners are cut.
     For TRX (+200% runs), partial TP caps the upside severely.

  4. ENTRY FREQUENCY: Strict trend≥2 filters reduce trades → less compounding.
     BTC 56 trades in 5.5 years = ~10/year. With 13.7% CAGR, avg trade adds 0.25%/yr.

  5. LEVERAGE: 2.5x is conservative. 3x would add ~20% to CAGR at cost of +25% DD.

  RECOMMENDATIONS to push CAGR toward 20%:
  - Raise leverage to 3x (but DD will increase)
  - Increase entry frequency (relax trend filter to ≥1 for BTC/ETH)
  - Remove partial TP (let winners run full)
  - Increase margin per coin (but DD will be unsustainable)
""")
