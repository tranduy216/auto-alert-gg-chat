#!/usr/bin/env python3
"""Backtest each rule individually vs baseline. Find which to keep."""

import sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib
from crypto_trading import (
    sma, compute_atr, compute_rsi, trend_strength, evaluate_exit_v5,
    compute_volume_score, compute_reaction_score_long, compute_reaction_score_short,
    compute_resistance, compute_support, compute_break_score_long,
    compute_break_score_short, compute_atr_score,
    compute_entry1_signal_long, compute_entry1_signal_short,
    _aggregate_daily_to_3d, SYMBOL_MAP,
)

LOOKBACK = 400
COINS_BT = ["ETH", "BNB", "ADA", "MATIC", "LINK"]
PERIODS = {
    "BEAR": (None, "Recent 400d"),
    "BULL": (int(datetime(2023,1,1).timestamp()*1000), "Bull 2023"),
}

_cache = {}
def fetch(symbol, st=None):
    key = (symbol, st)
    if key not in _cache:
        p = {"symbol": symbol, "interval": "1d", "limit": LOOKBACK}
        if st: p["startTime"] = st
        r = req_lib.get("https://api.binance.com/api/v3/klines", params=p, timeout=15)
        r.raise_for_status()
        _cache[key] = [
            {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in r.json()
        ]
    return _cache[key]

def _btc_ma(st):
    btc = fetch("BTCUSDT", st)
    c = [x["close"] for x in btc[-200:]]
    return (sma(c,50)[-1] or c[-1]) > (sma(c,200)[-1] or c[-1])

def trend_custom(ms, mm, ml):
    if ms > mm > ml: return ("SB", 3)
    elif ms > mm: return ("B", 2)
    elif ms > ml: return ("WB", 1)
    elif ms < mm < ml: return ("SBS", -3)
    elif ms < mm: return ("S", -2)
    elif ms < ml: return ("WS", -1)
    return ("N", 0)

def run_bt(coin, st, rules):
    """rules: set of rule names to enable."""
    da = fetch(SYMBOL_MAP[coin], st)[-LOOKBACK:]
    stt = {"ps":"FLAT","ep":None,"rs":1.0,"pk":None,"lsk":0}
    closes = []
    btc_bull = _btc_ma(st) if "btc_regime" in rules else None

    atr_history = []
    for di in range(75, len(da)):
        slc = da[:di+1]; c1d=slc[-30:]; c3d=_aggregate_daily_to_3d(slc)
        if len(c3d) < 20: continue
        cx = c1d[-1]["close"]
        c3 = [c["close"] for c in c3d]
        m3s=(sma(c3,7)[-1] or c3[-1]); m3m=(sma(c3,10)[-1] or c3[-1]); m3l=(sma(c3,20)[-1] or c3[-1])
        m20=(sma(c3,20)[-1] or c3[-1])
        _, ts=trend_custom(m3s,m3m,m3l); tv=trend_strength(ts)
        rsi=compute_rsi(c3,14)
        c1=[c["close"] for c in c1d]; h1=[c["high"] for c in c1d]; l1=[c["low"] for c in c1d]; v1=[c["volume"] for c in c1d]
        m1s=(sma(c1,3)[-1] or c1[-1]); m1m=(sma(c1,5)[-1] or c1[-1]); m1l=(sma(c1,10)[-1] or c1[-1])
        m17=(sma(c1,7)[-1] or c1[-1]); vm20=(sma(v1,20)[-1] or v1[-1])
        atr=compute_atr(c1d,14); atr_history.append(atr)
        atr_ma20 = sma(atr_history, 20)[-1] if len(atr_history) >= 20 else atr
        vs=compute_volume_score(v1[-1],vm20)
        rl=compute_reaction_score_long(cx,l1[-1],m1s); rs=compute_reaction_score_short(cx,h1[-1],m1s)
        res=compute_resistance(c1d,m1m,m1l); sup=compute_support(c1d,m1m,m1l)
        bl=compute_break_score_long(cx,res,atr); bs=compute_break_score_short(cx,sup,atr); ats=compute_atr_score(atr,cx)
        um=m17 if ts>=2 else m1m
        e1l=compute_entry1_signal_long(cx,um,vs); e1s=compute_entry1_signal_short(cx,um,vs)
        eth=2 if abs(ts)>=2 else 3
        tl=max(0,tv); ts_=max(0,-tv)
        p2l=min(1,max(0,0.35*tl+0.25*rl+0.25*vs+0.15*ats))
        p2s=min(1,max(0,0.35*ts_+0.25*rs+0.25*vs+0.15*ats))
        p3l=min(1,max(0,0.30*tl+0.20*rl+0.30*vs+0.20*bl))
        p3s=min(1,max(0,0.30*ts_+0.20*rs+0.30*vs+0.20*bs))
        ps=stt["ps"]; ep=stt["ep"]; rz=stt["rs"]; lsk=stt["lsk"]; pk=stt["pk"]

        if ps == "FLAT":
            # ── Filter chain ──
            if "volatility" in rules and atr > atr_ma20 * 1.8:
                continue
            # BTC regime: block new LONG in bear, block new SHORT in bull
            if "btc_regime" in rules:
                if not btc_bull and ts >= eth:
                    continue  # no LONG in bear
            if ts >= eth and e1l:
                sz = 1.0
                if "breaker" in rules and lsk >= 3:
                    sz *= 0.5
                stt.update({"ps":"LONG_ENTRY_1","ep":cx,"rs":sz,"pk":cx})
            elif ts <= -eth and e1s:
                sz = 1.0
                if "breaker" in rules and lsk >= 3:
                    sz *= 0.5
                stt.update({"ps":"SHORT_ENTRY_1","ep":cx,"rs":sz,"pk":cx})
        else:
            il=ps.startswith("LONG")
            pnl=((cx-ep)/ep*100) if il else ((ep-cx)/ep*100)
            new_pk=max(pk,cx) if il else min(pk,cx) if pk else cx
            stt["pk"]=new_pk

            # BTC regime: no action needed in active position (only blocks NEW entries)

            ea,rp,_=evaluate_exit_v5(ps,ep,cx,rz,m3s,m3m,m3l,m20,rsi,ts,tv)
            if ea=="HOLD":
                if   p2l>=0.80 and ps=="LONG_ENTRY_1":  stt["ps"]="LONG_ENTRY_2"
                elif p3l>=0.85 and ps=="LONG_ENTRY_2": stt["ps"]="LONG_ENTRY_3"
                elif p2s>=0.80 and ps=="SHORT_ENTRY_1":stt["ps"]="SHORT_ENTRY_2"
                elif p3s>=0.85 and ps=="SHORT_ENTRY_2":stt["ps"]="SHORT_ENTRY_3"
            elif ea=="EXIT_ALL":
                lsk2=0 if pnl>0 else lsk+1
                closes.append(pnl)
                stt.update({"ps":"FLAT","ep":None,"rs":1.0,"pk":None,"lsk":lsk2})
            elif ea in ("TAKE_PROFIT_1","TAKE_PROFIT_2","OVER_EXTEND"):
                rz=round(rz-rz*rp,4) if rp>0 else rz; stt["rs"]=rz
                if rz<0.01:
                    closes.append(pnl)
                    stt.update({"ps":"FLAT","ep":None,"rs":1.0,"pk":None})
    return closes

RULES = [
    ("none",              set()),
    ("btc_regime",        {"btc_regime"}),
    ("breaker",           {"breaker"}),
    ("volatility_1.8x",   {"volatility"}),
    ("volatility_1.5x",   {"volatility_1.5x"}),
    ("volatility_2.0x",   {"volatility_2.0x"}),
    ("all_rules",         {"btc_regime","breaker","volatility"}),
]

def main():
    print(f"{'='*90}")
    print("  RULE BACKTEST: each rule individually + all combined (time filter skipped — no event data)")
    print(f"{'='*90}")

    results = {}
    for pkey, (pstime, plabel) in PERIODS.items():
        print(f"\n{'='*90}")
        print(f"  {plabel}")
        print(f"{'='*90}")
        print(f"  {'Rule':<16s} {'PnL':>8s}  Coins")
        print(f"  {'─'*16} {'─'*8}  {'─'*50}")
        results[pkey] = {}
        for rname, rset in RULES:
            total = 0; details = []
            for coin in COINS_BT:
                cl = run_bt(coin, pstime, rset)
                p = sum(cl) if cl else 0; total += p
                details.append(f"{coin}={p:+.1f}({len(cl)})")
            results[pkey][rname] = total
            mark = "★" if rname == "all_rules" else " "
            print(f"  {mark}{rname:<15s} {total:>+8.2f}%  {' | '.join(details)}")

    # Impact analysis
    print(f"\n{'='*90}")
    print("  RULE IMPACT (PnL delta vs baseline 'none')")
    print(f"{'='*90}")
    print(f"  {'Rule':<16s} {'BEAR':>10s} {'BULL':>10s}")
    print(f"  {'─'*16} {'─'*10} {'─'*10}")
    for rname, _ in RULES[1:]:  # skip 'none'
        bear_d = results["BEAR"][rname] - results["BEAR"]["none"]
        bull_d = results["BULL"][rname] - results["BULL"]["none"]
        print(f"  {rname:<15s} {bear_d:>+9.2f}% {bull_d:>+9.2f}%")

    # Combined impact
    print(f"  {'─'*16} {'─'*10} {'─'*10}")
    all_bear = results["BEAR"]["all_rules"] - results["BEAR"]["none"]
    all_bull = results["BULL"]["all_rules"] - results["BULL"]["none"]
    print(f"  {'all_combined':<15s} {all_bear:>+9.2f}% {all_bull:>+9.2f}%")

    print(f"\n  {'Summary:':<16s}")
    print(f"  Baseline (no rules): BEAR={results['BEAR']['none']:+.1f}% BULL={results['BULL']['none']:+.1f}%")
    print(f"  All rules combined: BEAR={results['BEAR']['all_rules']:+.1f}% BULL={results['BULL']['all_rules']:+.1f}%")

if __name__ == "__main__":
    main()
