#!/usr/bin/env python3
"""Compare v11 (3SL Separated + Sideway Filter) vs Baseline v10.

v10: Direction-specific cooldown only
v11: v10 + 3SL Rolling Lock (separated) + Sideway<3 filter
"""

import sys, os, json
from datetime import datetime as dt_cls, timezone
from statistics import mean, stdev

sys.path.insert(0, 'scripts')
from crypto_trading import (
    sma, evaluate_trend_3d, compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long, _entry_score_v7_short,
    get_coin_profile, compute_rsi, compute_sideway_score,
)

SF = 2.0; AGGR_N = 2
TMA_F, TMA_M, TMA_S = 7, 14, 28
BASE = 10000; ENTRY_MIN = 65; MAX_POS_PCT = 0.65; INITIAL = 75
FIB_MIN = 2
TP = [(8.0, 0.10), (15.0, 0.15), (25.0, 0.20), (40.0, 0.25)]
FEE_RATE = 0.0005

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_klines_12h_5y.json")
with open(CACHE) as f:
    _cache = json.load(f)

PROFILES_BULL = {
    "ETH": {"lev": 2.5, "sl": 10, "cap": 2.5, "trail": 0.04, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "rsi_max_long": 65, "pos_mult": 1.0},
    "BNB": {"lev": 3.5, "sl": 12, "cap": 2.8, "trail": 0.065, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 1.0},
    "TRX": {"lev": 3.5, "sl": 12, "cap": 2.5, "trail": 0.065, "cd": 5,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 1.0},
}
PROFILES_BEAR = {
    "ETH": {"lev": 2.0, "sl": 8, "cap": 2.5, "trail": 0.04, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "rsi_max_long": 65, "pos_mult": 0.90},
    "BNB": {"lev": 2.0, "sl": 10, "cap": 2.8, "trail": 0.065, "cd": 0,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 0.75},
    "TRX": {"lev": 2.0, "sl": 8, "cap": 2.5, "trail": 0.065, "cd": 5,
             "e_strong": 0.09, "e_weak": 0.07, "pos_mult": 0.75},
}
SHORT_COINS = {"ETH", "TRX"}

# v11 config
SL_ROLLING_CAP = 3
SL_ROLLING_LOCK_BARS = 8
SL_ROLLING_FIB = True
SIDEWAY_MAX_SCORE = 2


def fib_bars(n, shift=0):
    if n < FIB_MIN: return 0
    a, b = 1, 1
    for _ in range(n + 1 + shift): a, b = b, a + b
    return a

def fetch(s): return _cache.get(s + '_4000_1609434000000', [])
def aggr(c, n=3):
    r = []
    for i in range(0, len(c) - n + 1, n):
        b = c[i:i + n]
        if len(b) < n: continue
        r.append({'open_time': b[0]['open_time'], 'open': b[0]['open'],
            'high': max(x['high'] for x in b), 'low': min(x['low'] for x in b),
            'close': b[-1]['close'], 'volume': sum(x['volume'] for x in b)})
    return r

def btc_bull(idx, da):
    c1 = [c['close'] for c in da[:idx + 1]]
    if len(c1) < int(200 * SF): return True
    return (sma(c1, int(50 * SF))[-1] or c1[-1]) > (sma(c1, int(200 * SF))[-1] or c1[-1])


def run_backtest(enable_v11_features=True):
    """Run backtest with or without v11 features."""
    results = {}
    
    for coin in ["ETH", "BNB", "TRX"]:
        prof = dict(get_coin_profile(coin))
        da = fetch(coin + "USDT")
        if not da: continue
        allow_short = coin in SHORT_COINS

        entries = []; eq = 1.0; curve = []; trades = []; lei = -999
        yearly_eq = {}
        consec_l = 0; consec_s = 0
        cd_l_until = -999; cd_s_until = -999
        
        # v11: Rolling SL tracker
        rolling_sl_long = 0
        rolling_sl_short = 0
        rolling_lock_until_long = -999
        rolling_lock_until_short = -999

        for idx in range(INITIAL, len(da)):
            ds = da[:idx + 1]; ct = aggr(ds, AGGR_N)
            if len(ct) < 25: continue
            cc = ds[-1]['close']; bh = ds[-1]['high']; bl = ds[-1]['low']
            cl = [c['close'] for c in ct]
            mf = sma(cl, TMA_F)[-1] or cl[-1]
            mm = sma(cl, TMA_M)[-1] or cl[-1]
            ms = sma(cl, TMA_S)[-1] or cl[-1]
            _, ts = evaluate_trend_3d(mf, mm, ms)
            c1 = [c['close'] for c in ds]; v1 = [c['volume'] for c in ds]
            ef = sma(c1, 18)[-1] or c1[-1]; em = sma(c1, 37)[-1] or c1[-1]
            es = sma(c1, 30)[-1] or c1[-1]
            ma7 = sma(c1, int(7*SF))[-1] or c1[-1]
            ma10 = sma(c1, int(10*SF))[-1] or c1[-1]
            ma200 = sma(c1, int(200*SF))[-1] or None
            vm2 = sma(v1, int(20*SF))[-1] or v1[-1]
            v5a = sum(v1[-(int(6*SF)):-1])/(int(5*SF)) if len(v1)>=int(6*SF) else v1[-1]
            vs = compute_volume_score(v1[-1], vm2)
            rsi1 = compute_rsi(c1, int(14*SF))
            dt_val = ds[-1]['open_time']
            is_bull = btc_bull(idx, da)
            p = PROFILES_BULL[coin] if is_bull else PROFILES_BEAR[coin]
            lev = p["lev"]; sl_val = p["sl"]; cm = p["cap"]
            tr_rate = p["trail"]; cd = p["cd"]
            e_strong = p["e_strong"]; e_weak = p["e_weak"]
            pos_mult = p.get("pos_mult", 1.0)
            max_ms = MAX_POS_PCT / lev * pos_mult; tc = BASE * cm

            ne = []
            for ent in entries:
                ep = ent['ep']; mp = ent['mp']; tp_s = ent['tp']
                rem2 = ent['rem']; hi = ent['hi']; tstop = ent['tstop']
                is_sh = ent.get('is_short', False)
                ent_lev = ent.get('lev', lev); ent_sl = ent.get('sl', sl_val)
                ent_ff = 1 - 2 * FEE_RATE * ent_lev

                if not is_sh: raw_roi = ((cc-ep)/ep*100)*mp*tc*ent_lev/BASE
                else: raw_roi = ((ep-cc)/ep*100)*mp*tc*ent_lev/BASE
                sl_mult = mp*tc*ent_lev/BASE; sl_pct = ent_sl/sl_mult/100 if sl_mult>0 else 1.0

                intrabar = False
                if not is_sh:
                    sl_p = ep*(1-sl_pct)
                    if bl <= sl_p:
                        sl_roi = ((sl_p-ep)/ep*100)*mp*tc*ent_lev/BASE
                        eq += sl_roi*rem2/100*ent_ff
                        trades.append({'t':'SL','dir':'L','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                        intrabar = True
                else:
                    sl_p = ep*(1+sl_pct)
                    if bh >= sl_p:
                        sl_roi = ((ep-sl_p)/ep*100)*mp*tc*ent_lev/BASE
                        eq += sl_roi*rem2/100*ent_ff
                        trades.append({'t':'SL','dir':'S','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                        intrabar = True

                if intrabar:
                    if is_sh:
                        consec_s += 1; cd_f = fib_bars(consec_s)
                        if cd_f > 0: cd_s_until = idx + cd_f
                    else:
                        consec_l += 1; cd_f = fib_bars(consec_l)
                        if cd_f > 0: cd_l_until = idx + cd_f
                    
                    # v11: Rolling SL counter
                    if enable_v11_features:
                        if is_sh:
                            rolling_sl_short += 1
                            if rolling_sl_short >= SL_ROLLING_CAP:
                                lock_bars = SL_ROLLING_LOCK_BARS
                                if SL_ROLLING_FIB:
                                    extra = rolling_sl_short - SL_ROLLING_CAP
                                    lock_bars = fib_bars(SL_ROLLING_CAP + extra)
                                rolling_lock_until_short = idx + lock_bars
                        else:
                            rolling_sl_long += 1
                            if rolling_sl_long >= SL_ROLLING_CAP:
                                lock_bars = SL_ROLLING_LOCK_BARS
                                if SL_ROLLING_FIB:
                                    extra = rolling_sl_long - SL_ROLLING_CAP
                                    lock_bars = fib_bars(SL_ROLLING_CAP + extra)
                                rolling_lock_until_long = idx + lock_bars
                    continue

                if not is_sh:
                    if cc > hi: hi = cc; ent['hi'] = hi
                else:
                    if cc < hi: hi = cc; ent['hi'] = hi
                rm = False

                if raw_roi <= -ent_sl:
                    eq += raw_roi*rem2/100*ent_ff
                    trades.append({'t':'SL','dir':'S' if is_sh else 'L','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                    rm = True
                    if is_sh:
                        consec_s += 1; cd_f = fib_bars(consec_s)
                        if cd_f > 0: cd_s_until = idx + cd_f
                    else:
                        consec_l += 1; cd_f = fib_bars(consec_l)
                        if cd_f > 0: cd_l_until = idx + cd_f
                    
                    # v11: Rolling SL counter
                    if enable_v11_features:
                        if is_sh:
                            rolling_sl_short += 1
                            if rolling_sl_short >= SL_ROLLING_CAP:
                                lock_bars = SL_ROLLING_LOCK_BARS
                                if SL_ROLLING_FIB:
                                    extra = rolling_sl_short - SL_ROLLING_CAP
                                    lock_bars = fib_bars(SL_ROLLING_CAP + extra)
                                rolling_lock_until_short = idx + lock_bars
                        else:
                            rolling_sl_long += 1
                            if rolling_sl_long >= SL_ROLLING_CAP:
                                lock_bars = SL_ROLLING_LOCK_BARS
                                if SL_ROLLING_FIB:
                                    extra = rolling_sl_long - SL_ROLLING_CAP
                                    lock_bars = fib_bars(SL_ROLLING_CAP + extra)
                                rolling_lock_until_long = idx + lock_bars

                elif tp_s < len(TP):
                    trg, cpct = TP[tp_s]
                    if raw_roi >= trg:
                        cf = cpct*rem2; eq += raw_roi*cf/100*ent_ff
                        rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                        if is_sh: consec_s = 0
                        else: consec_l = 0
                        # v11: Win resets rolling SL
                        if enable_v11_features:
                            if is_sh: rolling_sl_short = 0
                            else: rolling_sl_long = 0
                        trades.append({'t':'TP','dir':'S' if is_sh else 'L','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                        if ent['tp'] >= len(TP):
                            ent['tstop'] = cc*(1-tr_rate) if not is_sh else cc*(1+tr_rate)

                if tp_s >= len(TP) and not rm:
                    if not is_sh:
                        if tstop is None: tstop = cc*(1-tr_rate)
                        tstop = max(tstop, hi*(1-tr_rate)); ent['tstop'] = tstop
                        if bl <= tstop:
                            eq += raw_roi*rem2/100*ent_ff
                            trades.append({'t':'TRAIL','dir':'L','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                            rm = True; consec_l = 0
                            if enable_v11_features: rolling_sl_long = 0
                    else:
                        if tstop is None: tstop = cc*(1+tr_rate)
                        tstop = min(tstop, hi*(1+tr_rate)); ent['tstop'] = tstop
                        if bh >= tstop:
                            eq += raw_roi*rem2/100*ent_ff
                            trades.append({'t':'TRAIL','dir':'S','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                            rm = True; consec_s = 0
                            if enable_v11_features: rolling_sl_short = 0

                if is_sh and not rm and ts >= 2:
                    eq += raw_roi*rem2/100*ent_ff
                    trades.append({'t':'TREND_REV','dir':'S','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                    rm = True
                    if raw_roi > 0:
                        consec_s = 0
                        if enable_v11_features: rolling_sl_short = 0
                    else:
                        consec_s += 1; cd_f = fib_bars(consec_s)
                        if cd_f > 0: cd_s_until = idx + cd_f
                        if enable_v11_features:
                            rolling_sl_short += 1
                            if rolling_sl_short >= SL_ROLLING_CAP:
                                lock_bars = SL_ROLLING_LOCK_BARS
                                if SL_ROLLING_FIB:
                                    extra = rolling_sl_short - SL_ROLLING_CAP
                                    lock_bars = fib_bars(SL_ROLLING_CAP + extra)
                                rolling_lock_until_short = idx + lock_bars

                if not is_sh and not rm and ts <= -2:
                    eq += raw_roi*rem2/100*ent_ff
                    trades.append({'t':'TREND_REV','dir':'L','yr':dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc).year})
                    rm = True
                    if raw_roi > 0:
                        consec_l = 0
                        if enable_v11_features: rolling_sl_long = 0
                    else:
                        consec_l += 1; cd_f = fib_bars(consec_l)
                        if cd_f > 0: cd_l_until = idx + cd_f
                        if enable_v11_features:
                            rolling_sl_long += 1
                            if rolling_sl_long >= SL_ROLLING_CAP:
                                lock_bars = SL_ROLLING_LOCK_BARS
                                if SL_ROLLING_FIB:
                                    extra = rolling_sl_long - SL_ROLLING_CAP
                                    lock_bars = fib_bars(SL_ROLLING_CAP + extra)
                                rolling_lock_until_long = idx + lock_bars

                if not rm: ne.append(ent)
            entries = ne

            dep = sum(e['mp'] for e in entries)
            can_l = dep < max_ms and (idx - lei >= cd) and (idx > cd_l_until)
            can_s = dep < max_ms and (idx - lei >= cd) and (idx > cd_s_until)
            
            # v11: Rolling lock check
            if enable_v11_features:
                if can_l and idx <= rolling_lock_until_long:
                    can_l = False
                if can_s and idx <= rolling_lock_until_short:
                    can_s = False
            
            # v11: Sideway filter
            if enable_v11_features and (can_l or can_s):
                sideway_score = compute_sideway_score(ds, SF)
                if sideway_score > SIDEWAY_MAX_SCORE:
                    can_l = False
                    can_s = False
            
            has_l = any(not e.get('is_short',False) for e in entries)
            has_s = any(e.get('is_short',False) for e in entries)

            if can_l or can_s:
                el = compute_entry_v6_long(ts,rsi1,cc,es,em,ef,vs,
                    trend_min=prof['trend_min_long'],vol_min=prof['vol_min'],
                    rsi_max=prof.get('rsi_max_long',90),ma7_1d=ma7,ma200_1d=ma200,
                    last_volume=v1[-1],vol_5d_avg=v5a,
                    use_ma200_filter=False,use_pullback_filter=False,
                    use_volume_expan=False,min_entry_score=ENTRY_MIN) if can_l else False
                es_ = compute_entry_v6_short(ts,rsi1,cc,es,em,ef,vs,
                    trend_max=prof.get('trend_max_short',-2),vol_min=prof['vol_min'],
                    rsi_min=prof.get('rsi_min_short',10),
                    ma7_1d=ma7,ma10_1d=ma10,ma200_1d=ma200,
                    last_volume=v1[-1],vol_5d_avg=v5a,
                    use_ma200_filter=False,use_pullback_filter=False,
                    use_volume_expan=False,
                    min_entry_score=prof.get('short_min_entry_score',ENTRY_MIN),
                    candles_12h=ds) if (allow_short and can_s) else False
                if el and has_s: el = False
                if es_ and has_l: es_ = False
                ps_, act = resolve_action_v6(ts, el, es_, 'FLAT')
                if act in ('OPEN_LONG_ENTRY_1','OPEN_SHORT_ENTRY_1'):
                    is_sh = act.startswith('OPEN_SHORT')
                    if is_sh: sc = _entry_score_v7_short(ts,cc,ma7,ma10,es,ma200,ef,em,vs,v1[-1],v5a,rsi1,ds)
                    else: sc = _entry_score_v7_long(ts,cc,ma7,ma10,es,ma200,ef,em,vs,v1[-1],v5a,rsi1)
                    strong = sc >= ENTRY_MIN
                    mp = e_strong if strong else e_weak
                    mp *= pos_mult
                    if dep + mp <= max_ms + 0.001:
                        entries.append({'ep':cc,'mp':mp,'tp':0,'rem':1.0,'hi':cc,
                            'tstop':None,'is_short':is_sh,'lev':lev,'sl':sl_val})
                        lei = idx

            ureal = 0
            for e in entries:
                e_lev = e.get('lev', lev)
                if not e.get('is_short',False): ureal += ((cc-e['ep'])/e['ep']*100)*e['mp']*tc*e_lev/BASE*e['rem']/100
                else: ureal += ((e['ep']-cc)/e['ep']*100)*e['mp']*tc*e_lev/BASE*e['rem']/100
            total_eq = eq + ureal; curve.append(total_eq)
            d = dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc)
            if d.month == 12: yearly_eq[d.year] = total_eq

        slc = sum(1 for t in trades if t['t']=='SL')
        tpc = sum(1 for t in trades if t['t'] in ('TP','TRAIL'))
        tot = slc+tpc; slr = slc/tot*100 if tot else 0
        peak = curve[0] if curve else eq; md = 0
        for v in curve:
            if v > peak: peak = v
            dd = (peak-v)/peak*100
            if dd > md: md = dd
        years = len(curve)/2/365 if curve else 1
        teq = curve[-1] if curve else eq
        cagr = ((teq**(1/years)-1)*100) if years>0 and teq>0 else 0
        
        yearly_returns = {}
        prev = 1.0
        for y in range(2021, 2026):
            ev = yearly_eq.get(y, prev)
            yearly_returns[y] = ((ev/prev)-1)*100 if prev > 0 else 0
            prev = ev
        
        results[coin] = dict(cagr=cagr, dd=md, slr=slr, yearly=yearly_returns)
    
    return results


def main():
    print("=" * 100)
    print("  PERFORMANCE COMPARISON: v10 (Baseline) vs v11 (3SL Separated + Sideway Filter)")
    print("=" * 100)
    
    # Run v10 baseline
    print("\n[1/2] Running v10 Baseline (direction-specific cooldown only)...")
    v10_results = run_backtest(enable_v11_features=False)
    
    # Run v11 with new features
    print("[2/2] Running v11 (3SL Separated + Sideway Filter)...")
    v11_results = run_backtest(enable_v11_features=True)
    
    # Comparison table
    print("\n" + "=" * 100)
    print("  RESULTS COMPARISON")
    print("=" * 100)
    print(f"{'Metric':<20} {'v10 Baseline':>15} {'v11 (3SL+SW)':>15} {'Change':>10}")
    print("-" * 100)
    
    # Aggregate metrics
    v10_avg_cagr = mean(v10_results[c]['cagr'] for c in ["ETH","BNB","TRX"])
    v11_avg_cagr = mean(v11_results[c]['cagr'] for c in ["ETH","BNB","TRX"])
    v10_avg_dd = mean(v10_results[c]['dd'] for c in ["ETH","BNB","TRX"])
    v11_avg_dd = mean(v11_results[c]['dd'] for c in ["ETH","BNB","TRX"])
    v10_avg_slr = mean(v10_results[c]['slr'] for c in ["ETH","BNB","TRX"])
    v11_avg_slr = mean(v11_results[c]['slr'] for c in ["ETH","BNB","TRX"])
    
    # StdDev
    v10_yearly = []
    v11_yearly = []
    for coin in ["ETH","BNB","TRX"]:
        for y in range(2021, 2026):
            v10_yearly.append(v10_results[coin]['yearly'].get(y, 0))
            v11_yearly.append(v11_results[coin]['yearly'].get(y, 0))
    v10_std = stdev(v10_yearly)
    v11_std = stdev(v11_yearly)
    
    print(f"{'Avg CAGR':<20} {v10_avg_cagr:>+14.1f}% {v11_avg_cagr:>+14.1f}% {v11_avg_cagr-v10_avg_cagr:>+9.1f}%")
    print(f"{'Avg DD':<20} {v10_avg_dd:>14.1f}% {v11_avg_dd:>14.1f}% {v11_avg_dd-v10_avg_dd:>+9.1f}%")
    print(f"{'Avg SLr':<20} {v10_avg_slr:>14.1f}% {v11_avg_slr:>14.1f}% {v11_avg_slr-v10_avg_slr:>+9.1f}%")
    print(f"{'StdDev':<20} {v10_std:>14.1f}% {v11_std:>14.1f}% {v11_std-v10_std:>+9.1f}%")
    
    # Per-coin comparison
    print("\n" + "=" * 100)
    print("  PER-COIN COMPARISON")
    print("=" * 100)
    
    for coin in ["ETH", "BNB", "TRX"]:
        v10 = v10_results[coin]
        v11 = v11_results[coin]
        print(f"\n{coin}:")
        print(f"  CAGR: {v10['cagr']:>+7.1f}% → {v11['cagr']:>+7.1f}% (Δ {v11['cagr']-v10['cagr']:>+.1f}%)")
        print(f"  DD:   {v10['dd']:>7.1f}% → {v11['dd']:>7.1f}% (Δ {v11['dd']-v10['dd']:>+.1f}%)")
        print(f"  SLr:  {v10['slr']:>7.1f}% → {v11['slr']:>7.1f}% (Δ {v11['slr']-v10['slr']:>+.1f}%)")
        
        # Yearly breakdown
        print(f"  Yearly:")
        for y in range(2021, 2026):
            v10_yr = v10['yearly'].get(y, 0)
            v11_yr = v11['yearly'].get(y, 0)
            marker = " ← " if y == 2024 and coin == "ETH" else ""
            print(f"    {y}: {v10_yr:>+7.1f}% → {v11_yr:>+7.1f}% (Δ {v11_yr-v10_yr:>+.1f}%){marker}")
    
    # Summary
    print("\n" + "=" * 100)
    print("  SUMMARY")
    print("=" * 100)
    
    eth_2024_v10 = v10_results['ETH']['yearly'].get(2024, 0)
    eth_2024_v11 = v11_results['ETH']['yearly'].get(2024, 0)
    
    print(f"\n✅ ETH 2024 (key metric):")
    print(f"   v10: {eth_2024_v10:>+.1f}%")
    print(f"   v11: {eth_2024_v11:>+.1f}%")
    print(f"   Improvement: {eth_2024_v11-eth_2024_v10:>+.1f}%")
    
    print(f"\n✅ Overall Performance:")
    print(f"   CAGR: {v10_avg_cagr:>+.1f}% → {v11_avg_cagr:>+.1f}% (Δ {v11_avg_cagr-v10_avg_cagr:>+.1f}%)")
    print(f"   SLr:  {v10_avg_slr:>5.1f}% → {v11_avg_slr:>5.1f}% (Δ {v11_avg_slr-v10_avg_slr:>+.1f}%)")
    print(f"   DD:   {v10_avg_dd:>5.1f}% → {v11_avg_dd:>5.1f}% (Δ {v11_avg_dd-v10_avg_dd:>+.1f}%)")
    
    print(f"\n✅ v11 Features Applied:")
    print(f"   • 3SL Rolling Fibonacci Lock (Separated per direction)")
    print(f"     - 3 consecutive SLs → lock 8 bars (Fibonacci: 3→8, 4→13, 5→21)")
    print(f"     - Long SL only locks Long, not Short (and vice versa)")
    print(f"   • Sideway Filter (Score 0-4)")
    print(f"     - Skip entry if sideway_score > 2 (consolidation detected)")
    print(f"     - Indicators: MA spread, Slope20, Volume ratio, Range%")
    
    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
