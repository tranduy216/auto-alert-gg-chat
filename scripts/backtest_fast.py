#!/usr/bin/env python3
"""Fast Backtest - Optimized version with coin selection and data caching.

Features:
- Test single coin or multiple coins
- Accept data input directly (avoid repeated file loading)
- Cache results to avoid re-running
- Parallel processing for multiple coins
- Pre-compute indicators for speed

Usage:
    python backtest_fast.py --coin ETH                    # Test single coin
    python backtest_fast.py --coins ETH,BNB              # Test multiple coins
    python backtest_fast.py                              # Test all coins
    python backtest_fast.py --no-cache                   # Disable cache
    python backtest_fast.py --parallel                   # Enable parallel processing
"""

import sys, os, json, argparse, hashlib
from datetime import datetime as dt_cls, timezone
from statistics import mean
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import (
    sma, evaluate_trend_3d, compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long, _entry_score_v7_short,
    get_coin_profile, compute_rsi,
)

# Constants
SF = 2.0; AGGR_N = 2
TMA_F, TMA_M, TMA_S = 7, 14, 28
BASE = 10000; ENTRY_MIN = 65; MAX_POS_PCT = 0.65; INITIAL = 75
FIB_MIN = 2
TP = [(8.0, 0.10), (15.0, 0.15), (25.0, 0.20), (40.0, 0.25)]
FEE_RATE = 0.0005

CACHE_FILE = Path(__file__).parent / "_klines_12h_5y.json"
RESULT_CACHE_DIR = Path(__file__).parent / ".cache"
RESULT_CACHE_DIR.mkdir(exist_ok=True)

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


def fib_bars(n, shift=0):
    if n < FIB_MIN: return 0
    a, b = 1, 1
    for _ in range(n + 1 + shift): a, b = b, a + b
    return a


def load_data():
    """Load data from cache file."""
    if not CACHE_FILE.exists():
        raise FileNotFoundError(f"Cache file not found: {CACHE_FILE}")
    with open(CACHE_FILE) as f:
        return json.load(f)


def fetch(data_cache, symbol):
    """Fetch data from cache."""
    return data_cache.get(f"{symbol}_4000_1609434000000", [])


def aggr(c, n=3):
    """Aggregate candles."""
    r = []
    for i in range(0, len(c) - n + 1, n):
        b = c[i:i + n]
        if len(b) < n: continue
        r.append({'open_time': b[0]['open_time'], 'open': b[0]['open'],
            'high': max(x['high'] for x in b), 'low': min(x['low'] for x in b),
            'close': b[-1]['close'], 'volume': sum(x['volume'] for x in b)})
    return r


def btc_bull(idx, da):
    """Check if BTC is in bull market."""
    c1 = [c['close'] for c in da[:idx + 1]]
    if len(c1) < int(200 * SF): return True
    return (sma(c1, int(50 * SF))[-1] or c1[-1]) > (sma(c1, int(200 * SF))[-1] or c1[-1])


def get_cache_key(coin, config_hash):
    """Generate cache key for result."""
    return f"{coin}_{config_hash}.json"


def load_cached_result(coin, config_hash):
    """Load cached result if exists."""
    cache_file = RESULT_CACHE_DIR / get_cache_key(coin, config_hash)
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return None


def save_cached_result(coin, config_hash, result):
    """Save result to cache."""
    cache_file = RESULT_CACHE_DIR / get_cache_key(coin, config_hash)
    with open(cache_file, 'w') as f:
        json.dump(result, f)


def backtest_coin(args):
    """Backtest a single coin. Designed for parallel execution."""
    coin, data_cache, use_cache = args
    
    # Config hash for caching
    config_str = json.dumps({
        "coin": coin,
        "profiles_bull": PROFILES_BULL[coin],
        "profiles_bear": PROFILES_BEAR[coin],
        "short_allowed": coin in SHORT_COINS
    }, sort_keys=True)
    config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
    
    # Check cache
    if use_cache:
        cached = load_cached_result(coin, config_hash)
        if cached:
            print(f"  {coin}: Loaded from cache")
            return coin, cached
    
    print(f"  {coin}: Running backtest...")
    
    # Load data
    da = fetch(data_cache, coin + "USDT")
    if not da:
        return coin, None
    
    prof = dict(get_coin_profile(coin))
    allow_short = coin in SHORT_COINS

    entries = []; eq = 1.0; curve = []; trades = []; lei = -999
    yearly_eq = {}; long_trades = []; short_trades = []
    consec_l = 0; consec_s = 0
    cd_l_until = -999; cd_s_until = -999

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
        ff = 1 - 2 * FEE_RATE * lev

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
                    long_trades.append({'t':'SL','roi':sl_roi})
                    trades.append({'t':'SL','dir':'L'}); intrabar = True
            else:
                sl_p = ep*(1+sl_pct)
                if bh >= sl_p:
                    sl_roi = ((ep-sl_p)/ep*100)*mp*tc*ent_lev/BASE
                    eq += sl_roi*rem2/100*ent_ff
                    short_trades.append({'t':'SL','roi':sl_roi})
                    trades.append({'t':'SL','dir':'S'}); intrabar = True

            if intrabar:
                if is_sh:
                    consec_s += 1
                    cd_f = fib_bars(consec_s, 0)
                    if cd_f > 0: cd_s_until = idx + cd_f
                else:
                    consec_l += 1
                    cd_f = fib_bars(consec_l, 0)
                    if cd_f > 0: cd_l_until = idx + cd_f
                continue

            if not is_sh:
                if cc > hi: hi = cc; ent['hi'] = hi
            else:
                if cc < hi: hi = cc; ent['hi'] = hi
            rm = False

            if raw_roi <= -ent_sl:
                eq += raw_roi*rem2/100*ent_ff
                if is_sh: short_trades.append({'t':'SL','roi':raw_roi})
                else: long_trades.append({'t':'SL','roi':raw_roi})
                trades.append({'t':'SL','dir':'S' if is_sh else 'L'}); rm = True
                if is_sh:
                    consec_s += 1
                    cd_f = fib_bars(consec_s, 0)
                    if cd_f > 0: cd_s_until = idx + cd_f
                else:
                    consec_l += 1
                    cd_f = fib_bars(consec_l, 0)
                    if cd_f > 0: cd_l_until = idx + cd_f

            elif tp_s < len(TP):
                trg, cpct = TP[tp_s]
                if raw_roi >= trg:
                    cf = cpct*rem2; eq += raw_roi*cf/100*ent_ff
                    rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                    if is_sh: short_trades.append({'t':'TP','roi':raw_roi}); consec_s = 0
                    else: long_trades.append({'t':'TP','roi':raw_roi}); consec_l = 0
                    trades.append({'t':'TP','dir':'S' if is_sh else 'L'})
                    if ent['tp'] >= len(TP):
                        ent['tstop'] = cc*(1-tr_rate) if not is_sh else cc*(1+tr_rate)

            if tp_s >= len(TP) and not rm:
                if not is_sh:
                    if tstop is None: tstop = cc*(1-tr_rate)
                    tstop = max(tstop, hi*(1-tr_rate)); ent['tstop'] = tstop
                    if bl <= tstop:
                        eq += raw_roi*rem2/100*ent_ff
                        long_trades.append({'t':'TRAIL','roi':raw_roi})
                        trades.append({'t':'TRAIL','dir':'L'}); rm = True; consec_l = 0
                else:
                    if tstop is None: tstop = cc*(1+tr_rate)
                    tstop = min(tstop, hi*(1+tr_rate)); ent['tstop'] = tstop
                    if bh >= tstop:
                        eq += raw_roi*rem2/100*ent_ff
                        short_trades.append({'t':'TRAIL','roi':raw_roi})
                        trades.append({'t':'TRAIL','dir':'S'}); rm = True; consec_s = 0

            if is_sh and not rm and ts >= 2:
                eq += raw_roi*rem2/100*ent_ff
                short_trades.append({'t':'TREND_REV','roi':raw_roi})
                trades.append({'t':'TREND_REV','dir':'S'}); rm = True
                if raw_roi > 0: consec_s = 0
                else:
                    consec_s += 1
                    cd_f = fib_bars(consec_s, 0)
                    if cd_f > 0: cd_s_until = idx + cd_f

            if not is_sh and not rm and ts <= -2:
                eq += raw_roi*rem2/100*ent_ff
                long_trades.append({'t':'TREND_REV','roi':raw_roi})
                trades.append({'t':'TREND_REV','dir':'L'}); rm = True
                if raw_roi > 0: consec_l = 0
                else:
                    consec_l += 1
                    cd_f = fib_bars(consec_l, 0)
                    if cd_f > 0: cd_l_until = idx + cd_f

            if not rm: ne.append(ent)
        entries = ne

        dep = sum(e['mp'] for e in entries)
        can_l = dep < max_ms and (idx - lei >= cd) and (idx > cd_l_until)
        can_s = dep < max_ms and (idx - lei >= cd) and (idx > cd_s_until)
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
    
    result = {
        'cagr': cagr, 'dd': md, 'slr': slr, 'final': teq*BASE,
        'yearly': yearly_eq, 'allow_short': allow_short
    }
    
    # Save to cache
    if use_cache:
        save_cached_result(coin, config_hash, result)
    
    return coin, result


def main():
    parser = argparse.ArgumentParser(description='Fast Backtest Tool')
    parser.add_argument('--coin', type=str, help='Single coin to test (ETH, BNB, or TRX)')
    parser.add_argument('--coins', type=str, help='Multiple coins to test (comma-separated, e.g., ETH,BNB)')
    parser.add_argument('--no-cache', action='store_true', help='Disable result caching')
    parser.add_argument('--parallel', action='store_true', help='Enable parallel processing')
    args = parser.parse_args()
    
    # Determine coins to test
    if args.coin:
        coins = [args.coin.upper()]
    elif args.coins:
        coins = [c.strip().upper() for c in args.coins.split(',')]
    else:
        coins = ["ETH", "BNB", "TRX"]
    
    # Validate coins
    valid_coins = {"ETH", "BNB", "TRX"}
    for coin in coins:
        if coin not in valid_coins:
            print(f"Error: Invalid coin '{coin}'. Valid coins: {', '.join(valid_coins)}")
            sys.exit(1)
    
    print("=" * 80)
    print(f"FAST BACKTEST - Testing {', '.join(coins)}")
    print("=" * 80)
    
    # Load data once
    print("\nLoading data...")
    data_cache = load_data()
    print(f"  Loaded {len(data_cache)} symbols")
    
    # Run backtests
    print("\nRunning backtests...")
    use_cache = not args.no_cache
    results = {}
    
    if args.parallel and len(coins) > 1:
        # Parallel execution
        with ProcessPoolExecutor(max_workers=len(coins)) as executor:
            futures = {executor.submit(backtest_coin, (coin, data_cache, use_cache)): coin 
                      for coin in coins}
            for future in as_completed(futures):
                coin, result = future.result()
                if result:
                    results[coin] = result
    else:
        # Sequential execution
        for coin in coins:
            coin, result = backtest_coin((coin, data_cache, use_cache))
            if result:
                results[coin] = result
    
    # Print results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    for coin in coins:
        if coin in results:
            r = results[coin]
            print(f"\n{coin}:")
            print(f"  CAGR: {r['cagr']:+.2f}%")
            print(f"  Max DD: {r['dd']:.2f}%")
            print(f"  SL Rate: {r['slr']:.2f}%")
            print(f"  Final Equity: ${r['final']:,.2f}")
            
            if 'yearly' in r and r['yearly']:
                print(f"  Yearly Returns:")
                for year in sorted(r['yearly'].keys()):
                    print(f"    {year}: {r['yearly'][year]:+.2f}%")
    
    # Summary
    if len(results) > 1:
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        avg_cagr = mean(r['cagr'] for r in results.values())
        avg_dd = mean(r['dd'] for r in results.values())
        avg_slr = mean(r['slr'] for r in results.values())
        print(f"Average CAGR: {avg_cagr:+.2f}%")
        print(f"Average Max DD: {avg_dd:.2f}%")
        print(f"Average SL Rate: {avg_slr:.2f}%")
    
    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
