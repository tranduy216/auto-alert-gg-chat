"""
Simple Rule Strategy
1. BTC Bull: Close > MA200 AND Vol20 > VolMA50
2. Coin: Close > MA200
3. Entry: MA20 crosses above MA50 (golden cross)
4. Exit: BTC < MA200 OR Trailing 20%
5. Re-entry: Only after new MA20 cross up
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000; LEV = 2.0; ENTRY_SIZE = 0.10
TRAIL_PCT = 0.80  # 20% retracement
MAX_ENTRIES = 8; MAX_DEPLOYED = 0.80

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


def backtest_coin(coin, da, btc_da, selected_years):
    if not da or not btc_da or len(da) < 220: return coin, None
    closes = [c['close'] for c in da]; n = len(closes)
    ma20 = sma(closes, 20); ma50 = sma(closes, 50); ma200 = sma(closes, 200)

    btc_closes = [c['close'] for c in btc_da]
    btc_vols = [c['volume'] for c in btc_da]
    btc_ma200 = sma(btc_closes, 200)
    btc_vol_ma50 = sma(btc_vols, 50)

    entries = []; eq = 1.0; curve = []; yearly_eq = {}
    in_trade = False  # only enter on cross, not every bar
    last_cross = -999  # track last golden cross index

    import datetime

    for idx in range(200, n):
        cc = closes[idx]; hi = da[idx]['high']; bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000); yr = dt.year

        # Year filter
        if selected_years and yr not in selected_years:
            if entries:
                for e in entries:
                    raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                entries = []
            curve.append(eq)
            if dt.month == 12: yearly_eq[yr] = eq
            continue

        m20 = ma20[idx]; m50 = ma50[idx]; m200 = ma200[idx]
        if None in (m20, m50, m200): continue

        # BTC Bull check
        btc_idx = min(idx, len(btc_closes) - 1)
        btc_vol20 = sum(btc_vols[btc_idx-19:btc_idx+1]) / 20 if btc_idx >= 19 else 0
        btc_bull = (btc_idx >= 200 and btc_ma200[btc_idx] and btc_vol_ma50[btc_idx] and
                    btc_closes[btc_idx] > btc_ma200[btc_idx] and
                    btc_vol20 > btc_vol_ma50[btc_idx])

        # Golden cross detection
        golden_cross = False
        if idx > 0 and ma20[idx-1] and ma50[idx-1]:
            golden_cross = ma20[idx-1] <= ma50[idx-1] and m20 > m50
        if golden_cross: last_cross = idx

        # ── Exit logic ──
        force_exit = not btc_bull

        for e in entries[:]:
            trail_trigger = cc <= e['hi'] * TRAIL_PCT
            if force_exit or trail_trigger:
                raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                eq += raw / 100 * (1 - 2 * 0.0005 * LEV)
                entries.remove(e)
            else:
                e['hi'] = max(e.get('hi', cc), hi)

        if force_exit:
            in_trade = False

        # ── Entry logic (on every golden cross when conditions met) ──
        dep = sum(e.get('mp', ENTRY_SIZE) for e in entries)
        if golden_cross and btc_bull and cc > m200 and dep < MAX_DEPLOYED and len(entries) < MAX_ENTRIES:
            entries.append({'ep': cc, 'hi': cc, 'mp': ENTRY_SIZE})

        # ── Track equity ──
        ureal = 0
        for e in entries:
            raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
            ureal += raw / 100 * (1 - 2 * 0.0005 * LEV)
        total_eq = eq + ureal; curve.append(total_eq)
        if dt.month == 12: yearly_eq[yr] = total_eq

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

    print(f"{coin}: CAGR {cagr:+.2f}%  DD {md:.1f}%  Final ${teq*BASE:,.0f}")
    for y in sorted(yearly_cagr): print(f"  {y}: {yearly_cagr[y]:+.2f}%")
    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--years', type=str)
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()
    selected_years = None
    if args.years: selected_years = set(int(y.strip()) for y in args.years.split(','))
    data = load_data()
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    coins = ['BTC', 'ETH', 'BNB', 'TRX']
    results = []
    for coin in coins:
        da = data.get(f'{coin}USDT_4000_1609434000000', [])
        res = backtest_coin(coin, da, btc_da, selected_years)
        if res[1]: results.append(res)
    if results:
        cagrs = [r[1]['cagr'] for r in results]
        print(f"\nAvg CAGR: {sum(cagrs)/len(cagrs):+.2f}%")

if __name__ == '__main__': main()
