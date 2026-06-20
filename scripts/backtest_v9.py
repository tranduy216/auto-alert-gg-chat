#!/usr/bin/env python3
"""v9 strategy: isolated entries, 180% capital cap, partial TP, trailing, 3x/2.5x leverage."""
import sys, os, json
from datetime import datetime, timedelta
from statistics import mean
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_trading import (
    sma, compute_rsi, evaluate_trend_3d, trend_strength,
    compute_volume_score, compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long, compute_atr,
    get_coin_profile, SHORT_ALLOWED,
    SF, TREND_MA_FAST, TREND_MA_MID, TREND_MA_SLOW,
    EXEC_MA_FAST, EXEC_MA_MID, EXEC_MA_SLOW,
    SHORT_COOLDOWN_LOSSES, SHORT_COOLDOWN_DAYS,
    LONG_COOLDOWN_LOSSES, LONG_COOLDOWN_DAYS,
)

# ── v9 Configuration ────────────────────────────────────────────────
BASE_CAPITAL = 10000
TOTAL_CAPITAL = BASE_CAPITAL * 1.8   # 18000
MAX_PER_COIN = TOTAL_CAPITAL * 0.8   # 14400

LOW_DD_COINS = {"ETH"}
HIGH_DD_COINS = {"BNB", "TRX"}
COINS = ["ETH", "BNB", "TRX"]
SYMBOL_MAP = {c: f"{c}USDT" for c in COINS}

def get_lev(coin): return 3.0 if coin in LOW_DD_COINS else 2.5
def get_sl(coin): return 0.07 if coin in LOW_DD_COINS else 0.09
def get_trail_rate(coin): return 0.035 if coin in LOW_DD_COINS else 0.065
def get_entry_size(coin, strong): 
    if coin in LOW_DD_COINS:
        return 0.09 if strong else 0.07
    return 0.07 if strong else 0.055

TP_SCHEDULE = [(7.0, 0.07), (12.0, 0.11), (20.0, 0.20), (30.0, 0.27)]  # (ROI%, close_pct)
TRAIL_TRIGGER_ROI = 30.0
TOTAL_TP_CLOSE = sum(c for _, c in TP_SCHEDULE)  # 0.65
REMAINING_AFTER_TP = 1.0 - TOTAL_TP_CLOSE         # 0.35

START = int(datetime(2021, 1, 1).timestamp() * 1000)
LIMIT = 4000

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
_cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f: _cache = json.load(f)

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

def roi_of_entry(entry_price, current_price, margin_pct, lev, is_short):
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if not is_short \
              else ((entry_price - current_price) / entry_price * 100)
    return pnl_pct * margin_pct * TOTAL_CAPITAL * lev / BASE_CAPITAL

print(f"{'='*100}")
print(f"  v9 STRATEGY BACKTEST — Isolated entries, partial TP, trailing, 3x/2.5x leverage")
print(f"  Base=${BASE_CAPITAL:,} | Total=${TOTAL_CAPITAL:,.0f} | Max/coin=${MAX_PER_COIN:,.0f}")
print(f"  ETH(3x/7%sl/3.5%trail) BNB(2.5x/9%sl/6.5%trail) TRX(2.5x/9%sl/6.5%trail)")
print(f"  TP: ROI 7%→7% | 12%→11% | 20%→20% | 30%→27% | 35% trailing")
print(f"  SF={SF} | Trend MA{TREND_MA_FAST}/{TREND_MA_MID}/{TREND_MA_SLOW} | Exec MA{EXEC_MA_FAST}/{EXEC_MA_MID}/{EXEC_MA_SLOW}")
print(f"{'='*100}")

all_results = {}

for coin in COINS:
    profile = dict(get_coin_profile(coin))
    lev = get_lev(coin)
    sl_roi_pct = get_sl(coin)     # ROI-based stop loss
    trail_rate = get_trail_rate(coin)

    short_loss_streak = 0; short_cooldown_until = None
    long_loss_streak = 0; long_cooldown_until = None

    entries = []
    trades_log = []
    eq = 1.0         # multiplier on BASE_CAPITAL
    equity_curve = []
    yearly_eq = {}
    da = fetch(SYMBOL_MAP[coin], LIMIT, START)
    INITIAL = 25 * 3

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
        dt = ds[-1]["open_time"]

        # ── Process active entries ──
        new_entries = []
        for ent in entries:
            ep = ent["entry_price"]
            mp = ent["margin_pct"]
            is_sh = ent["is_short"]
            tp_stage = ent["tp_stage"]
            rem_sz = ent["remaining_size"]
            highest = ent["highest_since_entry"]
            trail_stop = ent["trailing_stop"]

            roi = roi_of_entry(ep, cc, mp, lev, is_sh)

            if not is_sh and cc > highest: highest = cc
            if is_sh and cc < highest: highest = cc
            ent["highest_since_entry"] = highest

            removed = False

            # ── Stop loss (ROI-based) ──
            if roi <= -sl_roi_pct:
                eq += roi * rem_sz / 100  # roi is % of base capital
                trades_log.append({"type": "SL", "pnl_roi": roi, "reason": f"SL -{sl_roi_pct}% ROI"})
                if is_sh:
                    short_loss_streak += 1
                    if short_loss_streak >= SHORT_COOLDOWN_LOSSES:
                        short_cooldown_until = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=SHORT_COOLDOWN_DAYS)
                else:
                    long_loss_streak += 1
                    if long_loss_streak >= LONG_COOLDOWN_LOSSES:
                        long_cooldown_until = datetime.utcfromtimestamp(dt / 1000) + timedelta(days=LONG_COOLDOWN_DAYS)
                removed = True

            # ── Partial TP ──
            elif tp_stage < len(TP_SCHEDULE):
                target_roi, close_pct = TP_SCHEDULE[tp_stage]
                if roi >= target_roi:
                    cf = close_pct * rem_sz
                    eq += roi * cf / 100
                    rem_sz -= cf
                    ent["remaining_size"] = rem_sz
                    ent["tp_stage"] = tp_stage + 1
                    trades_log.append({"type": f"TP{tp_stage+1}", "pnl_roi": roi, "reason": f"TP ROI {target_roi}%"})
                    if ent["tp_stage"] >= len(TP_SCHEDULE):
                        ent["trailing_stop"] = cc * (1 - trail_rate) if not is_sh else cc * (1 + trail_rate)

            # ── Trailing stop (after all TPs) ──
            if tp_stage >= len(TP_SCHEDULE) and not removed:
                if not is_sh:
                    if trail_stop is None:
                        trail_stop = cc * (1 - trail_rate)
                    trail_stop = max(trail_stop, highest * (1 - trail_rate))
                    ent["trailing_stop"] = trail_stop
                    if cc <= trail_stop:
                        eq += roi * rem_sz / 100
                        trades_log.append({"type": "TRAIL", "pnl_roi": roi, "reason": "trailing stop"})
                        removed = True
                else:
                    if trail_stop is None:
                        trail_stop = cc * (1 + trail_rate)
                    trail_stop = min(trail_stop, highest * (1 + trail_rate))
                    ent["trailing_stop"] = trail_stop
                    if cc >= trail_stop:
                        eq += roi * rem_sz / 100
                        trades_log.append({"type": "TRAIL", "pnl_roi": roi, "reason": "trailing stop"})
                        removed = True

            if not removed:
                new_entries.append(ent)

        entries = new_entries

        # ── Entry check ──
        deployed = sum(e["margin_pct"] for e in entries)
        current_max = MAX_PER_COIN / TOTAL_CAPITAL
        can_enter = deployed < current_max

        if can_enter:
            lok = long_cooldown_until is None or dt >= int(long_cooldown_until.timestamp() * 1000) if long_cooldown_until else True
            sok = coin in SHORT_ALLOWED
            if sok and short_cooldown_until:
                cd_ms = int(short_cooldown_until.timestamp() * 1000) if hasattr(short_cooldown_until, "timestamp") else int(short_cooldown_until)
                if dt < cd_ms: sok = False

            el = compute_entry_v6_long(ts, rsi1, cc, e_s, e_m, e_f, vs_,
                trend_min=profile["trend_min_long"], vol_min=profile["vol_min"],
                rsi_max=profile.get("rsi_max_long", 90),
                ma7_1d=ma7, ma200_1d=ma200, last_volume=v1[-1], vol_5d_avg=v5a,
                use_ma200_filter=False, use_pullback_filter=False,
                use_volume_expan=False,
                min_entry_score=profile.get("min_entry_score", 0)) if lok else False

            es = compute_entry_v6_short(ts, rsi1, cc, e_s, e_m, e_f, vs_,
                trend_max=profile["trend_max_short"], vol_min=profile["vol_min"],
                rsi_min=profile.get("rsi_min_short", 10)) if sok else False

            ps_, act = resolve_action_v6(ts, el, es, "FLAT")
            if act in ("OPEN_LONG_ENTRY_1", "OPEN_SHORT_ENTRY_1"):
                is_sh = act.startswith("OPEN_SHORT")
                sc = _entry_score_v7_long(ts, cc, ma7, ma10, e_s, ma200, e_f, e_m, vs_, v1[-1], v5a, rsi1)
                strong = sc >= 65
                margin_pct = get_entry_size(coin, strong)

                if deployed + margin_pct <= current_max + 0.001:
                    entries.append({
                        "entry_price": cc,
                        "margin_pct": margin_pct,
                        "is_short": is_sh,
                        "tp_stage": 0,
                        "remaining_size": 1.0,
                        "highest_since_entry": cc,
                        "trailing_stop": None,
                    })
                    if not is_sh:
                        long_loss_streak = 0; long_cooldown_until = None
                    else:
                        short_loss_streak = 0; short_cooldown_until = None

        # ── Equity curve ──
        unrealized = 0.0
        for ent in entries:
            roi = roi_of_entry(ent["entry_price"], cc, ent["margin_pct"], lev, ent["is_short"])
            unrealized += roi * ent["remaining_size"] / 100
        total_eq = eq + unrealized
        equity_curve.append(total_eq)
        date = datetime.utcfromtimestamp(dt / 1000)
        if date.month == 12:
            yearly_eq[date.year] = total_eq

    if not trades_log:
        print(f"  {coin:6s} | No trades")
        continue

    closes = [t for t in trades_log if t["type"] in ("SL", "TRAIL", "TP1")]
    tp_trades = [t for t in trades_log if t["type"].startswith("TP")]
    trail_trades = [t for t in trades_log if t["type"] == "TRAIL"]
    sl_trades = [t for t in trades_log if t["type"] == "SL"]

    # CAGR & DD
    peak = equity_curve[0] if equity_curve else eq; md = 0
    for v in equity_curve:
        if v > peak: peak = v
        dd_val = (peak - v) / peak * 100
        if dd_val > md: md = dd_val
    years = len(equity_curve) / 2 / 365 if equity_curve else 1
    cagr = ((total_eq ** (1 / years) - 1) * 100) if years > 0 and total_eq > 0 else 0
    final = total_eq * BASE_CAPITAL

    # Win rate
    all_pnl = [t.get("pnl_roi", 0) for t in trades_log]
    wins = [p for p in all_pnl if p > 0]
    losses = [p for p in all_pnl if p <= 0]
    wr = len(wins) / len(all_pnl) * 100 if all_pnl else 0
    aw = mean(wins) if wins else 0; al = mean(losses) if losses else 0
    pf = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")

    all_results[coin] = {"cagr": cagr, "dd": md, "pf": pf, "trades": len(trades_log),
                         "tp": len(tp_trades), "sl": len(sl_trades), "trail": len(trail_trades),
                         "wr": wr, "aw": aw, "al": al, "final": final, "yearly_eq": yearly_eq}

    print(f"  {coin:6s} | {len(trades_log):>3d} events (TP:{len(tp_trades)} SL:{len(sl_trades)} Trail:{len(trail_trades)}) | CAGR={cagr:+5.1f}% | DD={md:+5.1f}% | PF={pf:.2f} | WR={wr:.0f}% | ${BASE_CAPITAL:,}->${final:,.0f}")

# Yearly table
print(f"\n{'='*100}")
print(f"  YEARLY CAGR")
print(f"  {'Coin':<6}", end="")
for yr in range(2021, 2026): print(f" {yr:>8}", end=" ")
print(f" {'5Y':>8}  {'DD':>8}")
print(f"  {'─'*75}")
for coin in COINS:
    r = all_results.get(coin)
    if not r: continue
    print(f"  {coin:<6}", end="")
    prev = 1.0
    for yr in range(2021, 2026):
        ev = r["yearly_eq"].get(yr, prev)
        c = ((ev / prev) - 1) * 100
        print(f" {c:+7.1f}%", end="")
        prev = ev
    print(f" {r['cagr']:+7.1f}% {r['dd']:+7.1f}%")

# Portfolio
print(f"\n{'='*100}")
total_final = sum(r["final"] for r in all_results.values())
avg_c = mean(r["cagr"] for r in all_results.values())
avg_d = mean(r["dd"] for r in all_results.values())
print(f"  PORTFOLIO | Avg CAGR={avg_c:+.1f}% | Avg DD={avg_d:.1f}% | ${len(COINS)*BASE_CAPITAL:,}->${total_final:,.0f}")
