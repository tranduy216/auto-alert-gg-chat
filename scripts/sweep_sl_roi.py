#!/usr/bin/env python3
"""Sweep SL ROI to find 50-50 TP:SL ratio."""
import sys, os, json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long, compute_atr,
    get_coin_profile, SHORT_ALLOWED,
    SF, TREND_MA_FAST, TREND_MA_MID, TREND_MA_SLOW,
    EXEC_MA_FAST, EXEC_MA_MID, EXEC_MA_SLOW,
)

BASE = 10000; TOTAL = BASE * 1.8
COINS = ["ETH", "BNB", "TRX"]; SYMBOL = {c: f"{c}USDT" for c in COINS}
LOW = {"ETH"}
def lev(c): return 3.0 if c in LOW else 2.5
def trail(c): return 0.035 if c in LOW else 0.065
def esz(c, strong): return (0.09 if strong else 0.07) if c in LOW else (0.07 if strong else 0.055)
TP = [(7, 0.07), (12, 0.11), (20, 0.20), (30, 0.27)]

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
with open(CACHE) as f: _cache = json.load(f)
def fetch(s): return _cache.get(f"{s}_4000_1609434000000", [])
def aggr(c, n=3):
    r = []
    for i in range(0, len(c) - n + 1, n):
        b = c[i:i + n]; r.append({"close": b[-1]["close"]})
    return r

def roi_of(ep, cp, mp, lv):
    return ((cp - ep) / ep * 100) * mp * TOTAL * lv / BASE

def bt(coin, sl_roi):
    prof = dict(get_coin_profile(coin)); lv = lev(coin); trr = trail(coin)
    entries = []; eq = 1.0; curve = []; trades = []
    da = fetch(SYMBOL[coin]); INITIAL = 75
    for idx in range(INITIAL, len(da)):
        ds = da[:idx + 1]; ct = aggr(ds, 3)
        if len(ct) < 25: continue
        cc = ds[-1]["close"]; cl = [c["close"] for c in ct]
        mf = sma(cl, 10)[-1] or cl[-1]; mm = sma(cl, 15)[-1] or cl[-1]
        ms = sma(cl, 30)[-1] or cl[-1]
        _, ts = evaluate_trend_3d(mf, mm, ms)
        c1 = [c["close"] for c in ds]; v1 = [c["volume"] for c in ds]
        ef = (sma(c1, 18)[-1] or c1[-1]); em = (sma(c1, 37)[-1] or c1[-1])
        es = (sma(c1, 30)[-1] or c1[-1])
        ma7 = (sma(c1, int(7 * SF))[-1] or c1[-1]); ma10 = (sma(c1, int(10 * SF))[-1] or c1[-1])
        ma200 = (sma(c1, int(200 * SF))[-1] or None)
        vm = sma(v1, int(20 * SF))[-1] or v1[-1]
        v5a = sum(v1[-(int(6 * SF)):-1]) / (int(5 * SF)) if len(v1) >= int(6 * SF) else v1[-1]
        vs = compute_volume_score(v1[-1], vm); rsi1 = compute_rsi(c1, int(14 * SF))

        new_entries = []
        for ent in entries:
            ep = ent["ep"]; mp = ent["mp"]; tp_s = ent["tp"]; rem = ent["rem"]
            hi = ent["hi"]; tstop = ent["tstop"]
            roi = roi_of(ep, cc, mp, lv)
            if cc > hi: hi = cc; ent["hi"] = hi
            removed = False
            if roi <= -sl_roi:
                eq += roi * rem / 100; trades.append({"t": "SL"}); removed = True
            elif tp_s < len(TP):
                trg, cpct = TP[tp_s]
                if roi >= trg:
                    cf = cpct * rem; eq += roi * cf / 100; rem -= cf
                    ent["rem"] = rem; ent["tp"] = tp_s + 1; trades.append({"t": f"TP{tp_s+1}"})
                    if ent["tp"] >= len(TP): ent["tstop"] = cc * (1 - trr)
            if tp_s >= len(TP) and not removed:
                if tstop is None: tstop = cc * (1 - trr)
                tstop = max(tstop, hi * (1 - trr)); ent["tstop"] = tstop
                if cc <= tstop: eq += roi * rem / 100; trades.append({"t": "TRAIL"}); removed = True
            if not removed: new_entries.append(ent)
        entries = new_entries

        deployed = sum(e["mp"] for e in entries)
        if deployed < 14400 / TOTAL:
            el = compute_entry_v6_long(ts, rsi1, cc, es, em, ef, vs,
                trend_min=prof["trend_min_long"], vol_min=prof["vol_min"],
                rsi_max=prof.get("rsi_max_long", 90), ma7_1d=ma7, ma200_1d=ma200,
                last_volume=v1[-1], vol_5d_avg=v5a,
                use_ma200_filter=False, use_pullback_filter=False,
                use_volume_expan=False, min_entry_score=prof.get("min_entry_score", 0))
            es_ = compute_entry_v6_short(ts, rsi1, cc, es, em, ef, vs,
                trend_max=prof["trend_max_short"], vol_min=prof["vol_min"],
                rsi_min=prof.get("rsi_min_short", 10)) if coin in SHORT_ALLOWED else False
            ps_, act = resolve_action_v6(ts, el, es_, "FLAT")
            if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                sc = _entry_score_v7_long(ts, cc, ma7, ma10, es, ma200, ef, em, vs, v1[-1], v5a, rsi1)
                strong = sc >= 65; mp = esz(coin, strong)
                if deployed + mp <= 14400 / TOTAL + 0.001:
                    entries.append({"ep": cc, "mp": mp, "tp": 0, "rem": 1.0, "hi": cc, "tstop": None})

        ureal = sum(roi_of(e["ep"], cc, e["mp"], lv) * e["rem"] / 100 for e in entries)
        curve.append(eq + ureal)

    slc = sum(1 for t in trades if t["t"] == "SL")
    tpc = sum(1 for t in trades if t["t"].startswith("TP"))
    trc = sum(1 for t in trades if t["t"] == "TRAIL")
    tot = slc + tpc + trc
    slr = slc / tot * 100 if tot else 0
    tpr = (tpc + trc) / tot * 100 if tot else 0
    peak = curve[0] if curve else eq; md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > md: md = dd
    years = len(curve) / 2 / 365 if curve else 1
    teq = curve[-1] if curve else eq
    cagr = ((teq ** (1 / years) - 1) * 100) if years > 0 and teq > 0 else 0
    return cagr, md, slc, tpc, tot, slr, tpr, teq

SL_SWEEP = {
    "ETH": [7, 9, 10, 12, 15],
    "BNB": [9, 12, 15, 18, 22],
    "TRX": [9, 12, 15, 18, 22],
}

print(f"{'='*100}")
print(f"  SL ROI SWEEP — Target 45-55% TP rate")
print(f"{'='*100}")

for coin in COINS:
    print(f"\n  {coin}:")
    print(f"  {'SL ROI%':>8} {'CAGR':>8} {'DD':>8} {'SL#':>6} {'TP#':>6} {'Total':>6} {'SL%':>6} {'TP%':>6} {'$10K→':>10}")
    print(f"  {'─'*75}")
    for sl in SL_SWEEP[coin]:
        c, d, slc, tpc, tot, slr, tpr, teq = bt(coin, sl)
        final = teq * BASE
        marker = " ***" if 45 <= tpr <= 55 else ""
        print(f"  {sl:>7.0f}% {c:+7.1f}% {d:+7.1f}% {slc:>6} {tpc:>6} {tot:>6} {slr:+5.0f}% {tpr:+5.0f}% ${final:>9,.0f}{marker}")
