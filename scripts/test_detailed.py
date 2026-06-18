#!/usr/bin/env python3
"""Detailed tests: LONG/SHORT BTC/SOL, entry threshold, PAXG stops, portfolio sim."""

import itertools
import os
import sys
from datetime import datetime, timedelta
from statistics import mean, stdev

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests as req_lib

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, _aggregate_daily_to_3d,
    SHORT_ALLOWED,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

BINANCE_MAX_LIMIT = 1000
MIN_3D_PERIODS = 25

PERIODS = {
    "2021_2023": {
        "label": "2021–2023",
        "start_time": int(datetime(2021, 1, 1).timestamp() * 1000),
        "limit": BINANCE_MAX_LIMIT,
    },
    "2024_2026": {
        "label": "2024–2026",
        "start_time": int(datetime(2024, 1, 1).timestamp() * 1000),
        "limit": BINANCE_MAX_LIMIT,
    },
    "2021_2026": {
        "label": "2021–2026 (full)",
        "start_time": int(datetime(2021, 1, 1).timestamp() * 1000),
        "limit": 2000,
    },
}

_data_cache: dict = {}

def fetch_all_klines(symbol: str, limit: int = 1000, start_time: int | None = None) -> list[dict]:
    key = (symbol, limit, start_time)
    if key in _data_cache:
        return _data_cache[key]
    candles = []
    remaining = limit
    cur_start = start_time
    while remaining > 0:
        take = min(remaining, BINANCE_MAX_LIMIT)
        params = {"symbol": symbol, "interval": "1d", "limit": take + 50}
        if cur_start:
            params["startTime"] = cur_start
        resp = req_lib.get("https://api.binance.com/api/v3/klines", params=params, timeout=15)
        resp.raise_for_status()
        batch = [
            {"open_time": k[0], "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in resp.json()
        ]
        if len(batch) <= 1: break
        candles.extend(batch)
        remaining -= len(batch)
        cur_start = batch[-1]["open_time"] + 1
        if len(candles) >= limit: break
    result = candles[:limit]
    _data_cache[key] = result
    return result


def entry_long(
    ts, rsi, close, ma20, ma_slow, ma_fast, vs,
    t_min=1, v_min=0.3,
):
    if ts < t_min: return False
    if ma_fast is not None and ma_fast < ma_slow: return False
    if close < ma20 or close < ma_slow: return False
    if vs < v_min: return False
    return True

def entry_short(
    ts, rsi, close, ma20, ma_slow, ma_fast, vs,
    t_max=-3, v_min=0.3,
):
    if ts > t_max: return False
    if ma_fast is not None and ma_fast > ma_slow: return False
    if close > ma20 or close > ma_slow: return False
    if vs < v_min: return False
    return True

def exit_v6(ps, ep, cp, rsz, ma7, ma20, ts, tv, rsi3, ts_, he,
            ml=0.06, tr=0.80, hs=0.75):
    if ps == "FLAT" or ep is None or ep <= 0:
        return ("HOLD", 0.0, "", ts_, he)
    il = ps.startswith("LONG")
    pnl = ((cp - ep) / ep * 100) if il else ((ep - cp) / ep * 100)
    bp = max(he or ep, cp) if il else min(he or ep, cp)
    ns = ts_
    if ns is None:
        ns = round(ep * (tr if il else (2 - tr)), 2)
    if il:
        if bp > (he or ep):
            tb = bp * tr
            if tb > ns: ns = round(tb, 2)
    else:
        if bp < (he or ep):
            tb = bp * (2 - tr)
            if tb < ns: ns = round(tb, 2)
    if pnl <= -ml * 100:
        return ("EXIT_ALL", 1.0, f"ML{ml*100:.0f}%", ns, bp)
    hl = round(ep * (hs if il else (2 - hs)), 2)
    if il:
        if cp <= max(ns or 0, hl): return ("EXIT_ALL", 1.0, "STOP", ns, bp)
    else:
        if cp >= min(ns or 999999, hl): return ("EXIT_ALL", 1.0, "STOP", ns, bp)
    if il and ma7 < ma20: return ("EXIT_ALL", 1.0, "MA7<MA20", ns, bp)
    if not il and ma7 > ma20: return ("EXIT_ALL", 1.0, "MA7>MA20", ns, bp)
    if il and tv < -0.3: return ("EXIT_ALL", 1.0, f"SCORE{tv:.1f}", ns, bp)
    if not il and tv > 0.3: return ("EXIT_ALL", 1.0, f"SCORE{tv:.1f}", ns, bp)
    return ("HOLD", 0.0, "", ns, bp)


def backtest_coin(
    coin: str, daily_all: list[dict],
    ma_fast: int = 12, ma_slow: int = 25,
    t_min_long: int = 0, t_max_short: int = -3,
    vol_min: float = 0.3,
    ml: float = 0.06, tr: float = 0.80, hs: float = 0.75,
    lev: float = 2.5,
    long_only: bool = False, short_only: bool = False,
) -> dict:
    first = datetime.utcfromtimestamp(daily_all[0]["open_time"] / 1000).strftime("%Y-%m-%d")
    last = datetime.utcfromtimestamp(daily_all[-1]["open_time"] / 1000).strftime("%Y-%m-%d")
    state = {"ps": "FLAT", "ep": None, "rsz": 1.0, "ts": None, "he": None,
             "sls": 0, "scu": None, "lls": 0, "lcu": None}
    trades = []
    eq = [1.0]
    INITIAL_DAYS = MIN_3D_PERIODS * 3
    short_allowed = coin in SHORT_ALLOWED and not long_only

    can_short = coin in SHORT_ALLOWED
    long_ok = not short_only
    short_ok = can_short and not long_only

    for di in range(INITIAL_DAYS, len(daily_all)):
        ds = daily_all[:di + 1]
        c3d = _aggregate_daily_to_3d(ds)
        if len(c3d) < MIN_3D_PERIODS: continue
        cc = ds[-1]["close"]
        c3c = [c["close"] for c in c3d]
        m7 = (sma(c3c, 7)[-1] or c3c[-1])
        m10 = (sma(c3c, 10)[-1] or c3c[-1])
        m20 = (sma(c3c, 20)[-1] or c3c[-1])
        _, ts = evaluate_trend_3d(m7, m10, m20)
        tv = trend_strength(ts)
        rsi3 = compute_rsi(c3c, 14)
        c1c = [c["close"] for c in ds]
        h1 = [c["high"] for c in ds]
        l1 = [c["low"] for c in ds]
        v1 = [c["volume"] for c in ds]
        ma20_1d = (sma(c1c, 20)[-1] or c1c[-1])
        ma50_1d = (sma(c1c, 50)[-1] or c1c[-1])
        mf = (sma(c1c, ma_fast)[-1] or None)
        ms = sma(c1c, ma_slow)[-1] or ma50_1d
        vm20 = (sma(v1, 20)[-1] or v1[-1])
        vs = compute_volume_score(v1[-1], vm20)
        rsi1 = compute_rsi(c1c, 14)
        r10l = min(l1[-10:]) if len(l1) >= 10 else cc * 0.95
        r10h = max(h1[-10:]) if len(h1) >= 10 else cc * 1.05
        dt = ds[-1]["open_time"]
        ds_ = datetime.utcfromtimestamp(dt / 1000).strftime("%Y-%m-%d") if isinstance(dt, int) else str(dt)
        pps = state["ps"]
        ep = state["ep"]
        rsz = state["rsz"]
        ts_ = state.get("ts")
        he = state.get("he")

        if pps == "FLAT":
            _la = True
            if state.get("lcu"):
                cd = state["lcu"]
                if isinstance(cd, str) and dt and isinstance(dt, int):
                    if dt < int(datetime.fromisoformat(cd).timestamp() * 1000): _la = False
                elif isinstance(cd, (int, float)) and isinstance(dt, int):
                    if dt < cd: _la = False
            el = entry_long(ts, rsi1, cc, ma20_1d, ms, mf, vs, t_min_long, vol_min) if _la and long_ok else False
            _sa = short_ok
            if _sa and state.get("scu"):
                cd = state["scu"]
                if isinstance(cd, str) and dt and isinstance(dt, int):
                    if dt < int(datetime.fromisoformat(cd).timestamp() * 1000): _sa = False
                elif isinstance(cd, (int, float)) and isinstance(dt, int):
                    if dt < cd: _sa = False
            es = entry_short(ts, rsi1, cc, ma20_1d, ms, mf, vs, t_max_short, vol_min) if _sa else False
            if el:
                pps = "LONG_ENTRY_1"; ep = cc; rsz = 1.0; ts_ = None; he = None
                trades.append({"d": ds_, "t": "LONG_OPEN", "p": cc, "r": f"TS={ts}"})
            elif es:
                pps = "SHORT_ENTRY_1"; ep = cc; rsz = 1.0; ts_ = None; he = None
                trades.append({"d": ds_, "t": "SHORT_OPEN", "p": cc, "r": f"TS={ts}"})
            else:
                pps = "FLAT"
            state.update({"ps": pps, "ep": ep, "rsz": rsz, "ts": ts_, "he": he})
        else:
            il = pps.startswith("LONG")
            pnl = ((cc - ep) / ep * 100 if il else (ep - cc) / ep * 100) if ep and ep > 0 else 0
            ea, rp, er, nts, nhe = exit_v6(pps, ep, cc, rsz, m7, m20, ts, tv, rsi3, ts_, he, ml, tr, hs)
            ts_ = nts; he = nhe
            if ea == "HOLD":
                pps = pps
            else:
                if ea == "EXIT_ALL":
                    trades.append({"d": ds_, "t": "CLOSE", "p": cc, "s": rsz, "pnl": round(pnl, 2), "r": er})
                    if "SHORT" in pps:
                        sls = state.get("sls", 0)
                        if pnl > 0: state["sls"] = 0; state["scu"] = None
                        else: sls += 1; state["sls"] = sls
                        if sls >= SHORT_COOLDOWN_LOSSES:
                            state["scu"] = (datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)).isoformat()
                    else:
                        lls = state.get("lls", 0)
                        if pnl > 0: state["lls"] = 0; state["lcu"] = None
                        else: lls += 1; state["lls"] = lls
                        if lls >= LONG_COOLDOWN_LOSSES:
                            state["lcu"] = (datetime.utcfromtimestamp(dt / 1000) + timedelta(days=LONG_COOLDOWN_DAYS)).isoformat()
                    pps = "FLAT"; rsz = 0.0; ep = None
            state.update({"ps": pps, "ep": ep, "rsz": rsz, "ts": ts_, "he": he})
        if state["ps"] != "FLAT" and state["ep"] and state["rsz"] > 0:
            _il = state["ps"].startswith("LONG")
            upnl = ((cc - state["ep"]) / state["ep"] * 100 if _il else (state["ep"] - cc) / state["ep"] * 100)
            eq.append(1.0 + upnl / 100 * state["rsz"] * lev)
        else:
            eq.append(1.0)
    return {"coin": coin, "trades": trades, "eq": eq, "period": f"{first} → {last}"}


def metrics(r):
    closes = [t for t in r["trades"] if t["t"] == "CLOSE"]
    if not closes:
        return {"coin": r["coin"], "n": 0, "pnl": 0, "msg": "No trades", "period": r["period"]}
    pnls = [t["pnl"] for t in closes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    tp = sum(pnls)
    wr = len(wins) / len(closes) * 100
    aw = mean(wins) if wins else 0
    al = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")
    eq = r["eq"]
    peak = eq[0]; mdd = 0
    for v in eq:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd: mdd = dd
    rets = [(eq[i] - eq[i-1]) / eq[i-1] for i in range(1, len(eq)) if eq[i-1] > 0]
    sh = 0
    if len(rets) > 1 and stdev(rets) > 0:
        sh = (mean(rets) / stdev(rets)) * (365 ** 0.5)
    return {"coin": r["coin"], "n": len(closes), "pnl": round(tp, 2), "wr": round(wr, 1),
            "aw": round(aw, 2), "al": round(al, 2), "pf": round(pf, 2),
            "mdd": round(mdd, 2), "sh": round(sh, 2), "period": r["period"]}


def print_m(m):
    if m.get("msg"):
        print(f"  {m['coin']:7s} | {m['msg']}")
        return
    print(f"  {m['coin']:7s} | Trades={m['n']:3d} | PnL={m['pnl']:+8.2f}% | "
          f"WR={m['wr']:4.0f}% | PF={m['pf']:<6.2f} | DD={m['mdd']:5.1f}% | "
          f"Sharpe={m['sh']:.2f}")


# ====== TEST SUITES ======

COIN_MAP = {"ETH": "ETHUSDT", "BNB": "BNBUSDT", "PAXG": "PAXGUSDT", "TRX": "TRXUSDT", "SOL": "SOLUSDT", "BTC": "BTCUSDT"}


def test1_long_short(period_key, period_info):
    """Test LONG-only vs SHORT-only for BTC and SOL."""
    print(f"\n{'='*70}")
    print(f"  TEST 1: LONG vs SHORT — BTC & SOL")
    print(f"  Period: {period_info['label']}")
    print(f"{'='*70}")
    cfg = dict(ma_fast=12, ma_slow=25, t_min_long=0, t_max_short=-3,
               vol_min=0.3, ml=0.06, tr=0.80, hs=0.75, lev=2.5)
    tests = [
        ("BTC LONG-only", "BTC", True, False),
        ("BTC SHORT-only", "BTC", False, True),
        ("BTC BOTH", "BTC", False, False),
        ("SOL LONG-only", "SOL", True, False),
        ("SOL SHORT-only", "SOL", False, True),
        ("SOL BOTH", "SOL", False, False),
    ]
    for label, coin, lo, so in tests:
        raw = fetch_all_klines(COIN_MAP[coin], period_info["limit"], period_info["start_time"])
        da = raw[:period_info["limit"]] if period_info["start_time"] else raw[-period_info["limit"]:]
        r = backtest_coin(coin, da, long_only=lo, short_only=so, **cfg)
        m = metrics(r)
        print(f"  {label:20s}", end="")
        print_m(m)


def test2_entry_threshold(period_key, period_info, coin_list):
    """Test entry threshold sensitivity."""
    print(f"\n{'='*70}")
    print(f"  TEST 2: ENTRY THRESHOLD SENSITIVITY")
    print(f"  Period: {period_info['label']} | Coins: {', '.join(coin_list)}")
    print(f"{'='*70}")
    base = dict(ma_fast=12, ma_slow=25, vol_min=0.3,
                ml=0.06, tr=0.80, hs=0.75, lev=2.5)
    thresholds = [(0, -3, "T0_-3"), (1, -3, "T1_-3"), (2, -3, "T2_-3"),
                  (0, -2, "T0_-2"), (1, -2, "T1_-2")]
    rows = []
    for tml, tms, label in thresholds:
        total_pnl = 0; total_wr = 0; total_pf = 0; total_dd = 0; total_sh = 0; total_nt = 0; nv = 0
        for coin in coin_list:
            raw = fetch_all_klines(COIN_MAP[coin], period_info["limit"], period_info["start_time"])
            da = raw[:period_info["limit"]] if period_info["start_time"] else raw[-period_info["limit"]:]
            r = backtest_coin(coin, da, t_min_long=tml, t_max_short=tms, **base)
            m = metrics(r)
            if not m.get("msg"):
                total_pnl += m["pnl"]; total_wr += m["wr"]; total_pf += m["pf"]
                total_dd += m["mdd"]; total_sh += m["sh"]; total_nt += m["n"]; nv += 1
        if nv:
            rows.append((label, total_pnl, total_wr/nv, total_pf/nv, total_dd/nv, total_sh/nv, total_nt))
            print(f"  {label:10s} | PnL={total_pnl:+8.2f}% | WR={total_wr/nv:4.0f}% | "
                  f"PF={total_pf/nv:<5.2f} | DD={total_dd/nv:5.1f}% | Sharpe={total_sh/nv:.2f} | Trades={total_nt}")
    return rows


def test3_paxg_stops(period_key, period_info):
    """Test PAXG with different leverage & stop loss."""
    print(f"\n{'='*70}")
    print(f"  TEST 3: PAXG — LEVERAGE & STOP LOSS OPTIMIZATION")
    print(f"  Period: {period_info['label']}")
    print(f"{'='*70}")
    base = dict(ma_fast=12, ma_slow=25, t_min_long=0, t_max_short=-3, vol_min=0.3)
    params = [
        (0.04, 0.80, 0.75, 1.5, "SL4_TR80_HS75_L1.5"),
        (0.04, 0.80, 0.75, 2.0, "SL4_TR80_HS75_L2"),
        (0.05, 0.80, 0.75, 2.0, "SL5_TR80_HS75_L2"),
        (0.06, 0.80, 0.75, 2.0, "SL6_TR80_HS75_L2"),
        (0.06, 0.80, 0.75, 2.5, "SL6_TR80_HS75_L2.5"),
        (0.06, 0.85, 0.78, 2.5, "SL6_TR85_HS78_L2.5"),
        (0.05, 0.80, 0.75, 2.5, "SL5_TR80_HS75_L2.5"),
        (0.04, 0.80, 0.75, 2.5, "SL4_TR80_HS75_L2.5"),
        (0.06, 0.80, 0.75, 3.0, "SL6_TR80_HS75_L3"),
        (0.05, 0.80, 0.75, 3.0, "SL5_TR80_HS75_L3"),
    ]
    for ml, tr, hs, lev, label in params:
        raw = fetch_all_klines(COIN_MAP["PAXG"], period_info["limit"], period_info["start_time"])
        da = raw[:period_info["limit"]] if period_info["start_time"] else raw[-period_info["limit"]:]
        r = backtest_coin("PAXG", da, ml=ml, tr=tr, hs=hs, lev=lev, **base)
        m = metrics(r)
        print(f"  {label:30s}", end="")
        print_m(m)


def test4_portfolio(period_key, period_info, coin_list, params, label):
    """Simulate portfolio: equal capital per coin."""
    print(f"\n{'='*70}")
    print(f"  TEST 4: PORTFOLIO SIMULATION — {label}")
    print(f"  Period: {period_info['label']} | Coins: {', '.join(coin_list)}")
    print(f"{'='*70}")
    results = []
    for coin in coin_list:
        raw = fetch_all_klines(COIN_MAP[coin], period_info["limit"], period_info["start_time"])
        da = raw[:period_info["limit"]] if period_info["start_time"] else raw[-period_info["limit"]:]
        r = backtest_coin(coin, da, **params)
        m = metrics(r)
        results.append((coin, r, m))
        print(f"  {coin:7s} ", end="")
        print_m(m)
    # Aggregate
    valid = [(c, r, m) for c, r, m in results if not m.get("msg")]
    if valid:
        tot_pnl = sum(m["pnl"] for _, _, m in valid)
        avg_wr = mean([m["wr"] for _, _, m in valid])
        avg_pf = mean([m["pf"] for _, _, m in valid])
        avg_mdd = mean([m["mdd"] for _, _, m in valid])
        avg_sh = mean([m["sh"] for _, _, m in valid])
        tot_nt = sum(m["n"] for _, _, m in valid)
        print(f"  {'─'*65}")
        print(f"  PORTFOLIO | PnL={tot_pnl:+8.2f}% | WR={avg_wr:4.0f}% | "
              f"PF={avg_pf:.2f} | DD={avg_mdd:5.1f}% | Sharpe={avg_sh:.2f} | Trades={tot_nt}")
        # 10K simulation
        initial = 10000
        final = initial * (1 + tot_pnl / 100 / len(valid))
        print(f"  10K → ${final:,.0f} (PnL: ${final - initial:+,.0f})")
    return results


def main():
    print(f"{'='*70}")
    print(f"  DETAILED V6 STRATEGY TESTS")
    print(f"{'='*70}")

    CORE_COINS = ["ETH", "BNB", "PAXG", "TRX", "SOL"]
    BTC_COINS = ["ETH", "BNB", "PAXG", "TRX", "BTC"]
    BOTH_COINS = ["ETH", "BNB", "PAXG", "TRX", "SOL", "BTC"]

    for pkey, pinfo in PERIODS.items():
        if pkey == "2021_2026":
            continue  # handle full period separately
        print(f"\n{'#'*70}")
        print(f"# {pinfo['label']}")
        print(f"{'#'*70}")

        test1_long_short(pkey, pinfo)
        test2_entry_threshold(pkey, pinfo, CORE_COINS)
        test2_entry_threshold(pkey, pinfo, BTC_COINS)
        test3_paxg_stops(pkey, pinfo)

    # Config A: SOL coins, T0_-3, default stops (current + tighter trail/hard)
    cfg_a = dict(ma_fast=12, ma_slow=25, t_min_long=0, t_max_short=-3,
                 vol_min=0.3, ml=0.06, tr=0.80, hs=0.75, lev=2.5)
    # Config B: BTC coins, T0_-3
    cfg_b = dict(ma_fast=12, ma_slow=25, t_min_long=0, t_max_short=-3,
                 vol_min=0.3, ml=0.06, tr=0.80, hs=0.75, lev=2.5)

    # Full run: 2021-2026
    print(f"\n{'#'*70}")
    print(f"# FULL PERIOD: 2021–2026")
    print(f"# Config: MA12_25 T0_-3 V0.3 SL6 TR80 HS75 L2.5")
    print(f"{'#'*70}")

    print(f"\n--- Coin list: SOL (current) ---")
    test4_portfolio("2021_2026", PERIODS["2021_2026"], CORE_COINS, cfg_a, "SOL coins")
    print(f"\n--- Coin list: SOL→BTC ---")
    test4_portfolio("2021_2026", PERIODS["2021_2026"], BTC_COINS, cfg_b, "BTC replaces SOL")


if __name__ == "__main__":
    main()
