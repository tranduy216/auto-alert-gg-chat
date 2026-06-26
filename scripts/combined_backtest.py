"""
Combined Long + Short — MA5 pullback, red bar, BTC gate
- Long: buy red bars near MA5 (2% buffer) when BTC > MA200
- Short: BTC only, when BTC < MA200 with 30% cap
- 1.5x lev, 1.5% entry incl leverage
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 1.5
ENTRY_PCT = 0.015
TRAIL_PCT = 0.80      # 20% trail
MA_BUF = 0.03          # 3% buffer
MA_PERIOD = 20         # MA20 pullback entry
PYRAMID_ROI_DEFAULT = 5
BTC_MA_BULL = 120   # strong bull: BTC > MA120
BTC_MA_WEAK = 200   # weak bull: BTC > MA200
PYR_STRONG = 8      # pyramid ROI threshold in strong bull
PYR_WEAK = 5        # pyramid ROI threshold in weak bull
TP_SCHEDULE = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
# 4 TP levels, 25% each

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

def winner_mult(entries, cc, is_short, lev):
    if not entries: return 1.0
    rois = []
    for e in entries:
        if is_short:
            roi = (e['ep'] - cc) / e['ep'] * 100 * lev
        else:
            roi = (cc - e['ep']) / e['ep'] * 100 * lev
        rois.append(roi)
    avg = sum(rois) / len(rois)
    if avg > 15:    return 2.5
    elif avg > 10:  return 2.0
    elif avg > 5:   return 1.5
    elif avg > 0:   return 1.2
    elif avg > -5:  return 0.75
    else:           return 0.5

def backtest_coin(coin, da, btc_da, is_short, max_cap, selected_years, cfg=None):
    if not da or len(da) < 60: return coin, None
    if cfg is None: cfg = {}
    lev_coin = cfg.get('lev', LEV)
    ma_period = cfg.get('ma', MA_PERIOD)
    ma_buf = cfg.get('buf', MA_BUF)
    pyr_roi = cfg.get('pyr', PYRAMID_ROI_DEFAULT)
    tp_sched = cfg.get('tp', TP_SCHEDULE)
    trail_pct = cfg.get('trail', TRAIL_PCT)
    closes = [c['close'] for c in da]; n = len(closes)
    vols = [c['volume'] for c in da]
    ma_short = sma(closes, ma_period); vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None
    btc_start = 200

    entries = []; eq = 1.0; lei = -999; last_ep = 0
    curve = []; yearly_eq = {}
    ts_curve = []  # (timestamp, equity) for portfolio merging
    import datetime

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        if selected_years and yr not in selected_years:
            for e in entries:
                if e.get('is_short'):
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                else:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
                eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * lev_coin)
            entries = []
            curve.append(eq)
            ts_curve.append((da[idx]['time'], eq))
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m_ma = ma_short[idx]; vavg = vol_ma20[idx]
        if m_ma is None or vavg is None or vavg == 0: continue

        # BTC regime: bull when BTC > MA200
        btc_bull = False
        if btc_ma200:
            btc_idx = min(idx, len(btc_closes) - 1)
            if btc_idx >= 200 and btc_ma200[btc_idx]:
                btc_bull = btc_closes[btc_idx] > btc_ma200[btc_idx]

        vol_cond = idx >= 2 and (vols[idx] + vols[idx-1]) / 2 > vavg
        near_ma = abs(cc - m_ma) / m_ma <= ma_buf
        red_bar = idx > 0 and cc < closes[idx-1]
        dep = sum(e.get('mp', 0) for e in entries)
        mult = winner_mult(entries, cc, is_short, lev_coin)

        # Block entry entirely when price extended >30% from lowest entry price
        if entries:
            lowest_ep = min(e['ep'] for e in entries)
            ext = (cc - lowest_ep) / lowest_ep * 100
            if ext > 30:
                mult = 0  # block adds

        # ── BTC regime exit (longs: no exit, shorts: exit on bull) ──
        for e in entries[:]:
            if e.get('is_short') and btc_bull:
                raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * lev_coin)
                entries.remove(e)
                continue

            # ── Per-position exit: TP + trail ──
            if e.get('is_short'):
                e['lo'] = min(e.get('lo', bl), bl)
                roi = (e['ep'] - cc) / e['ep'] * 100 * lev_coin
                tp_stage = e.get('tp', 0)
                if tp_stage < len(tp_sched):
                    trg, cf = tp_sched[tp_stage]
                    if roi >= trg:
                        raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
                        eq += raw * cf / 100 * (1 - 2 * 0.0005 * lev_coin)
                        e['rem'] = e.get('rem', 1.0) - cf
                        e['tp'] = tp_stage + 1
                        if e.get('rem', 1.0) <= 0.001: entries.remove(e) 
                elif cc >= e['lo'] / trail_pct:
                    raw = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                    eq += raw / 100 * (1 - 2 * 0.0005 * lev_coin)
                    entries.remove(e)
            else:
                e['hi'] = max(e.get('hi', cc), hi)
                if cc <= e['hi'] * trail_pct:
                    raw = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin * e.get('rem', 1.0)
                    eq += raw / 100 * (1 - 2 * 0.0005 * lev_coin)
                    entries.remove(e)

        # ── Entry: BTC two-regime gate, near MA ──
        can_enter_long = not is_short
        can_enter_short = is_short and not btc_bull
        active = can_enter_long or can_enter_short

        if active and near_ma and vol_cond and (idx - lei >= 0) and mult > 0:
            mp = eq * ENTRY_PCT / lev_coin * mult
            if (dep + mp) * lev_coin <= max_cap * eq:
                e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                if is_short: e['lo'] = bl
                else: e['hi'] = cc
                entries.append(e)
                last_ep = cc; lei = idx

        # Pyramid
        if active and last_ep > 0 and (idx - lei >= 0):
            if can_enter_long:
                roi = (cc - last_ep) / last_ep * 100 * lev_coin
            else:
                roi = (last_ep - cc) / last_ep * 100 * lev_coin
            if roi >= pyr_roi:
                dep = sum(e.get('mp', 0) for e in entries)
                mp = eq * ENTRY_PCT / lev_coin * mult
                if (dep + mp) * lev_coin <= max_cap * eq:
                    e = {'ep': cc, 'mp': mp, 'rem': 1.0, 'tp': 0, 'is_short': is_short}
                    if is_short: e['lo'] = bl
                    else: e['hi'] = cc
                    entries.append(e)
                    last_ep = cc; lei = idx

        ureal = 0
        for e in entries:
            if e.get('is_short'):
                roi = (e['ep'] - cc) / e['ep'] * 100 * e['mp'] * lev_coin
            else:
                roi = (cc - e['ep']) / e['ep'] * 100 * e['mp'] * lev_coin
            ureal += roi * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * lev_coin)
        total_eq = eq + ureal; curve.append(total_eq); ts_curve.append((da[idx]['time'], total_eq))
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
    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr, 'ts_curve': ts_curve}


def main():
    # Optimal leverage per coin
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])

    strategies = [
        ('TRX-L', 'TRX', False, 1.0,  {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('BNB-L', 'BNB', False, 1.0,  {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('BTC-S', 'BTC', True,  0.30, {'ma': 20, 'buf': 0.03, 'pyr': 5, 'lev': 1.6}),
    ]

    results = {}
    for label, coin, is_short, max_cap, cfg in strategies:
        sym = f'{coin}USDT_4000_1609434000000'
        da = data.get(sym, [])
        btc = btc_da
        res = backtest_coin(coin, da, btc, is_short, max_cap, None, cfg)
        if res[1]: results[label] = res[1]

    # Merge portfolio equity curves by timestamp
    curves = [results[s[0]]['ts_curve'] for s in strategies if s[0] in results]
    if curves:
        merged = {}
        for curve in curves:
            for ts, eq in curve:
                merged[ts] = merged.get(ts, []) + [eq]
        tss = sorted(merged.keys())
        portfolio_eq = []
        yearly = {}
        peak = 1.0; md = 0
        import datetime
        for ts in tss:
            vals = merged[ts]
            if len(vals) != len(curves): continue
            avg_eq = sum(vals) / len(vals)
            portfolio_eq.append(avg_eq)
            if avg_eq > peak: peak = avg_eq
            dd = (peak - avg_eq) / peak * 100
            if dd > md: md = dd
            yr = datetime.datetime.fromtimestamp(ts / 1000).year
            yearly[yr] = avg_eq
        pf_yearly_cagr = {}
        for y in sorted(yearly.keys()):
            prev = yearly.get(y - 1, 1.0)
            pf_yearly_cagr[y] = (yearly[y] / prev - 1) * 100
        years_held = len(tss) / 365 if tss else 1
        pf_cagr = (portfolio_eq[-1] ** (1 / years_held) - 1) * 100 if portfolio_eq else 0

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
            cagr_yr = r.get('yearly', {})
            row = f"{label:<12}"
            for y in years:
                row += f"{cagr_yr.get(y, 0):>+7.1f}%"
            lev_used = cfg.get('lev', 1.5)
            row += f"{r['cagr']:>+7.1f}%  {r['dd']:>7.1f}%  {lev_used:>4.1f}x"
            print(row)
    print("-" * 70)
    row = f"{'Portfolio':<12}"
    for y in years:
        row += f"{pf_yearly_cagr.get(y, 0):>+7.1f}%"
    row += f"{pf_cagr:>+7.1f}%  {md:>7.1f}%"
    print(row)
    print("=" * 70)

if __name__ == '__main__': main()
