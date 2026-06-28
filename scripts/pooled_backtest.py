"""
Pooled Backtest — shared $10k equity, FCFS signals.
Fully synced with combined_backtest.py.
"""
import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import (
    sma,
    BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE,
    MAX_CAP, EXT_BLOCK_PCT, fee_factor, PYRAMID_STRATEGIES,
    SHORT_MAX_MARGIN, SHORT_CLOSE_PCT, SHORT_COOLDOWN_ENTRY, winner_mult,
    load_data, fetch_paxg, entry_conditions, compute_results, avg_entry,
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
        opens = [c.get('open', c['close']) for c in da]
        highs = [c['high'] for c in da]
        lows = [c['low'] for c in da]
        times = [c['time'] for c in da]
        ma_short = sma(closes, cfg.get('entry', {}).get('ma', 20))
        vol_ma20 = sma(vols, 20)
        coin_data[label] = {
            'closes': closes, 'vols': vols, 'opens': opens,
            'highs': highs, 'lows': lows,
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
    # Per-coin states
    next_pyr_roi_map = {label: 8 for label in coin_data}
    pyr_bar_map = {label: -999 for label in coin_data}
    long_tp_hit_map = {label: 0 for label in coin_data}
    short_tp_hit_map = {label: 0 for label in coin_data}

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
            e_cfg = cfg.get('entry', {}); exit_cfg = cfg.get('exit', {})
            lev_coin = e_cfg.get('lev', 1.5)
            tp_sched = exit_cfg.get('tp', TP_SCHEDULE)
            trail_pct = exit_cfg.get('trail', TRAIL_PCT)
            ff = fee_factor(lev_coin)
            entries = entries_map[label]

            # Short: BTC bull close-all
            for e in entries[:]:
                if e.get('is_short') and btc_bull_exit:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                    eq += raw * e.get('rem', 1.0) / 100 * ff
                    entries.remove(e)
            if not [e for e in entries if e.get('is_short')]:
                short_tp_hit_map[label] = 0

            # Long: close check (trailing or MA crossover)
            long_entries = [e for e in entries if not e.get('is_short')]
            if long_entries:
                exit_mode = exit_cfg.get('mode', 'trailing')
                if exit_mode == 'ma_cross':
                    ma_s = sma(cd['closes'], exit_cfg.get('ma_short', 40))
                    ma_l_vals = sma(cd['closes'], exit_cfg.get('ma_long', 90))
                    mbuf = exit_cfg.get('buffer', 0.03)
                    close_trigger = (idx >= exit_cfg.get('ma_long', 90)
                                     and ma_s[idx] is not None and ma_l_vals[idx] is not None
                                     and ma_s[idx] < ma_l_vals[idx] * (1 - mbuf))
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
                        long_tp_hit_map[label] = 0
                elif exit_mode != 'ma_cross':
                    for e in entries:
                        if not e.get('is_short'):
                            e['hi'] = peak_hi

            # Short: trailing close
            short_entries = [e for e in entries if e.get('is_short')]
            if short_entries:
                trough_lo = min(min(e.get('lo', cc) for e in short_entries), bl)
                if hi >= trough_lo * (1 + SHORT_CLOSE_PCT):
                    for e in entries[:]:
                        if e.get('is_short'):
                            raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                            eq += raw / 100 * ff
                            entries.remove(e)
                    last_sl_map[label] = idx
                    if not [e for e in entries if e.get('is_short')]:
                        short_tp_hit_map[label] = 0
                else:
                    for e in entries:
                        if e.get('is_short'):
                            e['lo'] = trough_lo

            # TP check (by avg EP)
            long_tp_entries = [e for e in entries if not e.get('is_short')] if 'tp' in cfg else []
            short_tp_entries = [e for e in entries if e.get('is_short')] if tp_sched else []
            
            if long_tp_entries and long_tp_hit_map[label] < len(tp_sched):
                avg_ep, total_mp = avg_entry(long_tp_entries)
                roi = (cc - avg_ep) / avg_ep * 100 * lev_coin
                hit = 0
                for stage in range(long_tp_hit_map[label], len(tp_sched)):
                    trg, cf = tp_sched[stage]
                    if roi >= trg:
                        hit = stage + 1
                    else:
                        break
                if hit > long_tp_hit_map[label]:
                    for stage in range(long_tp_hit_map[label], hit):
                        trg, cf = tp_sched[stage]
                        close_amt = total_mp * cf
                        for e in entries[:]:
                            if not e.get('is_short') and close_amt > 0:
                                rem_frac = min(e.get('rem', 1.0), close_amt / e['mp'])
                                raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * rem_frac
                                eq += raw / 100 * ff
                                e['rem'] = e.get('rem', 1.0) - rem_frac
                                close_amt -= rem_frac * e['mp']
                                if e.get('rem', 1.0) <= 0.001:
                                    entries.remove(e)
                        long_tp_hit_map[label] = hit
                if not [e for e in entries if not e.get('is_short')]:
                    long_tp_hit_map[label] = 0

            if short_tp_entries:
                avg_ep, total_mp = avg_entry(short_tp_entries)
                roi = (avg_ep - cc) / avg_ep * 100 * lev_coin
                hit = 0
                for stage in range(short_tp_hit_map[label], len(tp_sched)):
                    trg, cf = tp_sched[stage]
                    if roi >= trg:
                        hit = stage + 1
                    else:
                        break
                if hit > short_tp_hit_map[label]:
                    for stage in range(short_tp_hit_map[label], hit):
                        trg, cf = tp_sched[stage]
                        close_amt = total_mp * cf
                        for e in entries[:]:
                            if e.get('is_short') and close_amt > 0:
                                rem_frac = min(e.get('rem', 1.0), close_amt / e['mp'])
                                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * rem_frac
                                eq += raw / 100 * ff
                                e['rem'] = e.get('rem', 1.0) - rem_frac
                                close_amt -= rem_frac * e['mp']
                                if e.get('rem', 1.0) <= 0.001:
                                    entries.remove(e)
                        short_tp_hit_map[label] = hit
                if not [e for e in entries if e.get('is_short')]:
                    short_tp_hit_map[label] = 0

        # ── Entries (collect signals, split capital equally) ──
        fired_signals = []
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            cc = cd['closes'][idx]
            is_short = cd['is_short']; cfg = cd['cfg']
            e_cfg = cfg.get('entry', {})
            lev_coin = e_cfg.get('lev', 1.5)
            ma_buf = e_cfg.get('buffer', 0.03)
            ext_block = e_cfg.get('ext_block', EXT_BLOCK_PCT)
            ma_slope = e_cfg.get('ma_slope', False)
            lower_high = e_cfg.get('lower_high', False)
            asym_buffer = e_cfg.get('asym_buffer', False)
            vol_bars = e_cfg.get('vol_bars', 2)
            green_min_count = e_cfg.get('green_min_count', 0)
            green_window = e_cfg.get('green_window', 0)
            entries = entries_map[label]

            m_ma = cd['ma_short'][idx]; vavg = cd['vol_ma20'][idx]
            if m_ma is None or vavg is None or vavg == 0: continue

            should_enter, mult = entry_conditions(
                entries, cc, idx, cd['vols'], vavg, m_ma, ma_buf, is_short,
                btc_bull, ext_block, lev_coin, lei_map[label],
                ma=cd['ma_short'], highs=cd['highs'], lows=cd['lows'],
                ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer,
                vol_bars=vol_bars, green_min_count=green_min_count,
                green_window=green_window, opens=cd['opens'], closes=cd['closes'],
            )

            if should_enter:
                if is_short:
                    last_action = max(lei_map[label], last_sl_map[label])
                    if idx - last_action < SHORT_COOLDOWN_ENTRY:
                        should_enter = False
                    else:
                        mult = 1.0
                        short_mp = sum(e.get('mp', 0) for e in entries if e.get('is_short'))
                        if short_mp + eq * ENTRY_PCT * mult > SHORT_MAX_MARGIN:
                            should_enter = False
                elif not is_short:
                    mult = winner_mult(entries, cc, False, lev_coin)

            if should_enter:
                fired_signals.append((label, is_short, mult, cc, cfg))

        if fired_signals:
            n = len(fired_signals)
            for label, is_short, mult, cc, cfg in fired_signals:
                total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                lev_map = {l: coin_data[l]['cfg'].get('entry', {}).get('lev', 1.5) for l in coin_data}
                total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                mp = eq * ENTRY_PCT * mult / n * cfg.get('pyramid', {}).get('entry_mult', 1.0)
                if is_short:
                    mp *= cfg['entry'].get('short_mult', 2.0)
                if total_dep + mp <= MAX_CAP * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short,
                          'hi': None if is_short else cc, 'lo': cc if is_short else None}
                    entries_map[label].append(e)
                    last_ep_map[label] = cc
                    lei_map[label] = idx

        # ── Long Pyramid: ROI-based, 1/day ──
        for label, cd in coin_data.items():
            if cd['is_short'] or not cd['cfg'].get('pyramid', {}).get('enabled', False): continue
            entries = entries_map[label]
            long_entries = [e for e in entries if not e.get('is_short')]
            if not long_entries:
                next_pyr_roi_map[label] = 8
                continue
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            if idx - pyr_bar_map[label] < 1: continue
            cc = cd['closes'][idx]
            avg_ep, _ = avg_entry(long_entries)
            lev_coin = cd['cfg'].get('entry', {}).get('lev', 1.5)
            roi = (cc - avg_ep) / avg_ep * 100 * lev_coin
            if roi >= next_pyr_roi_map[label]:
                mp = eq * ENTRY_PCT * cd['cfg'].get('pyramid', {}).get('entry_mult', 1.0)
                total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                lev_map = {l: coin_data[l]['cfg'].get('entry', {}).get('lev', 1.5) for l in coin_data}
                total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                if total_dep + mp <= MAX_CAP * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': False, 'hi': cc}
                    entries.append(e)
                    next_pyr_roi_map[label] += 7
                    pyr_bar_map[label] = idx
                    last_ep_map[label] = cc
                    lei_map[label] = idx

        # ── Short Pyramid ──
        for label, cd in coin_data.items():
            if not cd['is_short'] or not cd['cfg'].get('pyramid', {}).get('enabled', False): continue
            entries = entries_map[label]
            short_entries = [e for e in entries if e.get('is_short')]
            if not short_entries:
                next_pyr_roi_map[label] = 8
                continue
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            if idx - pyr_bar_map[label] < 1: continue
            cc = cd['closes'][idx]
            avg_ep, _ = avg_entry(short_entries)
            lev_coin = cd['cfg'].get('entry', {}).get('lev', 1.5)
            roi = (avg_ep - cc) / avg_ep * 100 * lev_coin
            if roi >= next_pyr_roi_map[label]:
                mp = eq * ENTRY_PCT * cd['cfg'].get('pyramid', {}).get('entry_mult', 1.0)
                mp *= cd['cfg']['entry'].get('short_mult', 2.0)
                total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                lev_map = {l: coin_data[l]['cfg'].get('entry', {}).get('lev', 1.5) for l in coin_data}
                total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                if total_dep + mp <= MAX_CAP * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': True, 'lo': cc}
                    entries.append(e)
                    pyr_step = cd['cfg'].get('pyramid', {}).get('pyr_step', 7)
                    next_pyr_roi_map[label] += pyr_step
                    pyr_bar_map[label] = idx
                    last_ep_map[label] = cc
                    lei_map[label] = idx

        # ── Unrealized PnL ──
        ureal = 0
        for label, entries in entries_map.items():
            lev_coin = coin_data[label]['cfg'].get('entry', {}).get('lev', 1.5)
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
    print("POOLED BACKTEST — Shared $10k, FCFS signals (fully synced)")
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
