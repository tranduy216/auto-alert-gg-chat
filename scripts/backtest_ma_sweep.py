#!/usr/bin/env python3
"""Sweep 3D/1D MA combinations to find optimal parameters."""

import sys, os
from datetime import datetime
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_atr, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, compute_reaction_score_long, compute_reaction_score_short,
    compute_resistance, compute_support, compute_break_score_long,
    compute_break_score_short, compute_atr_score,
    compute_entry1_signal_long, compute_entry1_signal_short,
    evaluate_exit_v5, _aggregate_daily_to_3d,
    COINS, SYMBOL_MAP,
)

LOOKBACK_DAYS = 400

def evaluate_trend_custom(ma_short, ma_mid, ma_long):
    if ma_short > ma_mid > ma_long:  return ("STRONG_BULLISH", 3)
    elif ma_short > ma_mid:          return ("BULLISH", 2)
    elif ma_short > ma_long:         return ("WEAK_BULLISH", 1)
    elif ma_short < ma_mid < ma_long:return ("STRONG_BEARISH", -3)
    elif ma_short < ma_mid:          return ("BEARISH", -2)
    elif ma_short < ma_long:         return ("WEAK_BEARISH", -1)
    else:                            return ("NEUTRAL", 0)

# (name, 3d_short, 3d_mid, 3d_long, 1d_short, 1d_mid, 1d_long)
VARIANTS = [
    ("V0_baseline",  7, 10, 20,  3, 7, 10),   # current
    ("V1_3d_fast",   3,  7, 14,  3, 7, 10),   # faster 3D, keep 1D
    ("V2_3d_medium", 5, 10, 20,  3, 7, 10),   # moderate 3D, keep 1D
    ("V3_1d_trend",  7, 10, 20,  5, 10, 20),  # slower 1D (less whipsaw)
    ("V4_1d_fast",   7, 10, 20,  3, 5, 10),   # faster 1D
    ("V5_both_fast", 3,  7, 14,  3, 5, 10),   # both faster
    ("V6_all_ema",   7, 10, 20,  3, 7, 10),   # EMA baseline
]

def ema(data, period):
    if len(data) < period:
        return [None]*len(data)
    k = 2 / (period + 1)
    result = [None]*(period-1) + [sum(data[:period])/period]
    for v in data[period:]:
        result.append(v * k + result[-1] * (1-k))
    return result

def fetch_klines(symbol, start_time=None):
    params = {"symbol": symbol, "interval": "1d", "limit": LOOKBACK_DAYS}
    if start_time: params["startTime"] = start_time
    resp = req_lib.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
    resp.raise_for_status()
    return [{"open_time":k[0],"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in resp.json()]

PERIODS = {
    "BEAR": (None, "Recent 400d"),
    "BULL": (int(datetime(2023,1,1).timestamp()*1000), "Bull 2023"),
}

def backtest_variant(coin, ma_s3, ma_m3, ma_l3, ma_s1, ma_m1, ma_l1, start_time):
    symbol = SYMBOL_MAP[coin]
    daily_all = fetch_klines(symbol, start_time)[-LOOKBACK_DAYS:]
    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0}
    closes = []

    for day_idx in range(75, len(daily_all)):
        slice_ = daily_all[:day_idx+1]
        candles_1d = slice_[-30:]
        candles_3d = _aggregate_daily_to_3d(slice_)
        if len(candles_3d) < 20: continue

        cc = candles_1d[-1]["close"]

        # 3D indicators
        c3 = [c["close"] for c in candles_3d]
        ma_s   = (sma(c3, ma_s3)[-1] or c3[-1])
        ma_m   = (sma(c3, ma_m3)[-1] or c3[-1])
        ma_l   = (sma(c3, ma_l3)[-1] or c3[-1])
        ma20   = (sma(c3, ma_l3)[-1] or c3[-1])  # variant's long MA
        _, ts  = evaluate_trend_custom(ma_s, ma_m, ma_l)
        ts_val = trend_strength(ts)
        rsi_3d = compute_rsi(c3, 14)

        # 1D
        c1 = [c["close"] for c in candles_1d]
        h1 = [c["high"] for c in candles_1d]
        l1 = [c["low"] for c in candles_1d]
        v1 = [c["volume"] for c in candles_1d]
        ma3_1d = (sma(c1, ma_s1)[-1] or c1[-1])
        ma7_1d = (sma(c1, ma_m1)[-1] or c1[-1])
        ma10_1d = (sma(c1, ma_l1)[-1] or c1[-1])
        vm20 = (sma(v1, 20)[-1] or v1[-1])
        atr = compute_atr(candles_1d, 14)

        vs = compute_volume_score(v1[-1], vm20)
        rl = compute_reaction_score_long(cc, l1[-1], ma3_1d)
        rs = compute_reaction_score_short(cc, h1[-1], ma3_1d)
        res = compute_resistance(candles_1d, ma7_1d, ma10_1d)
        sup = compute_support(candles_1d, ma7_1d, ma10_1d)
        bl = compute_break_score_long(cc, res, atr)
        bs = compute_break_score_short(cc, sup, atr)
        ats = compute_atr_score(atr, cc)

        e1l = compute_entry1_signal_long(cc, ma7_1d, vs)
        e1s = compute_entry1_signal_short(cc, ma7_1d, vs)

        tl = max(0, ts_val)
        ts_ = max(0, -ts_val)
        p2l = min(1, max(0, 0.35*tl + 0.25*rl + 0.25*vs + 0.15*ats))
        p2s = min(1, max(0, 0.35*ts_ + 0.25*rs + 0.25*vs + 0.15*ats))
        p3l = min(1, max(0, 0.30*tl + 0.20*rl + 0.30*vs + 0.20*bl))
        p3s = min(1, max(0, 0.30*ts_ + 0.20*rs + 0.30*vs + 0.20*bs))

        pps = state["position_state"]
        ep  = state["entry_price"]
        rsz = state["remaining_size"]

        if pps == "FLAT":
            if ts >= 3 and e1l:
                state.update({"position_state":"LONG_ENTRY_1","entry_price":cc,"remaining_size":1.0})
            elif ts <= -3 and e1s:
                state.update({"position_state":"SHORT_ENTRY_1","entry_price":cc,"remaining_size":1.0})
        else:
            il = pps.startswith("LONG")
            pnl = ((cc-ep)/ep*100) if il else ((ep-cc)/ep*100)
            ea, rp, _ = evaluate_exit_v5(pps, ep, cc, rsz, ma_s, ma_m, ma_l, ma20, rsi_3d, ts, ts_val)
            if ea == "HOLD":
                # adds only
                adv = False
                if p2l>=0.80 and pps=="LONG_ENTRY_1":  state["position_state"]="LONG_ENTRY_2"; adv=True
                elif p3l>=0.85 and pps=="LONG_ENTRY_2": state["position_state"]="LONG_ENTRY_3"; adv=True
                elif p2s>=0.80 and pps=="SHORT_ENTRY_1":state["position_state"]="SHORT_ENTRY_2";adv=True
                elif p3s>=0.85 and pps=="SHORT_ENTRY_2":state["position_state"]="SHORT_ENTRY_3";adv=True
            elif ea == "EXIT_ALL":
                closes.append(pnl)
                state.update({"position_state":"FLAT","entry_price":None,"remaining_size":1.0})
            elif ea in ("TAKE_PROFIT_1","TAKE_PROFIT_2","OVER_EXTEND"):
                rsz = round(rsz - rsz*rp, 4) if rp>0 else rsz
                state["remaining_size"] = rsz
                if rsz < 0.01:
                    state.update({"position_state":"FLAT","entry_price":None,"remaining_size":1.0})

    return closes

SWEEP_COINS = ["BTC", "ETH", "BNB", "ARB", "LINK", "PAXG"]

def main():
    print(f"{'='*100}")
    print("  MA Parameter Sweep")
    print(f"{'='*100}")

    for pkey, (pstime, plabel) in PERIODS.items():
        print(f"\n{'='*100}")
        print(f"  Period: {plabel}")
        print(f"{'='*100}")

        results = []
        for vname, s3, m3, l3, s1, m1, l1 in VARIANTS:
            total_pnl = 0
            total_trades = 0
            results_str = []

            for coin in SWEEP_COINS:
                closes = backtest_variant(coin, s3, m3, l3, s1, m1, l1, pstime)
                pnl = sum(closes) if closes else 0
                n = len(closes)
                total_pnl += pnl
                total_trades += n
                results_str.append(f"{coin}={pnl:+.1f}%(n={n})")

            results.append((vname, total_pnl, total_trades, results_str))

        # Sort by total PnL descending
        results.sort(key=lambda x: x[1], reverse=True)

        for i, (vname, pnl, ntrades, detail) in enumerate(results):
            prefix = "★" if i == 0 else " "
            print(f"  {prefix} {vname:16s} | Sum PnL={pnl:+7.2f}% | Trades={ntrades:2d} | {' | '.join(detail)}")

    print(f"\n{'='*100}")
    print("  Legend:")
    for vname, s3, m3, l3, s1, m1, l1 in VARIANTS:
        print(f"  {vname:16s}: 3D MA{s3}/{m3}/{l3} | 1D MA{s1}/{m1}/{l1}")
    print(f"{'='*100}")

if __name__ == "__main__":
    main()
