"""
Pooled Backtest — shared $10k equity pool, first-come-first-served signals.
All coins share one capital pool. Signals compete for the 75% cap.
"""
import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from crypto_trading import sma
from backtest_shared import (
    BASE, ENTRY_PCT, TRAIL_PCT, TP_SCHEDULE, MAX_CAP, FEE_RATE,
    EXT_BLOCK_PCT, fee_factor,
    load_data, fetch_paxg, winner_mult, compute_results,
)

# Multi-coin total_asset_value (different signature from single-coin version)
def total_asset_value_multi(all_entries, closes_map, eq, lev_map):
    val = eq
    for coin, entries in all_entries.items():
        if not entries:
            continue
        cc = closes_map.get(coin)
        if cc is None:
            continue
        lev = lev_map.get(coin, 1.5)
        for e in entries:
            if e.get('is_short'):
                val += (e['ep'] - cc) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
            else:
                val += (cc - e['ep']) / e['ep'] * e['mp'] * lev * e.get('rem', 1.0)
    return val


def run_pooled(data, strategies):
    """
    strategies: list of (label, coin_key, is_short, cfg)
    Returns: {cagr, dd, final, yearly}
    """
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

    # BTC regime
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    btc_closes = [c['close'] for c in btc_da]
    btc_times = [c['time'] for c in btc_da]
    btc_ma200 = sma(btc_closes, 200)
    btc_time_to_idx = {t: i for i, t in enumerate(btc_times)}

    entries_map = {label: [] for label, _, _, _ in strategies}
    lei_map = {label: -999 for label, _, _, _ in strategies}
    last_ep_map = {label: 0 for label, _, _, _ in strategies}
    time_to_idx = {l: {t: i for i, t in enumerate(cd['times'])} for l, cd in coin_data.items()}

    eq = 1.0; curve = []; yearly_eq = {}; ts_curve = []

    for ts in tss:
        btc_bull = False
        if btc_ma200:
            btc_idx = btc_time_to_idx.get(ts)
            if btc_idx is not None and btc_idx >= 200 and btc_ma200[btc_idx]:
                btc_bull = btc_closes[btc_idx] > btc_ma200[btc_idx]

        dt = datetime.datetime.fromtimestamp(ts / 1000); yr = dt.year

        # ── Exits (all coins) ──
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            cc = cd['closes'][idx]; hi = cd['highs'][idx]; bl = cd['lows'][idx]
            lev_coin = cd['cfg'].get('lev', 1.5)
            tp_sched = cd['cfg'].get('tp', TP_SCHEDULE)
            trail_pct = cd['cfg'].get('trail', TRAIL_PCT)
            ff = fee_factor(lev_coin)
            entries = entries_map[label]

            for e in entries[:]:
                if e.get('is_short') and btc_bull:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                    eq += raw * e.get('rem', 1.0) / 100 * ff
                    entries.remove(e)
                    continue

                if e.get('is_short'):
                    e['lo'] = min(e.get('lo', bl), bl)
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
                    elif cc >= e['lo'] / trail_pct:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)
                else:
                    e['hi'] = max(e.get('hi', cc), hi)
                    if cc <= e['hi'] * trail_pct:
                        raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                        eq += raw / 100 * ff
                        entries.remove(e)

        # ── Entries (FCFS by strategy order) ──
        for label, cd in coin_data.items():
            idx = time_to_idx[label].get(ts)
            if idx is None or idx < 200: continue
            cc = cd['closes'][idx]; hi = cd['highs'][idx]; bl = cd['lows'][idx]
            is_short = cd['is_short']; cfg = cd['cfg']
            lev_coin = cfg.get('lev', 1.5)
            ma_buf = cfg.get('buf', 0.03)
            pyr_roi = cfg.get('pyr', 5)
            ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
            entries = entries_map[label]

            m_ma = cd['ma_short'][idx]; vavg = cd['vol_ma20'][idx]
            if m_ma is None or vavg is None or vavg == 0: continue
            vol_cond = idx >= 2 and (cd['vols'][idx] + cd['vols'][idx-1]) / 2 > vavg
            near_ma = abs(cc - m_ma) / m_ma <= ma_buf

            can_enter_long = not is_short
            can_enter_short = is_short and not btc_bull
            active = can_enter_long or can_enter_short

            mult = winner_mult(entries, cc, is_short, lev_coin)
            if entries:
                lowest_ep = min(e['ep'] for e in entries)
                if abs(cc - lowest_ep) / lowest_ep * 100 > ext_block:
                    mult = 0

            if active and near_ma and vol_cond and mult > 0 and idx - lei_map[label] >= 0:
                total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                lev_map = {l: coin_data[l]['cfg'].get('lev', 1.5) for l in coin_data}
                total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                mp = eq * ENTRY_PCT / lev_coin * mult
                if total_dep + mp <= MAX_CAP * total_val:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                    if is_short: e['lo'] = bl
                    else: e['hi'] = cc
                    entries.append(e)
                    last_ep_map[label] = cc; lei_map[label] = idx

            if active and last_ep_map[label] > 0 and idx - lei_map[label] >= 0 and mult > 0:
                last_ep = last_ep_map[label]
                if can_enter_long:
                    roi = (cc - last_ep) / last_ep * 100 * lev_coin
                else:
                    roi = (last_ep - cc) / last_ep * 100 * lev_coin
                if roi >= pyr_roi:
                    total_dep = sum(sum(e.get('mp', 0) for e in es) for es in entries_map.values())
                    closes_map = {l: coin_data[l]['closes'][time_to_idx[l].get(ts)] if time_to_idx[l].get(ts) is not None else None for l in coin_data}
                    total_val = total_asset_value_multi(entries_map, closes_map, eq, lev_map)
                    mp = eq * ENTRY_PCT / lev_coin * mult
                    if total_dep + mp <= MAX_CAP * total_val:
                        e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                        if is_short: e['lo'] = bl
                        else: e['hi'] = cc
                        entries.append(e)
                        last_ep_map[label] = cc; lei_map[label] = idx

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
    paxg_da = fetch_paxg()
    data['PAXGUSDT_POOL'] = paxg_da

    strategies = [
        ('TRX-L',  'TRXUSDT_4000_1609434000000', False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('PAXG-L', 'PAXGUSDT_POOL',              False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('BTC-S',  'BTCUSDT_4000_1609434000000',  True, {'ma': 5,  'buf': 0.05, 'pyr': 3, 'lev': 1.6}),
    ]

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
