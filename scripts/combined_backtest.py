"""
Combined Long + Short Pyramid Strategy
- Long: TRX/XAU — TP 5-stage, trailing close, ×2 sizing at 10% ROI
- Short: BTC — TP 4-stage, trailing close, no pyramid, 2d cooldown
"""
from pathlib import Path
import sys, datetime
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import (
    sma,
    BASE, ENTRY_PCT, TRAIL_PCT, MA_BUF, MA_PERIOD,
    EXT_BLOCK_PCT, fee_factor, PYRAMID_STRATEGIES,
    LONG_TP, LONG_MAX_MARGIN,
    SHORT_TP, SHORT_MAX_MARGIN, SHORT_CLOSE_PCT,
    SHORT_COOLDOWN_ENTRY,
    load_data, fetch_paxg, total_asset_value, compute_results,
    entry_conditions, winner_mult, avg_entry,
)


def backtest_coin(coin, da, btc_da, is_short, cfg=None):
    if not da or len(da) < 60: return coin, None
    if cfg is None: cfg = {}
    e_cfg = cfg.get('entry', {}); exit_cfg = cfg.get('exit', {})
    lev_coin = e_cfg.get('lev', 1.8)
    ma_period = e_cfg.get('ma', MA_PERIOD)
    ma_buf = e_cfg.get('buffer', MA_BUF)
    tp_sched = exit_cfg.get('tp', SHORT_TP if is_short else LONG_TP)
    trail_pct = exit_cfg.get('trail', TRAIL_PCT)
    ext_block = e_cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_slope = e_cfg.get('ma_slope', False)
    lower_high = e_cfg.get('lower_high', False)
    asym_buffer = e_cfg.get('asym_buffer', False)
    vol_bars = e_cfg.get('vol_bars', 2)
    green_min_count = e_cfg.get('green_min_count', 0)
    green_window = e_cfg.get('green_window', 0)
    max_margin = SHORT_MAX_MARGIN if is_short else LONG_MAX_MARGIN

    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    opens = [c.get('open', c['close']) for c in da]
    highs = [c['high'] for c in da]; lows = [c['low'] for c in da]
    ma_short = sma(closes, ma_period); vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None

    entries = []; eq = 1.0; lei = -999; last_ep = 0
    curve = []; yearly_eq = {}; ts_curve = []
    ff = fee_factor(lev_coin)
    last_sl_bar = -999
    long_tp_hit = 0; short_tp_hit = 0; next_pyr_roi = 8; pyr_bar = -999

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        m_ma = ma_short[idx]; vavg = vol_ma20[idx]
        if m_ma is None or vavg is None or vavg == 0: continue

        # BTC regime
        btc_bull = False
        if btc_ma200:
            btc_idx = min(idx, len(btc_closes) - 1)
            if btc_idx >= 200 and btc_ma200[btc_idx]:
                btc_bull = btc_closes[btc_idx] >= btc_ma200[btc_idx] * 1.005

        # ── Entry check (shared) ──
        should_enter, mult = entry_conditions(
            entries, cc, idx, vols, vavg, m_ma, ma_buf, is_short,
            btc_bull, ext_block, lev_coin, lei,
            ma=ma_short, highs=highs, lows=lows,
            ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer,
            vol_bars=vol_bars, green_min_count=green_min_count,
            green_window=green_window, opens=opens, closes=closes,
        )

        active_entries = entries[:]

        # ── Compute avg EP per side (long/short) ──
        long_entries = [e for e in active_entries if not e.get('is_short')]
        short_entries = [e for e in active_entries if e.get('is_short')]
        avg_ep_long, _ = avg_entry(long_entries) if long_entries else (None, 0)
        avg_ep_short, _ = avg_entry(short_entries) if short_entries else (None, 0)

        # ── Long: close check (trailing or MA crossover) ──
        if long_entries:
            exit_mode = exit_cfg.get('mode', 'trailing')
            if exit_mode == 'ma_cross':
                ma_s = sma(closes, exit_cfg.get('ma_short', 40))
                ma_l = sma(closes, exit_cfg.get('ma_long', 90))
                mbuf = exit_cfg.get('buffer', 0.03)
                close_trigger = (idx >= exit_cfg.get('ma_long', 90)
                                 and ma_s[idx] is not None and ma_l[idx] is not None
                                 and ma_s[idx] < ma_l[idx] * (1 - mbuf))
            else:
                peak_hi = max(max(e.get('hi', cc) for e in long_entries), hi)
                close_trigger = bl <= peak_hi * trail_pct

            if close_trigger:
                for e in entries[:]:
                    if not e.get('is_short'):
                        raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)
                if not [e for e in entries if not e.get('is_short')]:
                    long_tp_hit = 0
            elif exit_mode != 'ma_cross':
                for e in entries:
                    if not e.get('is_short'):
                        e['hi'] = peak_hi

        # ── Long: TP check (by avg EP) ──
        if not is_short and long_entries and tp_sched and 'tp' in cfg and long_tp_hit < len(tp_sched):
            roi = (cc - avg_ep_long) / avg_ep_long * 100 * lev_coin
            hit = 0
            for stage in range(long_tp_hit, len(tp_sched)):
                trg, cf = tp_sched[stage]
                if roi >= trg:
                    hit = stage + 1
                else:
                    break
            if hit > long_tp_hit:
                for stage in range(long_tp_hit, hit):
                    trg, cf = tp_sched[stage]
                    _, total_long_mp = avg_entry(long_entries)
                    close_amt = total_long_mp * cf
                    for e in entries[:]:
                        if not e.get('is_short') and close_amt > 0:
                            rem_frac = min(e.get('rem', 1.0), close_amt / e['mp'])
                            raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * rem_frac
                            eq += raw / 100 * ff
                            e['rem'] = e.get('rem', 1.0) - rem_frac
                            close_amt -= rem_frac * e['mp']
                            if e.get('rem', 1.0) <= 0.001:
                                entries.remove(e)
                    long_tp_hit = hit
                if not [e for e in entries if not e.get('is_short')]:
                    long_tp_hit = 0

        # ── Short: close check (trailing) ──
        if short_entries:
            trough_lo = min(min(e.get('lo', cc) for e in short_entries), bl)
            if hi >= trough_lo * (1 + SHORT_CLOSE_PCT):
                for e in entries[:]:
                    if e.get('is_short'):
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)
                last_sl_bar = idx
                if not [e for e in entries if e.get('is_short')]:
                    short_tp_hit = 0
            else:
                for e in entries:
                    if e.get('is_short'):
                        e['lo'] = trough_lo

        # ── Short: TP check (by avg EP) ──
        if is_short and short_entries and tp_sched and short_tp_hit < len(tp_sched):
            roi = (avg_ep_short - cc) / avg_ep_short * 100 * lev_coin
            hit = 0
            for stage in range(short_tp_hit, len(tp_sched)):
                trg, cf = tp_sched[stage]
                if roi >= trg:
                    hit = stage + 1
                else:
                    break
            if hit > short_tp_hit:
                for stage in range(short_tp_hit, hit):
                    trg, cf = tp_sched[stage]
                    _, total_short_mp = avg_entry(short_entries)
                    close_amt = total_short_mp * cf
                    for e in entries[:]:
                        if e.get('is_short') and close_amt > 0:
                            rem_frac = min(e.get('rem', 1.0), close_amt / e['mp'])
                            raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * rem_frac
                            eq += raw / 100 * ff
                            e['rem'] = e.get('rem', 1.0) - rem_frac
                            close_amt -= rem_frac * e['mp']
                            if e.get('rem', 1.0) <= 0.001:
                                entries.remove(e)
                    short_tp_hit = hit
                if not [e for e in entries if e.get('is_short')]:
                    short_tp_hit = 0

        # ── Entry ──
        dep = sum(e.get('mp', 0) for e in entries)
        total_val = total_asset_value(entries, cc, eq, lev_coin)

        # Cooldown
        if is_short and idx - max(lei, last_sl_bar) < SHORT_COOLDOWN_ENTRY:
            should_enter = False

        if should_enter and not is_short:
            mult = winner_mult(entries, cc, False, lev_coin)
        elif should_enter and is_short:
            mult = 1.0

        if should_enter:
            mp = eq * ENTRY_PCT * mult * cfg.get('pyramid', {}).get('entry_mult', 1.0)
            if is_short:
                mp *= e_cfg.get('short_mult', 2.0)

            if dep + mp <= max_margin * total_val:
                e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short,
                      'hi': None if is_short else cc, 'lo': cc if is_short else None}
                entries.append(e)
                last_ep = cc; lei = idx

        # ── Pyramid: 1/day, ROI >= next_pyr_roi → entry ──
        if cfg.get('pyramid', {}).get('enabled', False) and not is_short and long_entries and avg_ep_long and idx - pyr_bar >= 1:
            roi = (cc - avg_ep_long) / avg_ep_long * 100 * lev_coin
            if roi >= next_pyr_roi:
                mt = eq * ENTRY_PCT * cfg.get('pyramid', {}).get('entry_mult', 1.0)
                if dep + mt <= max_margin * total_val:
                    e = {'ep': cc, 'mp': mt, 'rem': 1.0, 'tp': 0, 'is_short': False, 'hi': cc}
                    entries.append(e)
                    next_pyr_roi += 7
                    pyr_bar = idx
                    last_ep = cc; lei = idx
        if not is_short and not long_entries:
            next_pyr_roi = 8

        # ── Short Pyramid ──
        if cfg.get('pyramid', {}).get('enabled', False) and is_short and short_entries and avg_ep_short and idx - pyr_bar >= 1:
            roi = (avg_ep_short - cc) / avg_ep_short * 100 * lev_coin
            if roi >= next_pyr_roi:
                mt = eq * ENTRY_PCT * cfg.get('pyramid', {}).get('entry_mult', 1.0)
                mt *= e_cfg.get('short_mult', 2.0)
                if dep + mt <= max_margin * total_val:
                    e = {'ep': cc, 'mp': mt, 'rem': 1.0, 'tp': 0, 'is_short': True, 'lo': cc}
                    entries.append(e)
                    pyr_step = cfg.get('pyramid', {}).get('pyr_step', 7)
                    next_pyr_roi += pyr_step
                    pyr_bar = idx
                    last_ep = cc; lei = idx
        if is_short and not short_entries:
            next_pyr_roi = 8

        ureal = 0
        for e in entries:
            if e.get('is_short'):
                roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
            else:
                roi = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
            ureal += roi * e.get('rem', 1.0) / 100 * ff
        total_eq = eq + ureal
        curve.append(total_eq); ts_curve.append((da[idx]['time'], total_eq))
        if dt.month == 12: yearly_eq[yr] = total_eq

    if curve:
        last_yr = datetime.datetime.fromtimestamp(da[-1]['time'] / 1000).year
        if last_yr not in yearly_eq:
            yearly_eq[last_yr] = curve[-1]

    results = compute_results(curve, yearly_eq, BASE)
    results['ts_curve'] = ts_curve
    return coin, results


def main():
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    xau_da = fetch_paxg()

    strategies = [(f'{coin}-{"S" if is_short else "L"}', coin, is_short, cfg)
                  for coin, is_short, cfg in PYRAMID_STRATEGIES]

    results = {}
    for label, coin, is_short, cfg in strategies:
        sym = f'{coin}USDT_4000_1609434000000'
        da = xau_da if coin == 'XAU' else data.get(sym, [])
        res = backtest_coin(coin, da, btc_da, is_short, cfg)
        if res[1]: results[label] = res[1]

    curves = [results[s[0]]['ts_curve'] for s in strategies if s[0] in results]
    merged = {}
    for curve in curves:
        for ts, eq in curve:
            merged[ts] = merged.get(ts, []) + [eq]
    tss = sorted(merged.keys())
    pf_curve = []
    yearly = {}
    peak = 1.0; md = 0
    for ts in tss:
        vals = merged[ts]
        if len(vals) != len(curves): continue
        avg_eq = sum(vals) / len(vals)
        pf_curve.append(avg_eq)
        if avg_eq > peak: peak = avg_eq
        dd = (peak - avg_eq) / peak * 100
        if dd > md: md = dd
        yr = datetime.datetime.fromtimestamp(ts / 1000).year
        yearly[yr] = avg_eq
    pf_res = compute_results(pf_curve, yearly, BASE)

    print("=" * 70)
    print("COMBINED LONG + SHORT — YEARLY CAGR (per-coin tuned)")
    print("=" * 70)
    years = list(range(2021, 2027))
    header = f"{'Strategy':<12}" + "".join(f"{y:>8}" for y in years) + f"{'CAGR':>8}  {'Max DD':>8}  {'Lev':>5}"
    print(header)
    print("-" * 70)
    for label, coin, is_short, cfg in strategies:
        if label in results:
            r = results[label]
            row = f"{label:<12}"
            for y in years:
                row += f"{r['yearly'].get(y, 0):>+7.1f}%"
            row += f"{r['cagr']:>+7.1f}%  {r['dd']:>7.1f}%  {cfg.get('entry', {}).get('lev', 1.5):>4.1f}x"
            print(row)
    print("-" * 70)
    row = f"{'Portfolio':<12}"
    for y in years:
        row += f"{pf_res['yearly'].get(y, 0):>+7.1f}%"
    row += f"{pf_res['cagr']:>+7.1f}%  {md:>7.1f}%"
    print(row)
    print("=" * 70)


if __name__ == '__main__':
    main()
