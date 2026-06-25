#!/usr/bin/env python3
"""BULL Snowball Backtest - Snowball entries + trailing stop, NO SL in bull market.

Strategy for BULL mode:
  - Snowball entries: 25% → 50% → 75% → 100% (at +10%, +20%, +30% price milestones)
  - NO stop loss (hold through pullbacks)
  - Trailing stop at 11% (activates at 40% ROI)
  - Exit on trend reversal (3D trend score <= 0)
  - BEAR mode uses standard HYBRID (unchanged)
  - ETH/BNB/TRX bounce: per-coin lev, per-coin TP, per-coin peak DD, 3% price trail
"""

import sys, json, argparse, hashlib
from datetime import datetime as dt_cls, timezone
from statistics import mean
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

from crypto_trading import (
    sma, evaluate_trend_3d, compute_volume_score,
    compute_entry_v6_long, compute_entry_v6_short,
    resolve_action_v6, _entry_score_v7_long, _entry_score_v7_short,
    get_coin_profile, compute_rsi, compute_sideway_score,
    _fib_cooldown_bars, compute_adx,
)
from trading_config import (
    COINS, SF, BASE, ENTRY_MIN_SCORE, TP_SCHEDULE, FEE_RATE,
    SHORT_ALLOWED, MAX_POS_PCT, MAX_ENTRIES_PER_COIN,
    BULL_SNOWBALL_LEVELS, BULL_SNOWBALL_SIZES, BULL_INITIAL_SIZE,
    BULL_TRAIL_DISTANCE, BULL_TRAIL_ACTIVATION,
    BULL_TRAIL_CLOSE, BULL_TRAIL_COOLDOWN_BARS, BULL_NO_SL, BULL_MAX_LOSS,
    BULL_TP_SCHEDULE,
    COIN_CONFIG, ENTRY_COOLDOWN_BARS,
    SL_ROLLING_CAP, SL_ROLLING_LOCK_BARS, SL_ROLLING_FIB, SIDEWAY_MAX_SCORE,
    get_profile, _coin_lev, _coin_sl_roi, _coin_trail, _coin_cap,
    BTC_BEAR_OVERRIDE,
    BNB_BOUNCE_MA_BUF, TRX_BOUNCE_MA_BUF,
    SAFE_LEV, SAFE_SL, SAFE_ENTRY, SAFE_TP, SAFE_PEAK_DD, SAFE_ENTRY_SCORE, BTC_ADX_SAFE, SAFE_MA_BUF,
    BEAR_SHORT_LEV, BEAR_SHORT_SL, BEAR_SHORT_SNOWBALL, BEAR_SHORT_SCORE, BEAR_SHORT_MAX_LOSS,
    SAFE_SHORT_LEV, SAFE_SHORT_SL, SAFE_SHORT_ENTRY, SAFE_SHORT_SCORE, SAFE_SHORT_TP, SAFE_SHORT_PEAK_DD,
    BOUNCE_TP, BOUNCE_SL, BOUNCE_PEAK_DD, BOUNCE_ENTRY_SIZE, BOUNCE_TRAIL_DISTANCE, BOUNCE_TRAIL_CLOSE,
    BOUNCE_LEV_CHOPPY, BOUNCE_SL_CHOPPY, BOUNCE_TP_CHOPPY, BOUNCE_PEAK_DD_CHOPPY,
    BOUNCE_TRAIL_DISTANCE_CHOPPY, BOUNCE_TRAIL_CLOSE_CHOPPY, BOUNCE_TRAIL_ACTIVATION_CHOPPY,
    BOUNCE_MAX_ENTRIES, BOUNCE_SNOWBALL_LEVELS, BOUNCE_SNOWBALL_SIZES, BOUNCE_TRAIL_ACTIVATION, BOUNCE_MIN_SCORE, BOUNCE_MIN_SCORE_CHOPPY,

    COIN_PEAK_DD, COIN_BOUNCE_LEV, COIN_BOUNCE_ENTRY_SIZE, COIN_BOUNCE_TRAIL_ACTIVATION, COIN_MAX_MARGIN,
    COIN_BULL_SL, COIN_BULL_PEAK_DD, COIN_BULL_INITIAL_SIZE, COIN_BULL_SNOWBALL_SIZES,)

# All constants imported from trading_config.py

# Local constants (not in trading_config)
AGGR_N = 1; TMA_F, TMA_M, TMA_S = 14, 28, 56
INITIAL = 75
BULL_LEV = 3.5
BULL_REGIME_EXIT = True

CACHE_FILE = Path(__file__).parent / "_klines_12h_5y.json"
RESULT_CACHE_DIR = Path(__file__).parent / ".cache"
RESULT_CACHE_DIR.mkdir(exist_ok=True)


fib_bars = _fib_cooldown_bars


def load_data():
    if not CACHE_FILE.exists():
        raise FileNotFoundError(f"Cache file not found: {CACHE_FILE}")
    with open(CACHE_FILE) as f:
        return json.load(f)


def fetch(data_cache, symbol):
    return data_cache.get(f"{symbol}_4000_1609434000000", [])


def aggr(c, n=3):
    r = []
    for i in range(0, len(c) - n + 1, n):
        b = c[i:i + n]
        r.append({'open_time': b[0]['open_time'], 'open': b[0]['open'],
            'high': max(x['high'] for x in b), 'low': min(x['low'] for x in b),
            'close': b[-1]['close'], 'volume': sum(x['volume'] for x in b)})
    return r


def get_cache_key(coin, config_hash):
    return f"snowball_{coin}_{config_hash}.json"


def load_cached_result(coin, config_hash):
    cache_file = RESULT_CACHE_DIR / get_cache_key(coin, config_hash)
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)
    return None


def save_cached_result(coin, config_hash, result):
    cache_file = RESULT_CACHE_DIR / get_cache_key(coin, config_hash)
    with open(cache_file, 'w') as f:
        json.dump(result, f)


def backtest_coin(args_tuple):
    coin, data_cache, use_cache, selected_years = args_tuple
    btc_da = fetch(data_cache, "BTCUSDT")  # for BTC regime
    btc_da = fetch(data_cache, "BTCUSDT")  # for BTC regime

    config_str = json.dumps({
        "coin": coin, "mode": "snowball_bull",
        "config": {k: COIN_CONFIG.get(k, {}) for k in COIN_CONFIG},
        "bull": {
            "levels": BULL_SNOWBALL_LEVELS, "sizes": BULL_SNOWBALL_SIZES,
            "init": BULL_INITIAL_SIZE, "trail": BULL_TRAIL_DISTANCE,
            "trail_act": BULL_TRAIL_ACTIVATION, "trail_close": BULL_TRAIL_CLOSE,
            "trail_cd": BULL_TRAIL_COOLDOWN_BARS, "no_sl": BULL_NO_SL,
        },
        "tp": TP_SCHEDULE, "fee": FEE_RATE,
    }, sort_keys=True)
    config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

    if use_cache:
        cached = load_cached_result(coin, config_hash)
        if cached:
            print(f"  {coin}: Loaded from cache")
            return coin, cached

    print(f"  {coin}: Running snowball backtest...")

    da = fetch(data_cache, coin + "USDT")
    if not da:
        return coin, None

    prof = dict(get_coin_profile(coin))
    allow_short = coin in SHORT_ALLOWED

    entries = []; eq = 1.0; curve = []; trades = []; lei = -999
    yearly_eq = {};
    consec_l = 0; consec_s = 0; cd_l_until = -999; cd_s_until = -999
    rolling_sl_long = 0; rolling_sl_short = 0
    rolling_lock_until_long = -999; rolling_lock_until_short = -999

    # ── Pre-compute all indicators once ──
    closes_12h = [x['close'] for x in da]
    volumes_12h = [x['volume'] for x in da]
    high_12h = [x['high'] for x in da]
    low_12h = [x['low'] for x in da]
    n = len(closes_12h)
    rsi_p = int(14*SF); adx_p = int(14*SF); sw_p = int(5*SF); sw_p2 = int(20*SF)
    
    # SMAs on 12h raw data
    pre12 = {p: sma(closes_12h, p) for p in [18, 37, 30, int(7*SF), int(10*SF), int(200*SF), 50, 120, int(20*SF)]}
    pre12_v = sma(volumes_12h, int(20*SF))  # volume SMA
    
    # SMAs on 24h aggregated data
    ct_full = aggr(da, 2); ct_c = [c['close'] for c in ct_full]
    pre24 = {p: sma(ct_c, p) for p in [TMA_F, TMA_M, TMA_S]}
    
    # RSI (compute only once per bar)
    pre_rsi = [50.0] * n
    for i in range(rsi_p, n):
        pre_rsi[i] = compute_rsi(closes_12h[:i+1], rsi_p)
    
    # ADX (compute only once)
    pre_adx = [50.0] * n
    for i in range(adx_p+1, n):
        pre_adx[i] = compute_adx(da[:i+1], adx_p)
    
    # Sideway score (compute only once)
    pre_sw = [0] * n
    for i in range(1, n):
        pre_sw[i] = compute_sideway_score(da[:i+1], SF)
    
    # BTC data precompute
    if btc_da:
        btc_c1 = [x['close'] for x in btc_da]
        btc_pre50 = sma(btc_c1, 50)
        btc_pre120 = sma(btc_c1, 120)
        btc_n = len(btc_c1)
        btc_adx = [50.0] * btc_n
        for i in range(30, btc_n):
            btc_adx[i] = compute_adx(btc_da[:i+1], 14)
    else:
        btc_pre50 = btc_pre120 = btc_adx = [50]*n
    
    # Cached indicator lookups
    def g(arr, idx, default): return arr[idx] if arr[idx] is not None else default
    
    # ── Main loop ──
    for idx in range(INITIAL, len(da)):
        ds = da[:idx + 1]; ct = aggr(ds, AGGR_N)
        if len(ct) < 25: continue
        ci = min(idx // 2, len(ct_c) - 1)
        if ci >= len(ct_c): continue
        cc = ds[-1]['close']; bh = ds[-1]['high']; bl = ds[-1]['low']
        ci = min(idx // 2, len(ct_c) - 1)  # index into 24h data
        mf = g(pre24[TMA_F], ci, ct_c[ci]); mm = g(pre24[TMA_M], ci, ct_c[ci])
        ms = g(pre24[TMA_S], ci, ct_c[ci])
        _, ts = evaluate_trend_3d(mf, mm, ms)
        ef = g(pre12[18], idx, closes_12h[idx])
        em = g(pre12[37], idx, closes_12h[idx])
        exec_s = g(pre12[30], idx, closes_12h[idx])
        ma7 = g(pre12[int(7*SF)], idx, closes_12h[idx])
        ma10 = g(pre12[int(10*SF)], idx, closes_12h[idx])
        ma200 = g(pre12[int(200*SF)], idx, None)
        vm2 = g(pre12_v, idx, volumes_12h[idx])
        rsi1 = pre_rsi[idx]
        v1 = [c['volume'] for c in ds]
        dt_val = ds[-1]['open_time']

        ma50_pc = g(pre12[50], idx, closes_12h[idx])
        ma120_pc = g(pre12[120], idx, closes_12h[idx])
        cfg = COIN_CONFIG.get(coin, COIN_CONFIG["ETH"])
        d_cur = dt_cls.fromtimestamp(dt_val/1000,tz=timezone.utc)
        cur_year = d_cur.year

        is_bull = ma50_pc > ma120_pc
        if cfg.get("ma_buffer"):
            is_bull = ma50_pc > ma120_pc * (1 + cfg["ma_buffer"])

        # BTC regime override: only affect BULL entries
        btc_bull = True; btc_safe = True  # safe mode by default
        if btc_da and idx < len(btc_da) and btc_pre50 is not None and btc_pre120 is not None and idx < len(btc_pre50):
            b50 = btc_pre50[idx]; b120 = btc_pre120[idx]
            if b50 is not None and b120 is not None:
                btc_bull = b50 > b120
                btc_safe = False
                if idx < len(btc_adx) and btc_adx[idx] is not None and btc_adx[idx] < BTC_ADX_SAFE:
                    btc_safe = True
        else:
            btc_safe = True  # no BTC data → safe mode
        bull_lev_use = BULL_LEV
        bull_max_loss_use = BULL_MAX_LOSS
        # Use per-coin max_loss from profile
        pm = get_profile(coin, True).get("max_loss")
        if pm is not None: bull_max_loss_use = pm
        bull_cfg = dict(cfg)  # copy for bull-specific overrides
        # BTC regime override: only affect BULL entries, skip if coin has own strict config
        if not btc_bull and coin != "ETH":
            bull_cfg = {**bull_cfg, **BTC_BEAR_OVERRIDE}
            bull_lev_use = BTC_BEAR_OVERRIDE.get("bull_lev", BULL_LEV)
            bull_max_loss_use = BTC_BEAR_OVERRIDE.get("max_loss", BULL_MAX_LOSS)

        # Bounce: defensive long in BTC bear (ETH/BNB/TRX: 2x, SL 5.5%, fixed TP, peak DD)
        bounce = (coin in ("ETH", "BNB", "TRX") and not btc_bull)
        # Aggressive bear short: snowball + trail like longs, when BTC strong bear
        bear_short = (not btc_safe and not btc_bull and coin == "ETH" and BEAR_SHORT_SNOWBALL)

        # --- Year filter: go to cash if year not selected ---
        if selected_years and cur_year not in selected_years:
            if entries:
                for ent in entries:
                    ep = ent['ep']; mp = ent['mp']
                    is_sh = ent.get('is_short', False)
                    ent_lev = ent.get('lev', coin_lev)
                    ent_ff = 1 - 2 * FEE_RATE * ent_lev
                    if not is_sh: raw_roi = ((cc-ep)/ep*100)*mp*tc*ent_lev/BASE
                    else: raw_roi = ((ep-cc)/ep*100)*mp*tc*ent_lev/BASE
                    eq += raw_roi*ent['rem']/100*ent_ff
                entries = []
            ureal = 0; total_eq = eq; curve.append(total_eq)
            if d_cur.month == 12: yearly_eq[d_cur.year] = total_eq
            continue

        vm2 = g(pre12_v, idx, volumes_12h[idx])
        v5a = sum(v1[-int(5*SF):])/(int(5*SF)) if len(v1)>=int(5*SF) else v1[-1]
        vs = compute_volume_score(v1[-1], vm2)

        hybrid_profile = get_profile(coin, is_bull)
        coin_lev = _coin_lev(coin); sl_val = _coin_sl_roi(coin)
        tr_rate = _coin_trail(coin)
        cd = ENTRY_COOLDOWN_BARS.get(coin, 0)
        tc = BASE * _coin_cap(coin)
        ff = 1 - 2 * FEE_RATE * coin_lev
        pos_mult = hybrid_profile["pos_mult"]
        initial_exposure = hybrid_profile["initial_exposure"]
        max_ms = MAX_POS_PCT / hybrid_profile["lev"] * pos_mult
        coin_max_ms = COIN_MAX_MARGIN.get(coin, max_ms)

        go_cash = False
        if go_cash:
            if entries:
                for ent in entries:
                    ep = ent['ep']; mp = ent['mp']
                    is_sh = ent.get('is_short', False)
                    ent_lev = ent.get('lev', coin_lev)
                    ent_ff = 1 - 2 * FEE_RATE * ent_lev
                    if not is_sh: raw_roi = ((cc-ep)/ep*100)*mp*tc*ent_lev/BASE
                    else: raw_roi = ((ep-cc)/ep*100)*mp*tc*ent_lev/BASE
                    eq += raw_roi*ent['rem']/100*ent_ff
                    trades.append({'t':'BEAR_EXIT','dir':'S' if is_sh else 'L'})
                entries = []
            # Stay in cash during bear: just track equity
            ureal = 0; total_eq = eq; curve.append(total_eq)
            if d_cur.month == 12: yearly_eq[d_cur.year] = total_eq
            continue

        # --- Exit loop ---
        ne = []
        for ent in entries:
            ep = ent['ep']; mp = ent['mp']; tp_s = ent['tp']
            rem2 = ent['rem']; hi = ent['hi']; tstop = ent['tstop']
            is_sh = ent.get('is_short', False)
            ent_lev = ent.get('lev', coin_lev); ent_sl = ent.get('sl', sl_val)
            ent_ff = 1 - 2 * FEE_RATE * ent_lev
            ent_is_bull = ent_lev > 2.5
            tr_use = BULL_TRAIL_DISTANCE if ent_is_bull else tr_rate

            if not is_sh: raw_roi = ((cc-ep)/ep*100)*mp*tc*ent_lev/BASE
            else: raw_roi = ((ep-cc)/ep*100)*mp*tc*ent_lev/BASE

            # --- BULL mode: NO stop loss ---
            sl_pct_calc = ent_sl/(mp*tc*ent_lev/BASE)/100 if mp*tc*ent_lev/BASE>0 else 1.0
            intrabar = False
            if not ent_is_bull:  # BEAR mode: SL active
                if not is_sh:
                    sl_p = ep*(1-sl_pct_calc)
                    if bl <= sl_p:
                        sl_roi = ((sl_p-ep)/ep*100)*mp*tc*ent_lev/BASE
                        eq += sl_roi*rem2/100*ent_ff
                        trades.append({'t':'SL','dir':'L'}); intrabar = True
                else:
                    sl_p = ep*(1+sl_pct_calc)
                    if bh >= sl_p:
                        sl_roi = ((ep-sl_p)/ep*100)*mp*tc*ent_lev/BASE
                        eq += sl_roi*rem2/100*ent_ff
                        trades.append({'t':'SL','dir':'S'}); intrabar = True

            if intrabar:
                if is_sh:
                    consec_s += 1; rolling_sl_short += 1
                    cd_f = fib_bars(consec_s, 0)
                    if cd_f > 0: cd_s_until = idx + cd_f
                    if rolling_sl_short >= SL_ROLLING_CAP:
                        lock_bars = fib_bars(SL_ROLLING_CAP + (rolling_sl_short - SL_ROLLING_CAP), 0) if SL_ROLLING_FIB else SL_ROLLING_LOCK_BARS
                        rolling_lock_until_short = idx + lock_bars
                else:
                    consec_l += 1; rolling_sl_long += 1
                    cd_f = fib_bars(consec_l, 0)
                    if cd_f > 0: cd_l_until = idx + cd_f
                    if rolling_sl_long >= SL_ROLLING_CAP:
                        lock_bars = fib_bars(SL_ROLLING_CAP + (rolling_sl_long - SL_ROLLING_CAP), 0) if SL_ROLLING_FIB else SL_ROLLING_LOCK_BARS
                        rolling_lock_until_long = idx + lock_bars
                continue

            if not is_sh:
                if cc > hi: hi = cc; ent['hi'] = hi
            else:
                if cc < hi: hi = cc; ent['hi'] = hi
            rm = False

            # Safe mode: SL, staggered TP, peak DD (supports entry overrides)
            if ent.get('safe_mode', False):
                tp_schedule = ent.get('_tp_s', SAFE_TP)
                dd_threshold = ent.get('_dd_t', COIN_PEAK_DD.get(coin, SAFE_PEAK_DD))
                peak_roi = max(ent.get('_peak_roi', -999), raw_roi)
                ent['_peak_roi'] = peak_roi
                if raw_roi <= -ent_sl:
                    eq += raw_roi*rem2/100*ent_ff; rm = True
                    trades.append({'t':'SL','dir':'S' if is_sh else 'L'})
                    if is_sh: consec_s += 1; rolling_sl_short += 1
                    else: consec_l += 1; rolling_sl_long += 1
                elif not rm:
                    tp_s = ent.get('tp', 0)
                    if tp_s < len(tp_schedule):
                        trg, cf_pct = tp_schedule[tp_s]
                        if raw_roi >= trg:
                            cf = cf_pct * rem2; eq += raw_roi * cf / 100 * ent_ff
                            rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                            ent['_peak_roi'] = raw_roi
                            trades.append({'t':'TP','dir':'S' if is_sh else 'L'})
                            if is_sh: consec_s = 0; rolling_sl_short = 0
                            else: consec_l = 0; rolling_sl_long = 0
                            if rem2 <= 0.001: rm = True
                    if not rm and raw_roi <= peak_roi - dd_threshold:
                        eq += raw_roi * rem2 / 100 * ent_ff; rm = True
                        trades.append({'t':'PEAK_DD','dir':'S' if is_sh else 'L'})
                if not rm: ne.append(ent)
                continue

            # Bounce: per-entry TP/peak DD/trail
            if ent.get('bounce', False):
                peak_r = max(ent.get('_peak_roi', -999), raw_roi)
                ent['_peak_roi'] = peak_r
                if raw_roi <= -ent_sl:
                    eq += raw_roi*rem2/100*ent_ff; rm = True
                    trades.append({'t':'SL','dir':'L'})
                    consec_l += 1; rolling_sl_long += 1
                elif not rm:
                    tp_s = ent.get('tp', 0)
                    bounce_tp = ent.get('_tp_s', BOUNCE_TP)
                    if tp_s < len(bounce_tp):
                        trg, cf_pct = bounce_tp[tp_s]
                        if raw_roi >= trg:
                            cf = cf_pct * rem2
                            eq += raw_roi * cf / 100 * ent_ff
                            rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                            ent['_peak_roi'] = raw_roi
                            trades.append({'t':'TP','dir':'L'})
                            consec_l = 0; rolling_sl_long = 0
                            if rem2 <= 0.001: rm = True
                    bounce_peak_dd = COIN_PEAK_DD.get(coin, ent.get('_dd_t', BOUNCE_PEAK_DD))
                    if not rm and raw_roi <= peak_r - bounce_peak_dd:
                        eq += raw_roi * rem2 / 100 * ent_ff; rm = True
                        trades.append({'t':'PEAK_DD','dir':'L'})
                    bounce_tr = ent.get('_trail_dist', BOUNCE_TRAIL_DISTANCE)
                    bounce_tc = ent.get('_trail_close', BOUNCE_TRAIL_CLOSE)
                    bounce_ta = ent.get('_trail_act', COIN_BOUNCE_TRAIL_ACTIVATION.get(coin, BOUNCE_TRAIL_ACTIVATION))
                    trail_ready = tp_s >= len(bounce_tp)
                    if not trail_ready and bounce_ta > 0 and raw_roi >= bounce_ta:
                        trail_ready = True
                    if not rm and trail_ready:
                        if tstop is None:
                            tstop = cc * (1 - bounce_tr)
                        tstop = max(tstop, hi * (1 - bounce_tr))
                        ent['tstop'] = tstop
                        if bl <= tstop:
                            cf = bounce_tc * rem2
                            eq += raw_roi * cf / 100 * ent_ff
                            rem2 -= cf; ent['rem'] = rem2
                            trades.append({'t':'TRAIL','dir':'L'})
                            consec_l = 0; rolling_sl_long = 0
                            if rem2 <= 0.001: rm = True
                if not rm: ne.append(ent)
                continue

            # BEAR mode: standard SL + TP
            if not ent_is_bull:
                if raw_roi <= -ent_sl:
                    eq += raw_roi*rem2/100*ent_ff
                    trades.append({'t':'SL','dir':'S' if is_sh else 'L'}); rm = True
                    if is_sh: consec_s += 1; rolling_sl_short += 1
                    else: consec_l += 1; rolling_sl_long += 1

                elif tp_s < len(TP_SCHEDULE):
                    trg, cpct = TP_SCHEDULE[tp_s]
                    if raw_roi >= trg:
                        cf = cpct*rem2; eq += raw_roi*cf/100*ent_ff
                        rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                        trades.append({'t':'TP','dir':'S' if is_sh else 'L'})
                        if ent['tp'] >= len(TP_SCHEDULE):
                            ent['tstop'] = cc*(1-tr_use) if not is_sh else cc*(1+tr_use)

                # BEAR trailing
                if tp_s >= len(TP_SCHEDULE) and not rm:
                    if not is_sh:
                        if tstop is None: tstop = cc*(1-tr_use)
                        tstop = max(tstop, hi*(1-tr_use)); ent['tstop'] = tstop
                        if bl <= tstop:
                            eq += raw_roi*rem2/100*ent_ff
                            trades.append({'t':'TRAIL','dir':'L'}); rm = True; consec_l = 0; rolling_sl_long = 0
                    else:
                        if tstop is None: tstop = cc*(1+tr_use)
                        tstop = min(tstop, hi*(1+tr_use)); ent['tstop'] = tstop
                        if bh >= tstop:
                            eq += raw_roi*rem2/100*ent_ff
                            trades.append({'t':'TRAIL','dir':'S'}); rm = True; consec_s = 0; rolling_sl_short = 0

            # Aggressive bear short: same staggered TP + trail as bull longs
            if not rm and ent.get('short_agg', False):
                if raw_roi <= -BEAR_SHORT_MAX_LOSS * 100:
                    eq += raw_roi*rem2/100*ent_ff; rm = True
                    trades.append({'t':'MAX_LOSS','dir':'S'})
                    consec_s += 1; rolling_sl_short += 1
                elif not rm:
                    tp_s = ent.get('tp', 0)
                    if tp_s < len(BULL_TP_SCHEDULE):
                        trg, cf_pct = BULL_TP_SCHEDULE[tp_s]
                        if raw_roi >= trg:
                            cf = cf_pct * rem2; eq += raw_roi * cf / 100 * ent_ff
                            rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                            trades.append({'t':'TP','dir':'S'})
                            consec_s = 0; rolling_sl_short = 0
                            if rem2 <= 0.001: rm = True
                    if tp_s >= len(BULL_TP_SCHEDULE) and not rm:
                        in_trail_cd = ent.get('_trail_cooldown', -999) > idx
                        pnl_from_entry = (ep - cc) / ep  # profit for short
                        if pnl_from_entry >= BULL_TRAIL_ACTIVATION and not in_trail_cd:
                            tstop = min(ent.get('tstop') or cc*(1+BULL_TRAIL_DISTANCE), hi*(1+BULL_TRAIL_DISTANCE))
                            ent['tstop'] = tstop
                            if bh >= tstop:
                                cf = BULL_TRAIL_CLOSE * rem2
                                eq += raw_roi * cf / 100 * ent_ff
                                rem2 -= cf; ent['rem'] = rem2
                                trades.append({'t':'TRAIL','dir':'S'})
                                ent['tstop'] = cc*(1+BULL_TRAIL_DISTANCE)
                                ent['_trail_cooldown'] = idx + BULL_TRAIL_COOLDOWN_BARS
                                if rem2 <= 0.001: rm = True
                                consec_s = 0; rolling_sl_short = 0
                if not rm: ne.append(ent)
                continue

            # BULL mode: staggered TP (10/20/30%) + trail remaining
            if ent_is_bull and not rm:
                peak_r = max(ent.get('_peak_roi', -999), raw_roi)
                ent['_peak_roi'] = peak_r
                # Per-coin SL check (tighter than MAX_LOSS)
                coin_bull_sl = COIN_BULL_SL.get(coin, 0)
                if coin_bull_sl > 0 and raw_roi <= -coin_bull_sl:
                    eq += raw_roi*rem2/100*ent_ff; rm = True
                    trades.append({'t':'SL','dir':'L'})
                    consec_l += 1; rolling_sl_long += 1
                elif raw_roi <= -bull_max_loss_use * 100:
                    eq += raw_roi*rem2/100*ent_ff
                    trades.append({'t':'MAX_LOSS','dir':'L'}); rm = True
                    consec_l += 1; rolling_sl_long += 1
                elif not rm:
                    # Per-coin peak DD check
                    coin_bull_pdd = COIN_BULL_PEAK_DD.get(coin, 0)
                    if coin_bull_pdd > 0 and raw_roi <= peak_r - coin_bull_pdd:
                        eq += raw_roi * rem2 / 100 * ent_ff; rm = True
                        trades.append({'t':'PEAK_DD','dir':'L'})
                    # Staggered partial TP: 10% at 10% ROI, 10% at 20%, 10% at 30%
                    elif not rm:
                        tp_s = ent.get('tp', 0)
                        if tp_s < len(BULL_TP_SCHEDULE):
                            trg, cf_pct = BULL_TP_SCHEDULE[tp_s]
                            if raw_roi >= trg:
                                cf = cf_pct * rem2
                                eq += raw_roi * cf / 100 * ent_ff
                                rem2 -= cf; ent['rem'] = rem2; ent['tp'] = tp_s + 1
                                trades.append({'t':'TP','dir':'L'})
                                consec_l = 0; rolling_sl_long = 0
                                ent['_peak_roi'] = raw_roi
                                if rem2 <= 0.001: rm = True
                        # Trail remaining after all staggered TPs
                        if tp_s >= len(BULL_TP_SCHEDULE) and not rm:
                            in_trail_cd = ent.get('_trail_cooldown', -999) > idx
                            pnl_from_entry = (cc - ep) / ep if not is_sh else (ep - cc) / ep
                            if pnl_from_entry >= BULL_TRAIL_ACTIVATION and not in_trail_cd:
                                if tstop is None:
                                    tstop = cc * (1 - BULL_TRAIL_DISTANCE) if not is_sh else cc * (1 + BULL_TRAIL_DISTANCE)
                                if not is_sh:
                                    tstop = max(tstop, hi * (1 - BULL_TRAIL_DISTANCE))
                                else:
                                    tstop = min(tstop, hi * (1 + BULL_TRAIL_DISTANCE))
                                ent['tstop'] = tstop
                                if not is_sh and bl <= tstop:
                                    cf = BULL_TRAIL_CLOSE * rem2
                                    eq += raw_roi * cf / 100 * ent_ff
                                    rem2 -= cf; ent['rem'] = rem2
                                    trades.append({'t':'TRAIL','dir':'L'})
                                    tstop = cc * (1 - BULL_TRAIL_DISTANCE); ent['tstop'] = tstop
                                    ent['_trail_cooldown'] = idx + BULL_TRAIL_COOLDOWN_BARS
                                    if rem2 <= 0.001: rm = True
                                    consec_l = 0; rolling_sl_long = 0
                                elif is_sh and bh >= tstop:
                                    cf = BULL_TRAIL_CLOSE * rem2
                                    eq += raw_roi * cf / 100 * ent_ff
                                    rem2 -= cf; ent['rem'] = rem2
                                    trades.append({'t':'TRAIL','dir':'S'})
                                    ent['_trail_cooldown'] = idx + BULL_TRAIL_COOLDOWN_BARS
                                    if rem2 <= 0.001: rm = True
                                    consec_s = 0; rolling_sl_short = 0

            # Trend reversal exit (BEAR + shorts only, bull longs use trail+regime)
            if is_sh and not rm and ts >= 2:
                eq += raw_roi*rem2/100*ent_ff
                trades.append({'t':'TREND_REV','dir':'S'}); rm = True
                if raw_roi > 0: consec_s = 0; rolling_sl_short = 0
                else: consec_s += 1; rolling_sl_short += 1
            if not is_sh and not rm and not ent_is_bull and ts <= -2:
                eq += raw_roi*rem2/100*ent_ff
                trades.append({'t':'TREND_REV','dir':'L'}); rm = True
                if raw_roi > 0: consec_l = 0; rolling_sl_long = 0
                else: consec_l += 1; rolling_sl_long += 1

            # BULL regime exit: extra safety - close if trend fully reverses
            if BULL_REGIME_EXIT and ent_is_bull and not is_sh and not rm and not is_bull:
                eq += raw_roi*rem2/100*ent_ff
                trades.append({'t':'REGIME','dir':'L'}); rm = True
                if raw_roi > 0: consec_l = 0; rolling_sl_long = 0
                else: consec_l += 1; rolling_sl_long += 1

            if not rm: ne.append(ent)
        entries = ne

        # --- Entry logic ---
        dep = sum(e['mp'] for e in entries)
        can_l = dep < max_ms and (idx - lei >= cd) and (idx > cd_l_until)
        can_s = dep < max_ms and (idx - lei >= cd) and (idx > cd_s_until)
        has_l = any(not e.get('is_short',False) for e in entries)
        has_s = any(e.get('is_short',False) for e in entries)

        if can_l and idx <= rolling_lock_until_long: can_l = False
        if can_s and idx <= rolling_lock_until_short: can_s = False

        if can_l or can_s:
            sideway_score = pre_sw[idx]
            if sideway_score > SIDEWAY_MAX_SCORE:
                can_l = False; can_s = False
            adx_val = pre_adx[idx]
            if adx_val < cfg["adx_min"]:  # too weak -> skip
                can_l = False; can_s = False

        # Bounce: BNB/TRX need MA confirmation (1.8% buffer)
        if can_l and bounce and coin == "BNB":
            if ma50_pc <= ma120_pc * (1 + BNB_BOUNCE_MA_BUF):
                can_l = False
        if can_l and bounce and coin == "TRX":
            if ma50_pc <= ma120_pc * (1 + TRX_BOUNCE_MA_BUF):
                can_l = False
        # No shorts in BTC bull (counter-trend shorts are too risky)
        if btc_bull:
            can_s = False
        # No shorts in weak bear (ADX < 22) — choppy, gets stopped out
        if can_s and not btc_bull and btc_safe:
            can_s = False
        # Block bull mode when BTC is bear (false signals in bear market)
        if can_l and is_bull and not btc_bull:
            can_l = False
        # Block bounce long in strong bear (BTC bear + ADX >= 22)
        if can_l and bounce and not btc_safe:
            can_l = False
        # Safe mode: MA buffer 2% — confirm bounce before entry
        if can_l and btc_safe and not bounce and not bear_short:
            if ma50_pc <= ma120_pc * (1 + SAFE_MA_BUF):
                can_l = False

        if can_l or can_s:
            el = compute_entry_v6_long(ts,rsi1,cc,exec_s,em,ef,vs,
                trend_min=prof['trend_min_long'],vol_min=prof['vol_min'],
                rsi_max=prof.get('rsi_max_long',90),ma7_1d=ma7,ma200_1d=ma200,
                last_volume=v1[-1],vol_5d_avg=v5a,
                use_ma200_filter=False,use_pullback_filter=False,
                use_volume_expan=False,min_entry_score=bull_cfg["entry_score"] if is_bull else cfg["entry_score"]) if can_l else False
            es_ = compute_entry_v6_short(ts,rsi1,cc,exec_s,em,ef,vs,
                trend_max=prof.get('trend_max_short',-2),vol_min=prof['vol_min'],
                rsi_min=prof.get('rsi_min_short',10),
                ma7_1d=ma7,ma10_1d=ma10,ma200_1d=ma200,
                last_volume=v1[-1],vol_5d_avg=v5a,
                use_ma200_filter=False,use_pullback_filter=False,
                use_volume_expan=False,
                min_entry_score=prof.get('short_min_entry_score',ENTRY_MIN_SCORE),
                candles_12h=ds) if (allow_short and can_s and (cfg["bear_short"] or is_bull or (coin == "TRX" and not btc_bull))) else False
            if el and has_s: el = False
            if es_ and has_l: es_ = False

            # --- BULL snowball: add only on strong signal ---
            did_snowball = False
            # Aggressive bear short snowball
            if bear_short and has_s and not has_l:
                sc_snow = _entry_score_v7_short(ts,cc,ma7,ma10,exec_s,ma200,ef,em,vs,v1[-1],v5a,rsi1,ds)
                if sc_snow >= BEAR_SHORT_SCORE:
                    for ent in entries:
                        if not ent.get('is_short', False): continue
                        ent_ep = ent['ep']
                        pnl_from_last = (ent_ep - cc) / ent_ep
                        snowball_idx = ent.get('snowball_stage', 0)
                        if snowball_idx < len(BULL_SNOWBALL_LEVELS):
                            target = BULL_SNOWBALL_LEVELS[snowball_idx]
                            if pnl_from_last >= target:
                                add_mp = BULL_SNOWBALL_SIZES[snowball_idx + 1] if snowball_idx + 1 < len(BULL_SNOWBALL_SIZES) else BULL_INITIAL_SIZE
                                if dep + add_mp <= coin_max_ms + 0.001:
                                    entries.append({'ep':cc,'mp':add_mp,'tp':0,'rem':1.0,'hi':cc,
                                        'tstop':None,'is_short':True,
                                        'lev':BEAR_SHORT_LEV,'sl':BEAR_SHORT_SL,
                                        'bull_mode':False,'short_agg':True,
                                        'snowball_stage': snowball_idx + 1, 'is_snowball': True})
                                    lei = idx; did_snowball = True
                                    trades.append({'t':'SNOWBALL','dir':'S'})
                                break
            # Bull snowball (per-coin sizing)
            if is_bull and has_l and not has_s and not (coin == "TRX" and not btc_bull):
                sc_snow = _entry_score_v7_long(ts,cc,ma7,ma10,exec_s,ma200,ef,em,vs,v1[-1],v5a,rsi1)
                if sc_snow >= bull_cfg["snowball_min_score"]:
                    coin_sb_sizes = COIN_BULL_SNOWBALL_SIZES.get(coin, BULL_SNOWBALL_SIZES)
                    for ent in entries:
                        if ent.get('is_short', False): continue
                        ent_ep = ent['ep']
                        pnl_from_last = (cc - ent_ep) / ent_ep
                        snowball_idx = ent.get('snowball_stage', 0)
                        if snowball_idx < len(BULL_SNOWBALL_LEVELS):
                            target = BULL_SNOWBALL_LEVELS[snowball_idx]
                            if pnl_from_last >= target:
                                add_mp = coin_sb_sizes[snowball_idx + 1] if snowball_idx + 1 < len(coin_sb_sizes) else BULL_INITIAL_SIZE
                                if dep + add_mp <= coin_max_ms + 0.001:
                                    entries.append({'ep':cc,'mp':add_mp,'tp':0,'rem':1.0,'hi':cc,
                                        'tstop':None,'is_short':False,
                                        'lev':bull_lev_use,'sl':12,
                                        'snowball_stage': snowball_idx + 1, 'is_snowball': True})
                                    lei = idx
                                    trades.append({'t':'SNOWBALL','dir':'L'})
                                    did_snowball = True
                                break

            # Bounce snowball: up to BOUNCE_MAX_ENTRIES same-sized entries
            if bounce and has_l and not has_s and not did_snowball:
                for ent in entries:
                    if not ent.get('bounce', False) or ent.get('is_short', False): continue
                    ent_ep = ent['ep']
                    pnl_from_last = (cc - ent_ep) / ent_ep
                    snowball_idx = ent.get('snowball_stage', 0)
                    total_bounce = sum(1 for e in entries if e.get('bounce', False))
                    if total_bounce >= BOUNCE_MAX_ENTRIES: break
                    if snowball_idx < len(BOUNCE_SNOWBALL_LEVELS):
                        target = BOUNCE_SNOWBALL_LEVELS[snowball_idx]
                        if pnl_from_last >= target:
                            add_mp = BOUNCE_SNOWBALL_SIZES[snowball_idx + 1] if snowball_idx + 1 < len(BOUNCE_SNOWBALL_SIZES) else BOUNCE_ENTRY_SIZE
                            if dep + add_mp <= coin_max_ms + 0.001:
                                entries.append({'ep':cc,'mp':add_mp,'tp':0,'rem':1.0,'hi':cc,
                                    'tstop':None,'is_short':False,
                                    'lev':COIN_BOUNCE_LEV.get(coin, 2.0),'sl':BOUNCE_SL,
                                    'bounce':True, 'snowball_stage': snowball_idx + 1, 'is_snowball': True})
                                lei = idx; did_snowball = True
                                trades.append({'t':'SNOWBALL','dir':'L'})
                            break

            # Standard entry (if not already snowballed)
            if not did_snowball:
                _, act = resolve_action_v6(ts, el, es_, 'FLAT')
                if act in ('OPEN_LONG_ENTRY_1','OPEN_SHORT_ENTRY_1'):
                    is_sh = act.startswith('OPEN_SHORT')
                    if is_sh: sc = _entry_score_v7_short(ts,cc,ma7,ma10,exec_s,ma200,ef,em,vs,v1[-1],v5a,rsi1,ds)
                    else: sc = _entry_score_v7_long(ts,cc,ma7,ma10,exec_s,ma200,ef,em,vs,v1[-1],v5a,rsi1)
                    strong = sc >= (bull_cfg["entry_score"] if is_bull else cfg["entry_score"])

                    mp = initial_exposure * pos_mult
                    mp *= 1.0 if strong else 0.7

                    safe_flag = False; eth_flag = False; bnb_flag = False; short_flag = False; is_trx_safe = False
                    # BTC weak trend: safe long OR safe short
                    if btc_safe and not is_sh:
                        if is_sh: sc = _entry_score_v7_short(ts,cc,ma7,ma10,exec_s,ma200,ef,em,vs,v1[-1],v5a,rsi1,ds)
                        else: sc = _entry_score_v7_long(ts,cc,ma7,ma10,exec_s,ma200,ef,em,vs,v1[-1],v5a,rsi1)
                        if sc < SAFE_ENTRY_SCORE: mp = 0
                        lev_entry = SAFE_LEV; sl_entry = SAFE_SL
                        bull_entry = False; safe_flag = True
                        mp = SAFE_ENTRY
                    # Safe short: isolated 1.5x short in BTC bear (any ADX)
                    elif not btc_bull and is_sh:
                        lev_entry = SAFE_SHORT_LEV; sl_entry = SAFE_SHORT_SL
                        bull_entry = False; safe_flag = True; short_flag = True
                        mp = SAFE_SHORT_ENTRY
                    # TRX safe isolated short in BTC bear
                    elif coin == "TRX" and not btc_bull and is_sh:
                        if sc < SAFE_ENTRY_SCORE: mp = 0
                        lev_entry = SAFE_LEV; sl_entry = SAFE_SL
                        bull_entry = False; safe_flag = True; is_trx_safe = True
                        mp = SAFE_ENTRY
                    # Bounce: defensive long in BTC bear (2.5x, really strong signal req)
                    elif bounce and not is_sh:
                        bounce_min_sc = BOUNCE_MIN_SCORE_CHOPPY if btc_safe else BOUNCE_MIN_SCORE
                        if sc < bounce_min_sc: mp = 0
                        else:
                            if btc_safe:
                                lev_entry = COIN_BOUNCE_LEV.get(coin, BOUNCE_LEV_CHOPPY); sl_entry = BOUNCE_SL_CHOPPY
                                bull_entry = False; eth_flag = True
                                mp = COIN_BOUNCE_ENTRY_SIZE.get(coin, BOUNCE_ENTRY_SIZE)
                            else:
                                lev_entry = COIN_BOUNCE_LEV.get(coin, 2.0); sl_entry = BOUNCE_SL
                                bull_entry = False; eth_flag = True
                                mp = COIN_BOUNCE_ENTRY_SIZE.get(coin, BOUNCE_ENTRY_SIZE)
                    elif is_bull and not is_sh:
                        lev_entry = bull_lev_use
                        sl_entry = hybrid_profile['sl']
                        bull_entry = True; ct_flag = False; eth_flag = False
                        mp = COIN_BULL_INITIAL_SIZE.get(coin, BULL_INITIAL_SIZE)
                    else:
                        mp = 0  # default: no trade (no mode matched)
                        lev_entry = 1; sl_entry = 1
                        bull_entry = False; ct_flag = False; eth_flag = False

                    if mp > 0 and len(entries) < MAX_ENTRIES_PER_COIN and dep + mp <= coin_max_ms + 0.001:
                        entry = {'ep':cc,'mp':mp,'tp':0,'rem':1.0,'hi':cc,
                            'tstop':None,'is_short':is_sh,
                                    'lev': lev_entry,
                                    'sl': sl_entry,
                                    'bull_mode': bull_entry,
                                    'ct_mode': False, 'bounce': bounce,
                                    'safe_mode': btc_safe, 'short_agg': short_flag, 'trx_safe': is_trx_safe,
                            'snowball_stage': 0}
                        if short_flag:
                            entry['_tp_s'] = SAFE_SHORT_TP
                            entry['_dd_t'] = SAFE_SHORT_PEAK_DD
                        if bounce and btc_safe:
                            entry['_tp_s'] = BOUNCE_TP_CHOPPY
                            entry['_dd_t'] = BOUNCE_PEAK_DD_CHOPPY
                            entry['_trail_dist'] = BOUNCE_TRAIL_DISTANCE_CHOPPY
                            entry['_trail_close'] = BOUNCE_TRAIL_CLOSE_CHOPPY
                            entry['_trail_act'] = BOUNCE_TRAIL_ACTIVATION_CHOPPY
                    entries.append(entry)
                    lei = idx

        # --- Equity tracking ---
        ureal = 0
        ureal = 0
        for e in entries:
            e_lev = e.get('lev', coin_lev)
            if not e.get('is_short',False): ureal += ((cc-e['ep'])/e['ep']*100)*e['mp']*tc*e_lev/BASE*e['rem']/100
            else: ureal += ((e['ep']-cc)/e['ep']*100)*e['mp']*tc*e_lev/BASE*e['rem']/100
        total_eq = eq + ureal; curve.append(total_eq)
        if d_cur.month == 12: yearly_eq[d_cur.year] = total_eq

    # --- Aggregate ---
    slc = sum(1 for t in trades if t['t']=='SL')
    tpc = sum(1 for t in trades if t['t'] in ('TP','TRAIL','SNOWBALL'))
    tot = slc+tpc; slr = slc/tot*100 if tot else 0
    peak = curve[0] if curve else eq; md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak-v)/peak*100
        if dd > md: md = dd
    years = len(curve)/2/365 if curve else 1
    teq = curve[-1] if curve else eq
    cagr = ((teq**(1/years)-1)*100) if years>0 and teq>0 else 0

    yearly_cagr = {}
    sorted_years = sorted(yearly_eq.keys())
    for i, year in enumerate(sorted_years):
        prev_eq = yearly_eq[sorted_years[i-1]] if i > 0 else 1.0
        yearly_cagr[year] = (yearly_eq[year] / prev_eq - 1) * 100

    cagr_22_25 = 0
    if 2021 in yearly_eq and 2025 in yearly_eq:
        cagr_22_25 = ((yearly_eq[2025] / yearly_eq[2021]) ** (1/4) - 1) * 100

    snowball_count = sum(1 for t in trades if t['t']=='SNOWBALL')
    trail_count = sum(1 for t in trades if t['t']=='TRAIL')
    rev_count = sum(1 for t in trades if t['t']=='TREND_REV')
    sl_count = sum(1 for t in trades if t['t']=='SL')

    result = {
        'cagr': cagr, 'dd': md, 'slr': slr, 'final': teq*BASE,
        'yearly': yearly_cagr, 'cagr_22_25': cagr_22_25, 'allow_short': allow_short,
        'snowball': snowball_count, 'trail': trail_count, 'trend_rev': rev_count, 'sl': sl_count
    }

    if use_cache:
        save_cached_result(coin, config_hash, result)

    return coin, result


def main():
    parser = argparse.ArgumentParser(description='BULL Snowball Backtest')
    parser.add_argument('--coin', type=str, help='Single coin')
    parser.add_argument('--coins', type=str, help='Multiple coins')
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--parallel', action='store_true')
    parser.add_argument('--years', type=str, help='Only trade these years (e.g. 2021,2023,2024). Go to cash in other years.')
    args = parser.parse_args()

    if args.coin: coins = [args.coin.upper()]
    elif args.coins: coins = [c.strip().upper() for c in args.coins.split(',')]
    else: coins = COINS[:]

    if args.years:
        selected_years = set(int(y.strip()) for y in args.years.split(','))
    else:
        selected_years = None

    print("=" * 80)
    print(f"BULL SNOWBALL BACKTEST - {', '.join(coins)}")
    if selected_years:
        print(f"(years: {sorted(selected_years)} | go to cash outside)")
    print("(snowball entries | NO SL in bull | trailing 11% at 40% ROI | trend reversal exit | bounce: per-coin TP, peak DD, trail)")
    print("=" * 80)

    print("\nLoading data...")
    data_cache = load_data()
    print(f"  Loaded {len(data_cache)} symbols")

    print("\nRunning backtests...")
    use_cache = not args.no_cache
    results = {}

    if args.parallel and len(coins) > 1:
        with ProcessPoolExecutor(max_workers=len(coins)) as executor:
            futures = {executor.submit(backtest_coin, (coin, data_cache, use_cache, selected_years)): coin for coin in coins}
            for future in as_completed(futures):
                coin, result = future.result()
                if result: results[coin] = result
    else:
        for coin in coins:
            coin, result = backtest_coin((coin, data_cache, use_cache, selected_years))
            if result: results[coin] = result

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    for coin in coins:
        if coin in results:
            r = results[coin]
            print(f"\n{coin}:")
            print(f"  CAGR: {r['cagr']:+.2f}%")
            print(f"  CAGR 22-25: {r['cagr_22_25']:+.2f}%")
            print(f"  Max DD: {r['dd']:.2f}%")
            print(f"  SL Rate: {r['slr']:.2f}%")
            print(f"  Final Equity: ${r['final']:,.2f}")
            print(f"  Trades: {r.get('snowball',0)} snowball, {r.get('trail',0)} trail, {r.get('trend_rev',0)} trend_rev, {r.get('sl',0)} SL")
            if 'yearly' in r and r['yearly']:
                print(f"  Yearly CAGR:")
                for year in sorted(r['yearly'].keys()):
                    print(f"    {year}: {r['yearly'][year]:+.2f}%")

    if len(results) > 1:
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        avg_cagr = mean(r['cagr'] for r in results.values())
        avg_dd = mean(r['dd'] for r in results.values())
        avg_slr = mean(r['slr'] for r in results.values())
        cagrs_22_25 = [r.get('cagr_22_25', 0) for r in results.values()]
        avg_cagr_22_25 = mean(cagrs_22_25) if cagrs_22_25 else 0
        print(f"Avg CAGR: {avg_cagr:+.2f}%")
        print(f"Avg CAGR 22-25: {avg_cagr_22_25:+.2f}%")
        print(f"Avg Max DD: {avg_dd:.2f}%")
        print(f"Avg SL Rate: {avg_slr:.2f}%")

    print("\nDONE")


if __name__ == "__main__":
    main()
