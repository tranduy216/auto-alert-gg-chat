#!/usr/bin/env python3
"""Baseline backtest: 12h-36h SF=1.5, yearly CAGR per coin."""
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
    SF, TREND_MA_FAST, TREND_MA_MID, TREND_MA_SLOW,
    EXEC_MA_FAST, EXEC_MA_MID, EXEC_MA_SLOW,
)

COINS = ["ETH", "BNB", "TRX"]
SYMBOL_MAP = {c: f"{c}USDT" for c in COINS}
START = int(datetime(2021, 1, 1).timestamp() * 1000)
LIMIT = 4000; CAPITAL = 10000

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
_cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        _cache = json.load(f)

def fetch(symbol, limit=LIMIT, st=None):
    key = f"{symbol}_{limit}_{st}"
    return _cache.get(key, [])

def aggr(candles, n=3):
    r = []
    for i in range(0, len(candles) - n + 1, n):
        b = candles[i:i + n]
        r.append({"open_time": b[0]["open_time"], "open": b[0]["open"],
            "high": max(d["high"] for d in b), "low": min(d["low"] for d in b),
            "close": b[-1]["close"], "volume": sum(d["volume"] for d in b)})
    return r

print(f"{'='*100}")
print(f"  BASELINE BACKTEST — 12h-36h SF={SF} | Trend MA{TREND_MA_FAST}/{TREND_MA_MID}/{TREND_MA_SLOW} | Exec MA{EXEC_MA_FAST}/{EXEC_MA_MID}/{EXEC_MA_SLOW}")
print(f"  3 coins: ETH BNB TRX | $10K/coin | TRX@12% | Partial TP | min_entry_score=50")
print(f"{'='*100}")

all_results = {}
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
    INITIAL = 25 * 3

    # Yearly tracking
    yearly_eq = {}  # year -> eq at year-end
    yearly_start = {}  # year -> eq at year-start

    for idx in range(INITIAL, len(da)):
        ds = da[:idx + 1]; c_trend = aggr(ds, 3)
        if len(c_trend) < 25: continue
        cc = ds[-1]["close"]
        cl3 = [c["close"] for c in c_trend]
        m_f = sma(cl3, TREND_MA_FAST)[-1] or cl3[-1]
        m_m = sma(cl3, TREND_MA_MID)[-1] or cl3[-1]
        m_sl = sma(cl3, TREND_MA_SLOW)[-1] or cl3[-1]
        tl, ts = evaluate_trend_3d(m_f, m_m, m_sl)
        tsv = trend_strength(ts); rsi_t = compute_rsi(cl3, 14)

        c1 = [c["close"] for c in ds]; h1 = [c["high"] for c in ds]
        l1 = [c["low"] for c in ds]; v1 = [c["volume"] for c in ds]
        e_f = (sma(c1, EXEC_MA_FAST)[-1] or c1[-1])
        e_m = (sma(c1, EXEC_MA_MID)[-1] or c1[-1])
        e_s = (sma(c1, EXEC_MA_SLOW)[-1] or c1[-1])
        ma7 = (sma(c1, int(7 * SF))[-1] or c1[-1])
        ma10 = (sma(c1, int(10 * SF))[-1] or c1[-1])
        ma50 = (sma(c1, int(50 * SF))[-1] or c1[-1])
        ma200 = (sma(c1, int(200 * SF))[-1] or None)
        vm = sma(v1, int(20 * SF))[-1] or v1[-1]
        v5a = sum(v1[-(int(6 * SF)):-1]) / (int(5 * SF)) if len(v1) >= int(6 * SF) else v1[-1]
        vs_ = compute_volume_score(v1[-1], vm)
        rsi1 = compute_rsi(c1, int(14 * SF))
        atr_val = compute_atr(ds, int(14 * SF)) if len(ds) >= int(15 * SF) else 0
        r10l = min(l1[-(int(10 * SF)):]) if len(l1) >= int(10 * SF) else cc * .95
        r10h = max(h1[-(int(10 * SF)):]) if len(h1) >= int(10 * SF) else cc * 1.05
        dt = ds[-1]["open_time"]
        pps, ep = state["position_state"], state["entry_price"]

        # Track year boundaries
        date = datetime.utcfromtimestamp(dt / 1000)
        yr = date.year
        if yr not in yearly_start:
            yearly_start[yr] = eq

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
            ea, rp, er, nts, nhe = evaluate_exit_v6(pps, ep, cc, rem_sz, m_f, m_sl, ts, tsv, rsi_t,
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
            yearly_eq[yr] = eq

    closes = [t for t in trades if t["type"] == "CLOSE"]
    if not closes:
        print(f"  {coin:6s} | No trades")
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
    bars_per_day = 2
    years_total = len(equity_curve) / bars_per_day / 365 if equity_curve else 1
    cagr = ((eq ** (1 / years_total) - 1) * 100) if years_total > 0 and eq > 0 else 0
    final = eq * CAPITAL

    all_results[coin] = {"cagr": cagr, "dd": md, "pf": pf, "trades": len(closes),
                         "pnl": tp, "wr": wr, "aw": aw, "al": al, "final": final,
                         "yearly_eq": yearly_eq, "yearly_start": yearly_start}

    print(f"  {coin:6s} | {len(closes):>3d} trades | PnL={tp:+7.1f}% | CAGR={cagr:+5.1f}% | DD={md:+5.1f}% | PF={pf:.2f} | WR={wr:.0f}% | \${CAPITAL:,}->\${final:,.0f}")

# Yearly CAGR table
print(f"\n{'='*100}")
print(f"  YEARLY CAGR BREAKDOWN")
print(f"  {'Coin':<6}", end="")
for yr in range(2021, 2026):
    print(f" {'$'+str(yr):>12}", end=" ")
print(f" {'CAGR':>8}  {'DD':>8}")
print(f"  {'─'*95}")

for coin in COINS:
    r = all_results.get(coin)
    if not r: continue
    y_eq = r["yearly_eq"]
    y_start = r["yearly_start"]

    # Print yearly values
    print(f"  {coin:<6}", end="")
    prev_eq = 1.0
    for yr in range(2021, 2026):
        eq_val = y_eq.get(yr, prev_eq)
        if yr == 2021:
            print(f" ${eq_val*CAPITAL:>11,.0f}", end=" ")
        else:
            # CAGR for this year
            yr_cagr = ((eq_val / prev_eq) - 1) * 100
            print(f" ${eq_val*CAPITAL:>11,.0f}", end=" ")
        prev_eq = eq_val
    print(f" {r['cagr']:+7.1f}% {r['dd']:+7.1f}%")

# Yearly CAGR per coin
print(f"\n{'='*100}")
print(f"  YEARLY CAGR (%)")
print(f"  {'Coin':<6}", end="")
for yr in range(2021, 2026):
    print(f" {yr:>8}", end=" ")
print(f" {'5Y':>8}")
print(f"  {'─'*60}")

for coin in COINS:
    r = all_results.get(coin)
    if not r: continue
    y_eq = r["yearly_eq"]
    print(f"  {coin:<6}", end="")
    prev_eq = 1.0
    for yr in range(2021, 2026):
        eq_val = y_eq.get(yr, prev_eq)
        yr_cagr = ((eq_val / prev_eq) - 1) * 100
        print(f" {yr_cagr:+7.1f}%", end="")
        prev_eq = eq_val
    print(f" {r['cagr']:+7.1f}%")

# Portfolio summary
print(f"\n{'='*100}")
print(f"  PORTFOLIO SUMMARY")
total_final = sum(r["final"] for r in all_results.values())
avg_cagr = mean(r["cagr"] for r in all_results.values())
avg_dd = mean(r["dd"] for r in all_results.values())
print(f"  {len(COINS)} coins | Avg CAGR={avg_cagr:+.1f}% | Avg DD={avg_dd:.1f}% | \${len(COINS)*CAPITAL:,}->\${total_final:,.0f}")
