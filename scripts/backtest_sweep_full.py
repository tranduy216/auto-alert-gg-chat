#!/usr/bin/env python3
"""Full parameter sweep: MA combos, stoploss %, new coins."""

import sys, os
from datetime import datetime
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_atr, compute_rsi, trend_strength,
    compute_volume_score, compute_reaction_score_long, compute_reaction_score_short,
    compute_resistance, compute_support, compute_break_score_long,
    compute_break_score_short, compute_atr_score,
    compute_entry1_signal_long, compute_entry1_signal_short,
    _aggregate_daily_to_3d, SYMBOL_MAP,
)

LOOKBACK_DAYS = 400

# ---------------------------------------------------------------------------
# Trend evaluation
# ---------------------------------------------------------------------------
def trend_custom(ma_short, ma_mid, ma_long):
    if ma_short > ma_mid > ma_long:   return ("STRONG_BULLISH", 3)
    elif ma_short > ma_mid:           return ("BULLISH", 2)
    elif ma_short > ma_long:          return ("WEAK_BULLISH", 1)
    elif ma_short < ma_mid < ma_long: return ("STRONG_BEARISH", -3)
    elif ma_short < ma_mid:           return ("BEARISH", -2)
    elif ma_short < ma_long:          return ("WEAK_BEARISH", -1)
    else:                             return ("NEUTRAL", 0)

# ---------------------------------------------------------------------------
# Exit function with parameterized stoploss
# ---------------------------------------------------------------------------
def exit_fn(pps, ep, cp, rsz, ma3, ma7, ma10, ma20, rsi, ts, ts_val, stop_pct):
    if pps == "FLAT" or ep is None or ep <= 0:
        return ("HOLD", 0.0, "")
    is_long = pps.startswith("LONG")
    pnl = ((cp - ep) / ep * 100) if is_long else ((ep - cp) / ep * 100)
    if pnl <= -stop_pct:
        return ("EXIT_ALL", 1.0, f"Stop loss at {pnl:.1f}% (limit -{stop_pct}%)")
    if is_long:
        if ma3 < ma7 < ma10 and ts_val < -0.4:
            return ("EXIT_ALL", 1.0, f"Emergency exit: MA3<MA7<MA10 & Score {ts_val:.1f}")
    else:
        if ma3 > ma7 > ma10 and ts_val > 0.4:
            return ("EXIT_ALL", 1.0, f"Emergency exit: MA3>MA7>MA10 & Score {ts_val:.1f}")
    if is_long:
        if ma3 < ma10:
            return ("EXIT_ALL", 1.0, f"Trend exit: MA3<MA10")
    else:
        if ma3 > ma10:
            return ("EXIT_ALL", 1.0, f"Trend exit: MA3>MA10")
    if is_long:
        if ts_val < 0.2:
            return ("EXIT_ALL", 1.0, f"Score exit: {ts_val:.1f} < +0.2")
    else:
        if ts_val > -0.2:
            return ("EXIT_ALL", 1.0, f"Score exit: {ts_val:.1f} > -0.2")
    if pnl >= 25:
        cut = rsz * 0.3
        return ("TAKE_PROFIT_2", cut, f"TP2: +{pnl:.1f}% >= 25%")
    if pnl >= 15:
        cut = rsz * 0.3
        return ("TAKE_PROFIT_1", cut, f"TP1: +{pnl:.1f}% >= 15%")
    if is_long:
        if cp > ma20 * 1.25 or rsi > 80:
            cut = rsz * 0.25
            return ("OVER_EXTEND", cut, f"Over-extended: price > MA20*1.25 or RSI>80")
    else:
        if cp < ma20 * 0.75 or rsi < 20:
            cut = rsz * 0.25
            return ("OVER_EXTEND", cut, f"Over-extended: price < MA20*0.75 or RSI<20")
    return ("HOLD", 0.0, "")

# ---------------------------------------------------------------------------
# MA combinations to test
# ---------------------------------------------------------------------------
MA_VARIANTS = [
    ("V0_baseline",   7, 10, 20,  3, 7, 10),
    ("V4_1d_fast",    7, 10, 20,  3, 5, 10),   # ★ best in BEAR
    ("V1_3d_fast",    3,  7, 14,  3, 7, 10),   # ★ best in BULL
    ("V_both_mod",    5, 10, 20,  3, 5, 10),   # moderate
]

STOP_LOSSES = [5, 6, 7, 8, 9, 10, 11, 12, 13]
SWEEP_COINS = ["BTC", "ETH", "BNB", "ARB", "LINK", "PAXG", "XRP", "ADA", "MATIC"]

PERIODS = {
    "BEAR": (None,                             "Recent 400d"),
    "BULL": (int(datetime(2023,1,1).timestamp()*1000), "Bull 2023"),
}

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch(symbol, st=None):
    p = {"symbol": symbol, "interval": "1d", "limit": LOOKBACK_DAYS}
    if st: p["startTime"] = st
    r = req_lib.get("https://api.binance.com/api/v3/klines", params=p, timeout=15)
    r.raise_for_status()
    return [{"open_time":k[0],"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in r.json()]

# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------
def backtest(coin, ma_s3, ma_m3, ma_l3, ma_s1, ma_m1, ma_l1, stop_pct, st):
    symbol = SYMBOL_MAP.get(coin, f"{coin}USDT")
    if coin not in SYMBOL_MAP:
        # Coin not in crypto_trading COINS list, check Binance
        pass
    daily_all = fetch(symbol, st)[-LOOKBACK_DAYS:]
    state = {"position_state": "FLAT", "entry_price": None, "remaining_size": 1.0}
    closes = []

    for day_idx in range(75, len(daily_all)):
        slice_ = daily_all[:day_idx+1]
        c1d = slice_[-30:]
        c3d = _aggregate_daily_to_3d(slice_)
        if len(c3d) < 20: continue

        cc = c1d[-1]["close"]

        # 3D indicators
        c3 = [c["close"] for c in c3d]
        m3s = (sma(c3, ma_s3)[-1] or c3[-1])
        m3m = (sma(c3, ma_m3)[-1] or c3[-1])
        m3l = (sma(c3, ma_l3)[-1] or c3[-1])
        m20 = (sma(c3, max(ma_l3, 14))[-1] or c3[-1])
        _, ts = trend_custom(m3s, m3m, m3l)
        tv = trend_strength(ts)
        rsi = compute_rsi(c3, 14)

        # 1D
        c1 = [c["close"] for c in c1d]
        h1 = [c["high"] for c in c1d]
        l1 = [c["low"] for c in c1d]
        v1 = [c["volume"] for c in c1d]
        m1s = (sma(c1, ma_s1)[-1] or c1[-1])
        m1m = (sma(c1, ma_m1)[-1] or c1[-1])
        m1l = (sma(c1, ma_l1)[-1] or c1[-1])
        vm20 = (sma(v1, 20)[-1] or v1[-1])

        atr = compute_atr(c1d, 14)
        vs = compute_volume_score(v1[-1], vm20)
        rl = compute_reaction_score_long(cc, l1[-1], m1s)
        rs = compute_reaction_score_short(cc, h1[-1], m1s)
        res = compute_resistance(c1d, m1m, m1l)
        sup = compute_support(c1d, m1m, m1l)
        bl = compute_break_score_long(cc, res, atr)
        bs = compute_break_score_short(cc, sup, atr)
        ats = compute_atr_score(atr, cc)

        e1l = compute_entry1_signal_long(cc, m1m, vs)
        e1s = compute_entry1_signal_short(cc, m1m, vs)

        tl = max(0, tv); ts_ = max(0, -tv)
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
            ea, rp, _ = exit_fn(pps, ep, cc, rsz, m3s, m3m, m3l, m20, rsi, ts, tv, stop_pct)

            if ea == "HOLD":
                if   p2l>=0.80 and pps=="LONG_ENTRY_1":  state["position_state"]="LONG_ENTRY_2"
                elif p3l>=0.85 and pps=="LONG_ENTRY_2": state["position_state"]="LONG_ENTRY_3"
                elif p2s>=0.80 and pps=="SHORT_ENTRY_1":state["position_state"]="SHORT_ENTRY_2"
                elif p3s>=0.85 and pps=="SHORT_ENTRY_2":state["position_state"]="SHORT_ENTRY_3"
            elif ea == "EXIT_ALL":
                closes.append(pnl)
                state.update({"position_state":"FLAT","entry_price":None,"remaining_size":1.0})
            elif ea in ("TAKE_PROFIT_1","TAKE_PROFIT_2","OVER_EXTEND"):
                rsz = round(rsz - rsz*rp, 4) if rp>0 else rsz
                state["remaining_size"] = rsz
                if rsz < 0.01:
                    state.update({"position_state":"FLAT","entry_price":None,"remaining_size":1.0})
    return closes

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"{'='*90}")
    print("  FULL SWEEP: MA combos × Stoploss × Coins × Periods")
    print(f"{'='*90}")

    # Quick check: which coins have valid symbols?
    valid_coins = []
    for coin in SWEEP_COINS:
        sym = SYMBOL_MAP.get(coin, f"{coin}USDT")
        try:
            d = fetch(sym)
            if len(d) > 100:
                valid_coins.append(coin)
        except:
            print(f"  Skipping {coin} (not found on Binance)")
    print(f"  Valid coins: {', '.join(valid_coins)}")

    for pkey, (pstime, plabel) in PERIODS.items():
        print(f"\n{'='*90}")
        print(f"  {plabel}")
        print(f"{'='*90}")

        # Sweep: MA × stoploss
        all_results = []
        for ma_name, s3,m3,l3, s1,m1,l1 in MA_VARIANTS:
            for sl in STOP_LOSSES:
                total_pnl = 0
                total_trades = 0
                details = []
                for coin in valid_coins:
                    try:
                        closes = backtest(coin, s3,m3,l3, s1,m1,l1, sl, pstime)
                        p = sum(closes) if closes else 0
                        n = len(closes)
                        total_pnl += p
                        total_trades += n
                        details.append(f"{coin}={p:+.1f}({n})")
                    except Exception as e:
                        details.append(f"{coin}=ERR")
                all_results.append((total_pnl, total_trades, ma_name, sl, details))

        # Sort by PnL descending
        all_results.sort(key=lambda x: x[0], reverse=True)

        # Top 10
        print(f"  {'Rank':<5} {'MA Variant':<16} {'SL':>4} {'PnL':>10} {'Trades':>7}  Coins")
        print(f"  {'─'*5} {'─'*16} {'─'*4} {'─'*10} {'─'*7}  {'─'*40}")
        for i, (pnl, nt, ma, sl, det) in enumerate(all_results[:15]):
            mark = "★" if i == 0 else " "
            print(f"  {mark}{i+1:<4d} {ma:<16s} {sl:>3d}% {pnl:>+9.2f}% {nt:>5d}  {' | '.join(det)}")

    # Best coin analysis with V4 + optimal stoploss
    print(f"\n{'='*90}")
    print("  BEST CONFIG PER COIN (V4_1d_fast)")
    print(f"{'='*90}")
    for pkey, (pstime, plabel) in PERIODS.items():
        print(f"\n  --- {plabel} ---")
        print(f"  {'Coin':>6s} |", end="")
        for sl in STOP_LOSSES:
            print(f" {sl:>3d}% ", end="")
        print()
        for coin in valid_coins:
            print(f"  {coin:>6s} |", end="")
            for sl in STOP_LOSSES:
                try:
                    closes = backtest(coin, 7,10,20, 3,5,10, sl, pstime)
                    p = sum(closes) if closes else 0
                    print(f" {p:>+5.1f}", end="")
                except:
                    print(f"  ERR ", end="")
            print()

if __name__ == "__main__":
    main()
