"""
Pooled Backtest — shared $10k equity, first-come-first-served signals.
All coins share one capital pool. Logic synced with combined_backtest.py.
"""
import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import (
    sma,
    BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE, BTC_SHORT_TP,
    MAX_CAP, EXT_BLOCK_PCT, fee_factor, PYRAMID_STRATEGIES,
    SHORT_MARGIN_CAP, SHORT_SL_ROI, winner_mult,
    load_data, fetch_paxg, entry_conditions, compute_results,
)


def total_asset_value_multi(all_entries, closes_map, eq, lev_map):
    val = eq
    for coin, entries in all_entries.items():
        if not entries: continue
        cc = closes_map.get(coin)
        if cc is None: continue
        lev = lev_map.get(coin, 1.5)
        for e in entries:
            if e.get('is_short'):
                val += (e['ep'] - cc) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
            else:
                val += (cc - e['ep']) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
    return val


def run_pooled(data, strategies):
    coin_data = {}
    timestamps = set()

    for label, coin_key, is_short, cfg in strategies:
        da = data.get(coin_key)
        if not da: continue
        closes = [c['close'] for c in da]
        vols = [c['volume'] for c in da]
        highs = [c['high'] for c in da]
        lows = [c['low'] for c in da]
        times = [c['time'] for c in da]
        ma_short = sma(closes, cfg.get('ma', 20))
        vol_ma20 = sma(vols, 20)
        coin_data[label] = {
            'closes': closes, 'vols': vols, 'highs': highs, 'lows': lows,
            'times': times, 'ma_short': ma_short, 'vol_ma20': vol_ma20,
            'n': len(closes), 'is_short': is_short, 'cfg': cfg,
        }
        for t in times[200:]:
            timestamps.add(t)

    tss = sorted(timestamps)
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    btc_closes = [c['close'] for c in btc_da]
    btc_times = [c['time'] for c in btc_da]
    btc_ma200 = sma(btc_closes, 200)
    btc_time_to_idx = {t: i for i, t in enumerate(btc_times)}

    entries_map = {label: [] for label, _, _, _ in strategies}
    lei_map = {label: -999 for label, _, _, _ in strategies}
    last_ep_map = {label: 0 for label, _, _, _ in strategies}
    last_sl_map = {label: -999 for label, _, _, _ in strategies}
    time_to_idx = {l: {t: i for i, t in enumerate(cd['times'])} for l, cd in coin_data.items()}

    eq = 1.0; curve = []; yearly_eq = {}; ts_curve = []

    for ts in tss:
        btc_bull = False
        btc_bull_exit = False
        if btc_ma200:
            btc_idx = btc_time_to_idx.get(ts)
            if btc_idx is not None and btc_idx >= 200 and btc_ma200[btc_idx]:
                btc_bull = btc_closes[btc_idx] >= btc_ma200[btc_idx] * 1.005
                btc_bull_exit = btc_closes[btc_idx] > btc_ma200[btc_idx] * 0.995

        dt = datetime.datetime.fromtimestamp(ts / 1000); yr = dt.year

        # ── Exits (all coins) ──
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            cc = cd['closes'][idx]; hi = cd['highs'][idx]; bl = cd['lows'][idx]
            is_short = cd['is_short']; cfg = cd['cfg']
            lev_coin = cfg.get('lev', 1.5)
            tp_sched = cfg.get('tp', TP_SCHEDULE)
            trail_pct = cfg.get('trail', TRAIL_PCT)
            ff = fee_factor(lev_coin)
            entries = entries_map[label]

            # Short: BTC bull close-all
            for e in entries[:]:
                if e.get('is_short') and btc_bull_exit:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                    eq += raw * e.get('rem', 1.0) / 100 * ff
                    entries.remove(e)

            # Short: SL check
            if is_short:
                for e in entries[:]:
                    roi = (e['ep'] - cc) / e['ep'] * 100 * lev_coin
                    if roi <= -SHORT_SL_ROI:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)
                        last_sl_map[label] = idx

            # Short + Long: TP ladder
            for e in entries[:]:
                roi = (e['ep'] - cc) / e['ep'] * 100 * lev_coin if is_short else (cc - e['ep']) / e['ep'] * 100 * lev_coin
                tp_stage = e.get('tp', 0)
                if tp_stage < len(tp_sched):
                    trg, cf = tp_sched[tp_stage]
                    if roi >= trg:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin if is_short else (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
                        eq += raw * cf / 100 * ff
                        e['rem'] = e.get('rem', 1.0) - cf
                        e['tp'] = tp_stage + 1
                        if e.get('rem', 1.0) <= 0.001:
                            entries.remove(e)

            # Long: trailing stop
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

        # ── Entries (collect signals, split capital equally) ──
        fired_signals = []
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            cc = cd['closes'][idx]; hi = cd['highs'][idx]; bl = cd['lows'][idx]
            is_short = cd['is_short']; cfg = cd['cfg']
            lev_coin = cfg.get('lev', 1.5)
            ma_buf = cfg.get('buf', 0.03)
            ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
            ma_slope = cfg.get('ma_slope', False)
            lower_high = cfg.get('lower_high', False)
            asym_buffer = cfg.get('asym_buffer', False)
            entries = entries_map[label]

            m_ma = cd['ma_short'][idx]; vavg = cd['vol_ma20'][idx]
            if m_ma is None or vavg is None or vavg == 0: continue

            should_enter, mult = entry_conditions(
                entries, cc, idx, cd['vols'], vavg, m_ma, ma_buf, is_short,
                btc_bull, ext_block, lev_coin, lei_map[label],
                ma=cd['ma_short'], highs=cd['highs'], lows=cd['lows'],
                ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer,
            )

            if should_enter:
                if is_short:
                    last_action = max(lei_map[label], last_sl_map[label])
                    if idx - last_action < 1:
                        should_enter = False
                    else:
                        mult = 1.0
                        short_mp = sum(e.get('mp', 0) for e in entries if e.get('is_short'))
                        if short_mp + eq * ENTRY_PCT * mult > SHORT_MARGIN_CAP:
                            should_enter = False

            if should_enter:
                fired_signals.append((label, is_short, mult, cc, cfg))

        if fired_signals:
            n = len(fired_signals)
            for label, is_short, mult, cc, cfg in fired_signals:
                total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                lev_map = {l: coin_data[l]['cfg'].get('lev', 1.5) for l in coin_data}
                total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                mp = eq * ENTRY_PCT * mult / n
                if total_dep + mp <= MAX_CAP * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short,
                          'hi': None if is_short else cc, 'lo': cc if is_short else None}
                    entries_map[label].append(e)
                    last_ep_map[label] = cc
                    lei_map[label] = idx

        # ── Pyramid (long only) ──
        for label, cd in coin_data.items():
            if cd['is_short']: continue
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            cc = cd['closes'][idx]
            cfg = cd['cfg']
            lev_coin = cfg.get('lev', 1.5)
            pyr_roi = cfg.get('pyr', 5)
            entries = entries_map[label]

            if not entries or last_ep_map[label] <= 0: continue
            if idx - lei_map[label] < 0: continue

            roi = (cc - last_ep_map[label]) / last_ep_map[label] * 100 * lev_coin
            if roi >= pyr_roi:
                total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                lev_map = {l: coin_data[l]['cfg'].get('lev', 1.5) for l in coin_data}
                total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                pyr_mult = winner_mult(entries, cc, False, lev_coin)
                mp = eq * ENTRY_PCT * pyr_mult
                if total_dep + mp <= MAX_CAP * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': False, 'hi': cc}
                    entries.append(e)
                    last_ep_map[label] = cc
                    lei_map[label] = idx

        # ── Unrealized PnL ──
        ureal = 0
        for label, entries in entries_map.items():
            lev_coin = coin_data[label]['cfg'].get('lev', 1.5)
            idx = time_to_idx[label].get(ts)
            if idx is None: continue
            cc = coin_data[label]['closes'][idx]
            ff = fee_factor(lev_coin)
            for e in entries:
                if e.get('is_short'):
                    roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                else:
                    roi = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
                ureal += roi * e.get('rem', 1.0) / 100 * ff

        total_eq = eq + ureal
        curve.append(total_eq); ts_curve.append((ts, total_eq))
        if dt.month == 12: yearly_eq[yr] = total_eq

    if curve:
        last_yr = datetime.datetime.fromtimestamp(tss[-1] / 1000).year
        if last_yr not in yearly_eq:
            yearly_eq[last_yr] = curve[-1]

    return compute_results(curve, yearly_eq, BASE)


def main():
    data = load_data()
    xau_da = fetch_paxg()
    data['XAUUSDT_POOL'] = xau_da

    strategies = [(f'{coin}-{"S" if is_short else "L"}',
                   'XAUUSDT_POOL' if coin == 'XAU' else f'{coin}USDT_4000_1609434000000',
                   is_short, cfg)
                  for coin, is_short, cfg in PYRAMID_STRATEGIES]

    r = run_pooled(data, strategies)
    print("POOLED BACKTEST — Shared $10k, first-come-first-served signals")
    print("=" * 70)
    print(f"{'Metric':<20} {'Value':>15}")
    print("-" * 70)
    print(f"{'CAGR':<20} {r['cagr']:>+14.1f}%")
    print(f"{'Max DD':<20} {r['dd']:>14.1f}%")
    print(f"{'Final equity':<20} ${r['final']:>14,.0f}")
    print("-" * 70)
    print(f"{'Year':<8} {'Return':>12}")
    print("-" * 70)
    for y in sorted(r['yearly'].keys()):
        print(f"{y:<8} {r['yearly'][y]:>+11.1f}%")
    print("=" * 70)


if __name__ == '__main__':
    main()
