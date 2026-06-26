"""
Combined Long + Short Pyramid Strategy (standalone per-coin)
- Long: TRX, PAXG — MA pullback entry, no BTC gate
- Short: BTC only — only when BTC < MA200
- 75% max margin cap per coin (cap on margin, not position size)
- Block pyramid adds when price >25% from lowest entry price
"""
from pathlib import Path
import sys, datetime, requests, time
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import (
    sma,
    BASE, ENTRY_PCT, TRAIL_PCT, MA_BUF, MA_PERIOD,
    PYRAMID_ROI_DEFAULT, TP_SCHEDULE, BTC_SHORT_TP,
    MAX_CAP, EXT_BLOCK_PCT, fee_factor,
    load_data, fetch_paxg, total_asset_value, compute_results,
    entry_conditions,
)


def backtest_coin(coin, da, btc_da, is_short, max_cap, selected_years, cfg=None):
    if not da or len(da) < 60: return coin, None
    if cfg is None: cfg = {}
    lev_coin = cfg.get('lev', 1.8)
    ma_period = cfg.get('ma', MA_PERIOD)
    ma_buf = cfg.get('buf', MA_BUF)
    pyr_roi = cfg.get('pyr', PYRAMID_ROI_DEFAULT)
    tp_sched = cfg.get('tp', TP_SCHEDULE)
    trail_pct = cfg.get('trail', TRAIL_PCT)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_slope = cfg.get('ma_slope', False)
    lower_high = cfg.get('lower_high', False)
    asym_buffer = cfg.get('asym_buffer', False)

    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    highs = [c['high'] for c in da]; lows = [c['low'] for c in da]
    ma_short = sma(closes, ma_period); vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None

    entries = []; eq = 1.0; lei = -999; last_ep = 0
    curve = []; yearly_eq = {}; ts_curve = []
    ff = fee_factor(lev_coin)

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            for e in entries:
                if e.get('is_short'):
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                else:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
                eq += raw * e.get('rem', 1.0) / 100 * ff
            entries = []
            curve.append(eq); ts_curve.append((da[idx]['time'], eq))
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m_ma = ma_short[idx]; vavg = vol_ma20[idx]
        if m_ma is None or vavg is None or vavg == 0: continue

        # BTC regime
        btc_bull = False
        if btc_ma200:
            btc_idx = min(idx, len(btc_closes) - 1)
            if btc_idx >= 200 and btc_ma200[btc_idx]:
                # Entry generous: short when BTC < MA200 * 1.005; Exit tight: close when BTC > MA200 * 0.995
                btc_bull = btc_closes[btc_idx] >= btc_ma200[btc_idx] * 1.005
                btc_bull_exit = btc_closes[btc_idx] > btc_ma200[btc_idx] * 0.995

        # ── Entry check (shared) ──
        should_enter, mult = entry_conditions(
            entries, cc, idx, vols, vavg, m_ma, ma_buf, is_short,
            btc_bull, ext_block, lev_coin, lei,
            ma=ma_short, highs=highs, lows=lows,
            ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer,
        )

        # ── BTC regime exit (shorts exit on bull) ──
        for e in entries[:]:
            if e.get('is_short') and btc_bull_exit:
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                eq += raw * e.get('rem', 1.0) / 100 * ff
                entries.remove(e)

        # ── Short: TP ladder ──
        for e in entries[:]:
            if e.get('is_short'):
                roi = (e['ep'] - cc) / e['ep'] * 100 * lev_coin
                tp_stage = e.get('tp', 0)
                if tp_stage < len(tp_sched):
                    trg, cf = tp_sched[tp_stage]
                    if roi >= trg:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                        eq += raw * cf / 100 * ff
                        e['rem'] = e.get('rem', 1.0) - cf
                        e['tp'] = tp_stage + 1
                        if e.get('rem', 1.0) <= 0.001: entries.remove(e)

        # ── Fixed stop loss (matching live: LONG -20%, SHORT +13%) ──
        for e in entries[:]:
            if e.get('is_short'):
                if cc >= e['ep'] * 1.13:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                    eq += raw / 100 * ff
                    entries.remove(e)
            else:
                if cc <= e['ep'] * 0.80:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                    eq += raw / 100 * ff
                    entries.remove(e)

        # ── Long: combined trailing stop (single peak for all entries, matching live) ──
        long_entries = [e for e in entries if not e.get('is_short')]
        if long_entries:
            peak_hi = max(e.get('hi', cc) for e in long_entries)
            peak_hi = max(peak_hi, hi)
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

        # ── Entry ──
        can_enter_long = not is_short
        can_enter_short = is_short and not btc_bull
        active = can_enter_long or can_enter_short
        dep = sum(e.get('mp', 0) for e in entries)
        total_val = total_asset_value(entries, cc, eq, lev_coin)

        if should_enter:
            mp = eq * ENTRY_PCT / lev_coin * mult
            if dep + mp <= max_cap * total_val:
                e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short, 'hi': cc}

                entries.append(e)
                last_ep = cc; lei = idx

        # ── Pyramid ──
        if active and last_ep > 0 and (idx - lei >= 0) and mult > 0:
            if can_enter_long:
                roi = (cc - last_ep) / last_ep * 100 * lev_coin
            else:
                roi = (last_ep - cc) / last_ep * 100 * lev_coin
            if roi >= pyr_roi:
                dep = sum(e.get('mp', 0) for e in entries)
                total_val = total_asset_value(entries, cc, eq, lev_coin)
                mp = eq * ENTRY_PCT / lev_coin * mult
                if dep + mp <= max_cap * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short, 'hi': cc}
                    entries.append(e)
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

    # Capture final partial year
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

    strategies = [
        ('TRX-L',  'TRX',  False, MAX_CAP, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('XAU-L',  'XAU',  False, MAX_CAP, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8, 'lower_high': True}),
        ('BTC-S',  'BTC',  True,  MAX_CAP, {'ma': 5,  'buf': 0.05, 'pyr': 3, 'lev': 1.6, 'tp': BTC_SHORT_TP}),
    ]

    results = {}
    for label, coin, is_short, max_cap, cfg in strategies:
        sym = f'{coin}USDT_4000_1609434000000'
        da = xau_da if coin == 'XAU' else data.get(sym, [])
        res = backtest_coin(coin, da, btc_da, is_short, max_cap, None, cfg)
        if res[1]: results[label] = res[1]

    # Merge portfolio (equal-weight)
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
    for label, coin, is_short, max_cap, cfg in strategies:
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
