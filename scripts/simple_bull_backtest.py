"""
Simple Bull Market Long Engine
- BTC Bull: Close > MA200
- Entry: Coin Close > MA50 > MA100
- Exit: MA20 < MA50 cross, OR staged TP 40% (10/20/30%), OR trail 60% (20% retracement)
- Leverage 2x
"""

import json, argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from crypto_trading import sma

BASE = 10000
LEV = 1.5
ENTRY_SIZE = 0.10  # 10% of capital per entry (10 entries max at 1.5x = 150% position)

BTC_MA_PERIOD = 200
TRAIL_RETRACE = 0.80  # trail at 80% of highest (20% retracement)

# Staged TP for 30% of position: 10% each at 30/50/80% ROI
TP_SCHEDULE = [(30, 0.10), (50, 0.10), (80, 0.10)]

def load_data():
    p = Path(__file__).parent / "_klines_12h_5y.json"
    with open(p) as f:
        raw = json.load(f)
    # Aggregate 12h → 1d: take every 2nd bar
    data = {}
    for sym, candles in raw.items():
        daily = []
        for i in range(1, len(candles), 2):
            b2 = candles[i-1:i+1]
            daily.append({
                'close': b2[-1]['close'],
                'high': max(x['high'] for x in b2),
                'low': min(x['low'] for x in b2),
                'volume': sum(x['volume'] for x in b2),
                'time': b2[0]['open_time'],
            })
        data[sym] = daily
    return data


def backtest_coin(coin, da, btc_da, selected_years):
    if not da or not btc_da:
        return coin, None

    closes = [c['close'] for c in da]
    n = len(closes)
    if n < BTC_MA_PERIOD + 20:
        return coin, None

    # Indicators
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    ma100 = sma(closes, 100)

    # BTC indicators
    btc_closes = [c['close'] for c in btc_da]
    btc_ma = sma(btc_closes, BTC_MA_PERIOD)

    # State
    entries = []  # list of {ep, hi, bar_index}
    eq = 1.0
    curve = []
    yearly_eq = {}

    import datetime

    for idx in range(BTC_MA_PERIOD, n):
        cc = closes[idx]
        hi = da[idx]['high']
        bl = da[idx]['low']
        dt = datetime.datetime.fromtimestamp(da[idx]['time'] / 1000)
        yr = dt.year

        # Year filter
        if selected_years and yr not in selected_years:
            if entries:
                for e in entries:
                    raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw * LEV / 100 * (1 - 2 * 0.0005 * LEV)
                entries = []
            curve.append(eq)
            if dt.month == 12:
                yearly_eq[yr] = eq
            continue

        # BTC Bull check: Close > MA(BTC_MA_PERIOD)
        btc_idx = min(idx, len(btc_closes) - 1)
        btc_bull = False
        if btc_idx >= BTC_MA_PERIOD and btc_ma[btc_idx]:
            btc_bull = btc_closes[btc_idx] > btc_ma[btc_idx]

        # Update highest price for trailing
        for e in entries:
            e['hi'] = max(e.get('hi', cc), hi)

        # Exit: MA20 crosses below MA50 (closes ALL remaining)
        for e in entries[:]:
            if idx > 0 and ma20[idx] and ma50[idx] and ma20[idx-1] and ma50[idx-1]:
                if ma20[idx-1] >= ma50[idx-1] and ma20[idx] < ma50[idx]:
                    raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw * e.get('rem', 1.0) / 100 * (1 - 2 * 0.0005 * LEV)
                    entries.remove(e)

        # Staged TP: 40% of position at 10/20/30% ROI
        for e in entries[:]:
            roi = (cc - e['ep']) / e['ep'] * 100 * LEV
            tp_stage = e.get('tp_stage', 0)
            while tp_stage < len(TP_SCHEDULE):
                trg, cf = TP_SCHEDULE[tp_stage]
                if roi >= trg:
                    rem = e.get('rem', 1.0)
                    close_pct = cf / rem  # fraction of remaining position to close
                    close_pct = min(close_pct, rem)
                    raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                    eq += raw * close_pct / 100 * (1 - 2 * 0.0005 * LEV)
                    rem -= close_pct
                    e['rem'] = rem
                    e['tp_stage'] = tp_stage + 1
                    if rem <= 0.001:
                        entries.remove(e)
                        break
                tp_stage += 1

        # Trailing stop: 60% remaining, close if drop 20% from high
        for e in entries[:]:
            if e.get('rem', 1.0) > 0 and cc <= e['hi'] * TRAIL_RETRACE:
                raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
                eq += raw * e['rem'] / 100 * (1 - 2 * 0.0005 * LEV)
                entries.remove(e)

        # Entry: only when BTC Bull Strong
        if btc_bull:
            dep = sum(e.get('mp', ENTRY_SIZE) for e in entries)
            if (dep < 1.0 and len(entries) < 10 and
                ma50[idx] and ma100[idx] and
                cc > ma50[idx] and cc > ma100[idx]):
                entries.append({'ep': cc, 'hi': cc, 'mp': ENTRY_SIZE, 'rem': 1.0, 'tp_stage': 0})

        # Track equity
        ureal = 0
        for e in entries:
            raw = (cc - e['ep']) / e['ep'] * 100 * ENTRY_SIZE * LEV
            ureal += raw / 100 * (1 - 2 * 0.0005 * LEV)
        total_eq = eq + ureal
        curve.append(total_eq)
        if dt.month == 12:
            yearly_eq[yr] = total_eq

    # Results
    teq = curve[-1] if curve else eq
    years = len(curve) / 365 if curve else 1
    cagr = (teq ** (1 / years) - 1) * 100 if teq > 0 else 0
    peak = curve[0] if curve else eq
    md = 0
    for v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > md: md = dd

    yearly_cagr = {}
    for y in sorted(yearly_eq.keys()):
        prev = yearly_eq.get(y - 1, yearly_eq.get(min(yearly_eq.keys())) if y == min(yearly_eq.keys()) else 1.0)
        yearly_cagr[y] = (yearly_eq[y] / prev - 1) * 100

    print(f"{coin}: CAGR {cagr:+.2f}%  DD {md:.1f}%  Final ${teq*BASE:,.0f}")
    for y in sorted(yearly_cagr):
        print(f"  {y}: {yearly_cagr[y]:+.2f}%")

    return coin, {'cagr': cagr, 'dd': md, 'final': teq * BASE, 'yearly': yearly_cagr}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--years', type=str)
    parser.add_argument('--no-cache', action='store_true')
    args = parser.parse_args()

    selected_years = None
    if args.years:
        selected_years = set(int(y.strip()) for y in args.years.split(','))

    data = load_data()
    print(f"Loaded {len(data)} symbols")

    coins = ['BTC', 'BNB', 'TRX']
    btc_da = data.get('BTCUSDT_4000_1609434000000', [])
    results = []

    for coin in coins:
        sym = f"{coin}USDT_4000_1609434000000"
        da = data.get(sym, [])
        res = backtest_coin(coin, da, btc_da, selected_years)
        if res[1]:
            results.append(res)

    if len(results) > 1:
        cagrs = [r[1]['cagr'] for r in results]
        print(f"\nAvg CAGR: {sum(cagrs)/len(cagrs):+.2f}%")


if __name__ == '__main__':
    main()
