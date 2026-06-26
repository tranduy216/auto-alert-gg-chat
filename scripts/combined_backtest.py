"""
Combined Long + Short Pyramid Strategy
- Long: TRX, SOL, AVAX (always on)
- Short: AVAX, BTC, ETH (only when BTC < MA200)
- 1.5x lev, 1.5% entry incl leverage, 100% cap per coin
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 1.5
ENTRY_PCT = 0.015
TRAIL_PCT = 0.80
MA_BUF = 0.03
PYRAMID_ROI = 5
TP_SCHEDULE = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]

def load_data():
    p = Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f: raw = json.load(f)
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({'close': b2[-1]['close'], 'high': max(x['high'] for x in b2),
                         'low': min(x['low'] for x in b2), 'volume': sum(x['volume'] for x in b2),
                         'time': b2[0]['open_time']})
        data[sym] = daily
    return data

def winner_mult(entries, cc, is_short):
    if not entries: return 1.0
    rois = []
    for e in entries:
        if is_short:
            roi = (e['ep'] - cc) / e['ep'] * 100 * LEV
        else:
            roi = (cc - e['ep']) / e['ep'] * 100 * LEV
        rois.append(roi)
    avg = sum(rois) / len(rois)
    if avg > 15:    return 2.5
    elif avg > 10:  return 2.0
    elif avg > 5:   return 1.5
    elif avg > 0:   return 1.2
    elif avg > -5:  return 0.75
    else:           return 0.5

def backtest_coin(coin, da, btc_da, is_short, max_cap, selected_years):
    if not da or len(da) < 60: return coin, None
    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    ma20 = sma(closes, 20); vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None
    btc_ma50 = sma(btc_closes, 50) if btc_closes else None
    btc_start = 200

    entries = []; eq = 1.0; lei = -999; last_ep = 0
    curve = []; yearly_eq = {}
    import datetime

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            for e in entries:
                if e.get('is_short'):
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                else:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
            entries = []
            curve.append(eq)
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m20 = ma20[idx]; vavg = vol_ma20[idx]
        if m20 is None or vavg is None or vavg == 0: continue

        # BTC dual MA regime
        btc_regime = 'bear'
        btc_size_mult = 1.0
        if btc_ma50 and btc_ma200:
            btc_idx = min(idx, len(btc_closes) - 1)
            if btc_idx >= 50 and btc_ma50[btc_idx]:
                btc_close = btc_closes[btc_idx]
                above_ma200 = btc_idx >= 200 and btc_ma200[btc_idx] and btc_close > btc_ma200[btc_idx]
                above_ma50 = btc_close > btc_ma50[btc_idx]
                if above_ma200:
                    btc_regime = 'strong_bull'
                elif above_ma50:
                    btc_regime = 'weak_bull'
                else:
                    btc_regime = 'bear'
                # For longs: full size in weak_bull (recovery), only block in true bear
                # For shorts: reduced in weak_bull, full in bear
                btc_size_mult = 0.7 if is_short and btc_regime == 'weak_bull' else 1.0

        vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg
        near_ma20 = abs(cc - m20) / m20 <= MA_BUF
        dep = sum(e.get('mp', 0) for e in entries)
        mult = winner_mult(entries, cc, is_short)

        # ── BTC regime exit ──
        for e in entries[:]:
            if not e.get('is_short') and btc_regime == 'bear':
                raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
                entries.remove(e)
                continue
            if e.get('is_short') and btc_regime == 'strong_bull':
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
                entries.remove(e)
                continue

            # ── Per-position exit: trail + TP ──
            if e.get('is_short'):
                e['lo'] = min(e.get('lo', bl), bl)
                roi = (e['ep'] - cc) / e['ep'] * 100 * LEV
                tp_stage = e.get('tp', 0)
                if tp_stage < len(TP_SCHEDULE):
                    trg, cf = TP_SCHEDULE[tp_stage]
                    if roi >= trg:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
                        eq += raw * cf / 100 * (1 - 2 * 0.0005 * LEV)
                        e['rem'] = e.get('rem', 1.0) - cf
                        e['tp'] = tp_stage + 1
                        if e.get('rem', 1.0) <= 0.001: entries.remove(e) 
                elif cc >= e['lo'] / TRAIL_PCT:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV * e.get('rem', 1.0)
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                    entries.remove(e)
            else:
                # Long trail
                e['hi'] = max(e.get('hi', cc), hi)
                if cc <= e['hi'] * TRAIL_PCT:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV * e.get('rem', 1.0)
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                    entries.remove(e)

        # ── Entry: BTC dual-MA gate ──
        can_enter_long = not is_short and btc_regime != 'bear'
        can_enter_short = is_short and btc_regime != 'strong_bull'
        active = can_enter_long or can_enter_short

        if active and near_ma20 and vol_cond and (idx - lei >= 0):
            mp = eq * ENTRY_PCT / LEV * mult * btc_size_mult
            if (dep + mp) * LEV <= max_cap * eq:
                e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                if is_short: e['lo'] = bl
                else: e['hi'] = cc
                entries.append(e)
                last_ep = cc; lei = idx

        # Pyramid
        if active and last_ep > 0 and (idx - lei >= 0):
            if can_enter_long:
                roi = (cc - last_ep) / last_ep * 100 * LEV
            else:
                roi = (last_ep - cc) / last_ep * 100 * LEV
            if roi >= PYRAMID_ROI:
                dep = sum(e.get('mp', 0) for e in entries)
                mp = eq * ENTRY_PCT / LEV * mult * btc_size_mult
                if (dep + mp) * LEV <= max_cap * eq:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                    if is_short: e['lo'] = bl
                    else: e['hi'] = cc
                    entries.append(e)
                    last_ep = cc; lei = idx

        ureal = 0
        for e in entries:
            if e.get('is_short'):
                roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * LEV
            else:
                roi = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * LEV
            ureal += roi * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
        total_eq = eq + ureal; curve.append(total_eq)
        if dt.month == 12: yearly_eq[yr] = total_eq

    # Capture final partial year
    if curve:
        last_yr = datetime.datetime.fromtimestamp(da[-1]['time'] / 1000).year
        if last_yr not in yearly_eq:
            yearly_eq[last_yr] = curve[-1]

    teq = curve[-1] if curve else eq
    years = len(curve) / 365 if curve else 1
    cagr = (teq ** (1 / years) - 1) * 100 if teq > 0 else 0
    peak = curve[0] if curve else eq; md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > md: md = dd
    yearly_cagr = {}
    for y in sorted(yearly_eq.keys()):
        prev = yearly_eq.get(y - 1, 1.0)
        yearly_cagr[y] = (yearly_eq[y] / prev - 1) * 100
    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr}


def main():
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])

    # Long: TRX, BNB, ADA (100% cap per coin)
    # Short: BTC only (30% cap)
    strategies = [
        ('TRX-L', 'TRX', False, 1.0),
        ('BNB-L', 'BNB', False, 1.0),
        ('ADA-L', 'ADA', False, 1.0),
        ('BTC-S', 'BTC', True, 0.30),
    ]

    results = {}
    for label, coin, is_short, max_cap in strategies:
        sym = f'{coin}USDT_4000_1609434000000'
        da = data.get(sym, [])
        btc = btc_da  # always pass BTC data for regime gate
        res = backtest_coin(coin, da, btc, is_short, max_cap, None)
        if res[1]: results[label] = res[1]

    print("=" * 70)
    print("COMBINED LONG + SHORT — YEARLY CAGR (standalone fresh $10k)")
    print("=" * 70)
    years = list(range(2021, 2027))
    header = f"{'Strategy':<12}" + "".join(f"{y:>8}" for y in years) + f"{'CAGR':>8}"
    print(header)
    print("-" * 70)
    for label in [s[0] for s in strategies]:
        if label in results:
            r = results[label]
            cagr_yr = r.get('yearly', {})
            row = f"{label:<12}"
            for y in years:
                row += f"{cagr_yr.get(y, 0):>+7.1f}%"
            row += f"{r['cagr']:>+7.1f}%"
            print(row)
    print("=" * 70)

if __name__ == '__main__': main()
