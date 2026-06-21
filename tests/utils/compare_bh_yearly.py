#!/usr/bin/env python3
"""Compare Buy & Hold yearly returns vs Hybrid Backtest yearly CAGR for each coin."""
import json, sys
from pathlib import Path
from datetime import datetime as dt, timezone

SCRIPTS = Path(__file__).parent.parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))
data = json.load(open(SCRIPTS / "_klines_12h_5y.json"))

coins = {"ETH": "ETHUSDT", "BNB": "BNBUSDT", "TRX": "TRXUSDT"}

print(f"{'Year':<6} {'Coin':<5} {'Start $':>10} {'End $':>10} {'B&H CAGR':>10} {'Hybrid CAGR':>12} {'Diff':>8}")
print("-" * 70)

for coin, symbol in coins.items():
    key = f"{symbol}_4000_1609434000000"
    if key not in data:
        continue
    da = data[key]

    # Find first and last price of each year
    years = {}
    for c in da:
        d = dt.fromtimestamp(c['open_time'] / 1000, tz=timezone.utc)
        yr = d.year
        if yr not in years:
            years[yr] = {'first': c['open'], 'last': c['close']}
        years[yr]['last'] = c['close']

    for yr in sorted(years.keys()):
        start_p = years[yr]['first']
        end_p = years[yr]['last']
        bh_cagr = (end_p / start_p - 1) * 100 if start_p > 0 else 0
        print(f"  {yr:<4} {coin:<5} ${start_p:>8.2f} ${end_p:>8.2f} {bh_cagr:>+9.2f}%")

print()
print("--- Summary ---")
print(f"{'Year':<6} {'ETH B&H':>9} {'ETH Hyb':>9} {'BNB B&H':>9} {'BNB Hyb':>9} {'TRX B&H':>9} {'TRX Hyb':>9}")
print("-" * 70)

# Hardcode hybrid results from last run
hybrid = {
    "ETH": {2021: 83.42, 2022: 31.25, 2023: -2.01, 2024: -14.00, 2025: 23.95},
    "BNB": {2021: 295.74, 2022: 0.00, 2023: 6.24, 2024: 1.54, 2025: 6.56},
    "TRX": {2021: 149.78, 2022: -27.53, 2023: 2.95, 2024: 54.69, 2025: 6.49},
}

# Compute buy & hold
for yr in range(2021, 2026):
    row = f"  {yr:<4}"
    for coin, symbol in coins.items():
        key = f"{symbol}_4000_1609434000000"
        da = data[key]
        start_p = None; end_p = None
        for c in da:
            d = dt.fromtimestamp(c['open_time'] / 1000, tz=timezone.utc)
            if d.year == yr:
                if start_p is None:
                    start_p = c['open']
                end_p = c['close']
        bh = (end_p / start_p - 1) * 100 if start_p and start_p > 0 else 0
        hyb = hybrid.get(coin, {}).get(yr, 0)
        row += f" {bh:>+8.2f}% {hyb:>+8.2f}%"
    print(row)
