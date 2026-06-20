#!/usr/bin/env python3
"""Calculate consistency (std dev) from previous backtest results."""

from statistics import mean, stdev

# Data từ các lần backtest trước
results = {
    "BASELINE": {
        "ETH": {"yearly": [86.5, 24.6, 5.5, -3.1, 33.5], "cagr": 22.7, "dd": 37.2, "slr": 16.2},
        "BNB": {"yearly": [316.0, 0.0, 8.4, 11.1, 14.1], "cagr": 37.5, "dd": 20.6, "slr": 15.3},
        "TRX": {"yearly": [173.6, -19.5, 17.1, 57.6, 7.0], "cagr": 33.6, "dd": 34.1, "slr": 13.0},
    },
    "DYN-A": {  # Dynamic sizing với 4 tiers (80/75/70/65)
        "ETH": {"yearly": [95.9, 14.6, -18.4, -10.9, 9.1], "cagr": 23.3, "dd": 40.9, "slr": 15.0},
        "BNB": {"yearly": [355.4, 0.0, 10.2, 11.3, 11.5], "cagr": 38.0, "dd": 26.7, "slr": 9.0},
        "TRX": {"yearly": [168.0, -10.0, 18.1, 50.5, 6.7], "cagr": 33.9, "dd": 24.8, "slr": 7.0},
    },
}

print("=" * 95)
print("  CONSISTENCY ANALYSIS — Standard Deviation of Yearly Returns")
print("=" * 95)

for variant_name, coins in results.items():
    print(f"\n{variant_name}:")
    
    all_stds = []
    for coin in ["ETH", "BNB", "TRX"]:
        yearly = coins[coin]["yearly"]
        coin_std = stdev(yearly)
        all_stds.append(coin_std)
        
        yr_str = ", ".join([f"{y}:{r:+.1f}%" for y, r in zip([2021, 2022, 2023, 2024, 2025], yearly)])
        print(f"  {coin}: {yr_str}")
        print(f"        std={coin_std:.1f}%, CAGR={coins[coin]['cagr']:+.1f}%, DD={coins[coin]['dd']:.1f}%, SLr={coins[coin]['slr']:.0f}%")
    
    avg_std = mean(all_stds)
    avg_cagr = mean([coins[c]["cagr"] for c in ["ETH", "BNB", "TRX"]])
    avg_dd = mean([coins[c]["dd"] for c in ["ETH", "BNB", "TRX"]])
    avg_slr = mean([coins[c]["slr"] for c in ["ETH", "BNB", "TRX"]])
    
    print(f"\n  SUMMARY: Avg StdDev={avg_std:.1f}%, CAGR={avg_cagr:+.1f}%, DD={avg_dd:.1f}%, SLr={avg_slr:.0f}%")

print("\n" + "=" * 95)
print("  COMPARISON")
print("=" * 95)

baseline_std = mean([stdev(results["BASELINE"][c]["yearly"]) for c in ["ETH", "BNB", "TRX"]])
dyna_std = mean([stdev(results["DYN-A"][c]["yearly"]) for c in ["ETH", "BNB", "TRX"]])

print(f"BASELINE: StdDev={baseline_std:.1f}%, CAGR={mean([results['BASELINE'][c]['cagr'] for c in ['ETH','BNB','TRX']]):+.1f}%, SLr={mean([results['BASELINE'][c]['slr'] for c in ['ETH','BNB','TRX']]):.0f}%")
print(f"DYN-A:    StdDev={dyna_std:.1f}%, CAGR={mean([results['DYN-A'][c]['cagr'] for c in ['ETH','BNB','TRX']]):+.1f}%, SLr={mean([results['DYN-A'][c]['slr'] for c in ['ETH','BNB','TRX']]):.0f}%")
print(f"\nΔStdDev: {dyna_std - baseline_std:+.1f}%")
print(f"ΔSLr:    {mean([results['DYN-A'][c]['slr'] for c in ['ETH','BNB','TRX']]) - mean([results['BASELINE'][c]['slr'] for c in ['ETH','BNB','TRX']]):.0f}%")

if baseline_std < dyna_std:
    print(f"\n✓ BASELINE has better consistency (lower StdDev by {baseline_std - dyna_std:.1f}%)")
    print("  Recommendation: Keep BASELINE, don't apply dynamic sizing")
else:
    print(f"\n✓ DYN-A has better consistency (lower StdDev by {dyna_std - baseline_std:.1f}%)")
    print("  Recommendation: Apply dynamic sizing")
