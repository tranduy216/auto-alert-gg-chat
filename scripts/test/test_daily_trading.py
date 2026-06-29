"""
Unit tests for daily_trading.py and backtest_daily_trading.py.
Tests: pyramiding allowed, avg EP calc, TP/SL on ROI, signal detection.
"""
import sys, json, os, datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_shared import sma
from daily_trading import check_signal, avg_ep, avg_roi, TP_PCT, SL_PCT

failures = 0

def check(name, ok):
    global failures
    if ok: print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}")
        failures += 1


def make_candle(close, high=None, low=None, vol=1000, t=None):
    if high is None: high = close * 1.01
    if low is None: low = close * 0.99
    if t is None: t = 1700000000000
    return {'open': close, 'close': close, 'high': high, 'low': low, 'volume': vol, 'time': t}


# ── check_signal ──
print("\n=== check_signal ===")

# Uptrend
d_up = [make_candle(100+i*5) for i in range(12)]
h12_up = [make_candle(140) for _ in range(10)] + [make_candle(141), make_candle(141.5)]
dir, price = check_signal(h12_up, d_up)
check("uptrend returns LONG", dir == 'LONG')
check("uptrend returns price", price is not None and price > 0)

# Downtrend
d_down = [make_candle(150-i*5) for i in range(12)]
h12_down = [make_candle(100) for _ in range(12)]
dir, price = check_signal(h12_down, d_down)
check("downtrend returns SHORT", dir == 'SHORT')

# No trend
d_flat = [make_candle(100) for _ in range(12)]
h12_flat = [make_candle(100) for _ in range(12)]
dir, price = check_signal(h12_flat, d_flat)
check("flat trend returns None", dir is None)

# Insufficient data
check("no data => None", check_signal([], []) == (None, None))
check("short data => None", check_signal([make_candle(100)], [make_candle(100)]) == (None, None))


# ── avg_ep ──
print("\n=== avg_ep ===")
check("empty => None", avg_ep([]) is None)
check("single entry", abs(avg_ep([{'ep': 100, 'mp': 0.02}]) - 100) < 0.01)
check("two entries", abs(avg_ep([{'ep': 100, 'mp': 0.02}, {'ep': 110, 'mp': 0.02}]) - 105) < 0.01)
check("weighted", abs(avg_ep([{'ep': 100, 'mp': 0.03}, {'ep': 110, 'mp': 0.01}]) - 102.5) < 0.01)
check("three entries", abs(avg_ep([{'ep': 90, 'mp': 0.02}, {'ep': 100, 'mp': 0.02}, {'ep': 110, 'mp': 0.02}]) - 100) < 0.01)


# ── avg_roi ──
print("\n=== avg_roi ===")
entries_long = [{'ep': 100, 'mp': 0.02, 'short': False}]
check("long profit", abs(avg_roi(entries_long, 106, 2.0) - 12.0) < 0.01)  # (106-100)/100*200 = 12%
check("long loss", abs(avg_roi(entries_long, 97, 2.0) - (-6.0)) < 0.01)  # (97-100)/100*200 = -6%

entries_short = [{'ep': 100, 'mp': 0.02, 'short': True}]
check("short profit", abs(avg_roi(entries_short, 94, 2.0) - 12.0) < 0.01)  # (100-94)/100*200 = 12%
check("short loss", abs(avg_roi(entries_short, 103, 2.0) - (-6.0)) < 0.01)  # (100-103)/100*200 = -6%

# Multiple entries
multi = [{'ep': 90, 'mp': 0.02, 'short': True}, {'ep': 95, 'mp': 0.02, 'short': True}]
check("multi short profit", abs(avg_roi(multi, 88, 2.0) - 9.73) < 0.1)  # avg EP=92.5, ROI=(92.5-88)/92.5*200=9.73%
check("empty entries", avg_roi([], 100, 2.0) == 0)


# ── Entry sizing ──
print("\n=== Entry sizing ===")
from daily_trading import CAPITAL_BASE, ENTRY_MARGIN_PCT, LEV, NOTIONAL
check("CAPITAL_BASE = 10000", CAPITAL_BASE == 10000)
check("ENTRY_MARGIN_PCT = 0.02", abs(ENTRY_MARGIN_PCT - 0.02) < 0.001)
check("LEV = 2.0", abs(LEV - 2.0) < 0.01)
check("NOTIONAL = 400", abs(NOTIONAL - 400) < 0.01)


# ── TP/SL trigger levels ──
print("\n=== TP/SL triggers ===")
ep = 100.0
check("short SL at ROI -6%", abs(avg_roi([{'ep': ep, 'short': True}], ep*1.03, 2.0) - (-6.0)) < 0.01)
check("short TP at ROI +12%", abs(avg_roi([{'ep': ep, 'short': True}], ep*0.94, 2.0) - 12.0) < 0.01)
check("long SL at ROI -6%", abs(avg_roi([{'ep': ep, 'short': False}], ep*0.97, 2.0) - (-6.0)) < 0.01)
check("long TP at ROI +12%", abs(avg_roi([{'ep': ep, 'short': False}], ep*1.06, 2.0) - 12.0) < 0.01)

# SL = -3% * 2x = -6% ROI, TP = 6% * 2x = 12% ROI
check("SL threshold ROI", SL_PCT * 100 * LEV == 6.0)
check("TP threshold ROI", TP_PCT * 100 * LEV == 12.0)


# ── Full backtest with real data ──
print("\n=== Full backtest (pyramiding) ===")
raw_cache_path = Path(__file__).parent.parent / "_klines_12h_5y.json"
if raw_cache_path.exists():
    from backtest_daily_trading import backtest, avg_ep as bt_avg_ep
    raw_all = json.loads(raw_cache_path.read_text())

    for coin, key_name in [('BNB', 'BNBUSDT_4000_')]:
        key = next((k for k in raw_all if k.startswith(key_name)), None)
        if not key: continue
        r, wins, losses, tentries = backtest(coin, raw_all[key])
        check(f"{coin} returns result", r is not None)
        if r:
            check(f"{coin} CAGR computed", abs(r['cagr']) < 200)
            check(f"{coin} final > 0", r['final'] > 0)
            check(f"{coin} entries >= batches", tentries >= wins + losses)
            check(f"{coin} max DD realistic", r['dd'] < 50)

else:
    print("  SKIP: cache file not found")


# ── Summary ──
print(f"\n{'='*40}")
print(f"Results: {failures} failures")
print(f"{'='*40}")
