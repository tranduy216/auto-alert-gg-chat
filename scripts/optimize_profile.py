#!/usr/bin/env python3
"""Optimize per-coin config: leverage, SL, capital multiplier. SL rate < 20%, max CAGR."""
import sys, os, json
from datetime import datetime, timedelta
from statistics import mean
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_trading import (
    sma, evaluate_trend_3d, compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long,
    get_coin_profile, SHORT_ALLOWED, compute_rsi,
)

SF = 1.5; BASE = 10000
COINS = ["ETH", "BNB", "TRX"]
SYMBOL = {c: f"{c}USDT" for c in COINS}
TP = [(7, 0.07), (12, 0.11), (20, 0.20), (30, 0.27)]
ENTRY_MIN = 65
CD_BARS = {"ETH": 0, "BNB": 0, "TRX": 3}
TRAIL_RATE = {"ETH": 0.035, "BNB": 0.065, "TRX": 0.065}
ENTRY_STRONG = {"ETH": 0.09, "BNB": 0.07, "TRX": 0.07}
ENTRY_WEAK = {"ETH": 0.07, "BNB": 0.055, "TRX": 0.055}

INITIAL = 75
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
with open(CACHE) as f: _cache = json.load(f)

def fetch(s):
    return _cache.get(f"{s}_4000_1609434000000", [])

def aggr(c, n=3):
    r = []
    for i in range(0, len(c) - n + 1, n):
        b = c[i:i + n]
        r.append({"close": b[-1]["close"]})
    return r

LEVERAGES = [2.0, 2.5, 3.0, 3.5]
SL_ROIS = [3, 5, 7, 9, 12]
CAP_MULTS = [1.8, 1.9, 2.0]
MAX_POS_PCT = 0.65  # max position value as % of total capital

print(f"{'='*95}")
print(f"  Per-Coin Optimization: SL rate < 20%, max CAGR")
print(f"  Leverage: {LEVERAGES} | SL ROI: {SL_ROIS}% | Cap: {CAP_MULTS}x")
print(f"  Max position/coin = {MAX_POS_PCT*100:.0f}% of total capital (incl. leverage)")
print(f"{'='*95}")

for coin in COINS:
    print(f"\n  {coin} — scanning {len(LEVERAGES)*len(SL_ROIS)*len(CAP_MULTS)} combos...")
    prof = dict(get_coin_profile(coin))
    da = fetch(SYMBOL[coin])
    tr_rate = TRAIL_RATE[coin]
    cd = CD_BARS[coin]
    e_strong = ENTRY_STRONG[coin]
    e_weak = ENTRY_WEAK[coin]

    best = {"cagr": -999, "slr": 999, "lev": 0, "sl": 0, "cap": 0}
    results = []

    for lev in LEVERAGES:
        max_margin_sum = MAX_POS_PCT / lev  # max total margin_pct sum

        for sl_roi_val in SL_ROIS:
            for cap_mult in CAP_MULTS:
                entries = []
                eq = 1.0
                curve = []
                trades_log = []
                last_entry_idx = -999
                tot_cap_fixed = BASE * cap_mult

                for idx in range(INITIAL, len(da)):
                    ds = da[:idx + 1]
                    ct = aggr(ds, 3)
                    if len(ct) < 25: continue
                    cc = ds[-1]["close"]
                    cl = [c["close"] for c in ct]
                    mf = sma(cl, 10)[-1] or cl[-1]
                    mm = sma(cl, 15)[-1] or cl[-1]
                    ms = sma(cl, 30)[-1] or cl[-1]
                    _, ts = evaluate_trend_3d(mf, mm, ms)
                    c1 = [c["close"] for c in ds]
                    v1 = [c["volume"] for c in ds]
                    ef = sma(c1, 18)[-1] or c1[-1]
                    em = sma(c1, 37)[-1] or c1[-1]
                    es = sma(c1, 30)[-1] or c1[-1]
                    ma7 = sma(c1, int(7 * SF))[-1] or c1[-1]
                    ma10 = sma(c1, int(10 * SF))[-1] or c1[-1]
                    ma200 = sma(c1, int(200 * SF))[-1] or None
                    vm2 = sma(v1, int(20 * SF))[-1] or v1[-1]
                    v5a = sum(v1[-(int(6 * SF)):-1]) / (int(5 * SF)) if len(v1) >= int(6 * SF) else v1[-1]
                    vs = compute_volume_score(v1[-1], vm2)
                    rsi1 = compute_rsi(c1, int(14 * SF))

                    new_entries = []
                    for ent in entries:
                        ep = ent["ep"]; mp = ent["mp"]; tp_s = ent["tp"]
                        rem2 = ent["rem"]; hi = ent["hi"]; tstop = ent["tstop"]
                        roi = ((cc - ep) / ep * 100) * mp * tot_cap_fixed * lev / BASE
                        if cc > hi: hi = cc; ent["hi"] = hi
                        rm = False
                        if roi <= -sl_roi_val:
                            eq += roi * rem2 / 100
                            trades_log.append({"t": "SL", "r": roi})
                            rm = True
                        elif tp_s < len(TP):
                            trg, cpct = TP[tp_s]
                            if roi >= trg:
                                cf = cpct * rem2
                                eq += roi * cf / 100
                                rem2 -= cf
                                ent["rem"] = rem2
                                ent["tp"] = tp_s + 1
                                trades_log.append({"t": "TP", "r": roi})
                                if ent["tp"] >= len(TP):
                                    ent["tstop"] = cc * (1 - tr_rate)
                        if tp_s >= len(TP) and not rm:
                            if tstop is None: tstop = cc * (1 - tr_rate)
                            tstop = max(tstop, hi * (1 - tr_rate))
                            ent["tstop"] = tstop
                            if cc <= tstop:
                                eq += roi * rem2 / 100
                                trades_log.append({"t": "TRAIL", "r": roi})
                                rm = True
                        if not rm: new_entries.append(ent)
                    entries = new_entries

                    dep = sum(e["mp"] for e in entries)
                    can = dep < max_margin_sum and (idx - last_entry_idx >= cd)
                    if can:
                        el = compute_entry_v6_long(ts, rsi1, cc, es, em, ef, vs,
                            trend_min=prof["trend_min_long"], vol_min=prof["vol_min"],
                            rsi_max=prof.get("rsi_max_long", 90), ma7_1d=ma7, ma200_1d=ma200,
                            last_volume=v1[-1], vol_5d_avg=v5a,
                            use_ma200_filter=False, use_pullback_filter=False,
                            use_volume_expan=False, min_entry_score=ENTRY_MIN)
                        es_ = compute_entry_v6_short(ts, rsi1, cc, es, em, ef, vs,
                            trend_max=prof["trend_max_short"], vol_min=prof["vol_min"],
                            rsi_min=prof.get("rsi_min_short", 10)) if coin in SHORT_ALLOWED else False
                        ps_, act = resolve_action_v6(ts, el, es_, "FLAT")
                        if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                            sc = _entry_score_v7_long(ts, cc, ma7, ma10, es, ma200, ef, em, vs, v1[-1], v5a, rsi1)
                            mp = e_strong if sc >= ENTRY_MIN else e_weak
                            if dep + mp <= max_margin_sum + 0.001:
                                entries.append({"ep": cc, "mp": mp, "tp": 0, "rem": 1.0, "hi": cc, "tstop": None})
                                last_entry_idx = idx

                    ureal = sum(((cc - e["ep"]) / e["ep"] * 100) * e["mp"] * tot_cap_fixed * lev / BASE * e["rem"] / 100 for e in entries)
                    curve.append(eq + ureal)

                slc = sum(1 for t in trades_log if t["t"] == "SL")
                tpc = sum(1 for t in trades_log if t["t"] in ("TP", "TRAIL"))
                tot = slc + tpc
                slr = slc / tot * 100 if tot else 100

                if slr >= 20:
                    continue

                peak = curve[0] if curve else eq
                md = 0
                for v in curve:
                    if v > peak: peak = v
                    dd = (peak - v) / peak * 100
                    if dd > md: md = dd
                years = len(curve) / 2 / 365 if curve else 1
                teq = curve[-1] if curve else eq
                cagr = ((teq ** (1 / years) - 1) * 100) if years > 0 and teq > 0 else 0

                results.append({"lev": lev, "sl": sl_roi_val, "cap": cap_mult, "cagr": cagr, "dd": md, "slr": slr, "tot": tot, "teq": teq})
                if cagr > best["cagr"]:
                    best = {"cagr": cagr, "slr": slr, "lev": lev, "sl": sl_roi_val, "cap": cap_mult, "dd": md, "tot": tot, "teq": teq}

    # Show top 5
    ranked = sorted(results, key=lambda x: -x["cagr"])
    print(f"  Top 5 (SL rate < 20%):")
    print(f"  {'Rank':<5} {'Lev':>5} {'SL%':>5} {'Cap':>5} {'CAGR':>8} {'DD':>7} {'SLr':>6} {'Evts':>5} {'$10K→':>10}")
    for i, r in enumerate(ranked[:5]):
        print(f"  {i+1:<5} {r['lev']:>4.1f}x {r['sl']:>4.0f}% {r['cap']:>4.1f}x {r['cagr']:+7.1f}% {r['dd']:+6.1f}% {r['slr']:+5.0f}% {r['tot']:>5} ${r['teq']*BASE:>9,.0f}")

    print(f"\n  BEST → Lev={best['lev']}x SL={best['sl']}% Cap={best['cap']}x"
          f" | CAGR={best['cagr']:+.1f}% SLr={best['slr']:.0f}% DD={best['dd']:.1f}%"
          f" | ${BASE:,}→${best['teq']*BASE:,.0f}")
