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
    PYRAMID_ROI_DEFAULT,
    EXT_BLOCK_PCT, fee_factor, PYRAMID_STRATEGIES,
    LONG_TP, LONG_MAX_MARGIN, LONG_PYRAMID_DOUBLE,
    SHORT_TP, SHORT_MAX_MARGIN, SHORT_CLOSE_PCT,
    SHORT_COOLDOWN_ENTRY,
    load_data, fetch_paxg, total_asset_value, compute_results,
    entry_conditions, winner_mult,
)


def backtest_coin(coin, da, btc_da, is_short, cfg=None):
    if not da or len(da) < 60: return coin, None
    if cfg is None: cfg = {}
    lev_coin = cfg.get('lev', 1.8)
    ma_period = cfg.get('ma', MA_PERIOD)
    ma_buf = cfg.get('buf', MA_BUF)
    pyr_roi = cfg.get('pyr', PYRAMID_ROI_DEFAULT)
    tp_sched = cfg.get('tp', SHORT_TP if is_short else LONG_TP)
    trail_pct = cfg.get('trail', TRAIL_PCT)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    close_pct = cfg.get('close_pct', 0.20)
    ma_slope = cfg.get('ma_slope', False)
    lower_high = cfg.get('lower_high', False)
    asym_buffer = cfg.get('asym_buffer', False)
    max_margin = SHORT_MAX_MARGIN if is_short else LONG_MAX_MARGIN

    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    highs = [c['high'] for c in da]; lows = [c['low'] for c in da]
    ma_short = sma(closes, ma_period); vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None

    entries = []; eq = 1.0; lei = -999; last_ep = 0
    curve = []; yearly_eq = {}; ts_curve = []
    ff = fee_factor(lev_coin)
    double_cd = 0
    last_sl_bar = -999
    long_tp_hit = 0; short_tp_hit = 0; pyr_tier_hit = 0

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
        )

        active_entries = entries[:]

        # ── Compute avg EP per side (long/short) ──
        long_entries = [e for e in active_entries if not e.get('is_short')]
        short_entries = [e for e in active_entries if e.get('is_short')]
        avg_ep_long = sum(e['ep'] * e['mp'] * e.get('rem', 1.0) for e in long_entries) / max(sum(e['mp'] * e.get('rem', 1.0) for e in long_entries), 1e-10) if long_entries else None
        avg_ep_short = sum(e['ep'] * e['mp'] * e.get('rem', 1.0) for e in short_entries) / max(sum(e['mp'] * e.get('rem', 1.0) for e in short_entries), 1e-10) if short_entries else None

        # ── Long: close check (trailing) ──
        if long_entries:
            peak_hi = max(max(e.get('hi', cc) for e in long_entries), hi)
            if cc <= peak_hi * trail_pct:
                for e in entries[:]:
                    if not e.get('is_short'):
                        raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)
            else:
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
                    total_long_mp = sum(e['mp'] * e.get('rem', 1.0) for e in long_entries)
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

        # ── Short: close check (trailing) ──
        if short_entries:
            trough_lo = min(min(e.get('lo', cc) for e in short_entries), bl)
            if cc >= trough_lo * (1 + SHORT_CLOSE_PCT):
                for e in entries[:]:
                    if e.get('is_short'):
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)
                last_sl_bar = idx
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
                    total_short_mp = sum(e['mp'] * e.get('rem', 1.0) for e in short_entries)
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

        # ── Entry ──
        dep = sum(e.get('mp', 0) for e in entries)
        total_val = total_asset_value(entries, cc, eq, lev_coin)

        # Cooldown
        if is_short and idx - max(lei, last_sl_bar) < SHORT_COOLDOWN_ENTRY:
            should_enter = False

        if should_enter and not is_short:
            mult = winner_mult(entries, cc, False, lev_coin)

        if should_enter:
            if is_short:
                short_mp = sum(e.get('mp', 0) for e in entries if e.get('is_short'))
                if short_mp + eq * ENTRY_PCT * mult > SHORT_MAX_MARGIN:
                    should_enter = False

        if should_enter:
            mp = eq * ENTRY_PCT * mult
            if is_short:
                mp *= 2

            if dep + mp <= max_margin * total_val:
                e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short,
                      'hi': None if is_short else cc, 'lo': cc if is_short else None}
                entries.append(e)
                last_ep = cc; lei = idx

        # ── Pyramid tiers: at ROI X/Y/Z% → ×2 entry ──
        if not is_short and long_entries and avg_ep_long and pyr_tier_hit < 3:
            roi = (cc - avg_ep_long) / avg_ep_long * 100 * lev_coin
            tiers = cfg.get('_tiers', [7, 12, 17])
            if pyr_tier_hit < len(tiers):
                trg = tiers[pyr_tier_hit]
                if roi >= trg:
                    mp = eq * ENTRY_PCT * 2
                    if dep + mp <= max_margin * total_val:
                        e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': False, 'hi': cc, 'lo': None}
                        entries.append(e)
                        pyr_tier_hit += 1
                        last_ep = cc; lei = idx
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
            row += f"{r['cagr']:>+7.1f}%  {r['dd']:>7.1f}%  {cfg.get('lev', 1.5):>4.1f}x"
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
