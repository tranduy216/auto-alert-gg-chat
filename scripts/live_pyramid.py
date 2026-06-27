"""
Live Pyramid Strategy — sử dụng CHUNG logic entry với backtest.
Import entry_conditions từ backtest_shared → behavior 100% giống backtest.
Entries loaded from state_manager for extension block consistency.
"""
import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import os

from backtest_shared import (
    sma, fetch_candles,
    MA_BUF, MA_PERIOD, EXT_BLOCK_PCT,
    PYRAMID_STRATEGIES,
    entry_conditions,
)

TRADING_COIN_LIST = [c.strip() for c in os.environ.get('TRADING_COIN_LIST', '').splitlines() if c.strip()]
from utils.state_manager import get_entries


def check_signal(coin_da, btc_da, is_short, cfg, coin_name):
    """
    Kiểm tra entry tại bar cuối cùng, dùng CHUNG entry_conditions với backtest.
    """
    if not coin_da or len(coin_da) < 60:
        return None

    lev_coin = cfg.get('lev', 1.8)
    ma_buf = cfg.get('buf', MA_BUF)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_period = cfg.get('ma', MA_PERIOD)
    ma_slope = cfg.get('ma_slope', False)
    lower_high = cfg.get('lower_high', False)
    asym_buffer = cfg.get('asym_buffer', False)
    vol_bars = cfg.get('vol_bars', 2)

    closes = [c['close'] for c in coin_da]
    vols = [c['volume'] for c in coin_da]
    highs = [c['high'] for c in coin_da]; lows = [c['low'] for c in coin_da]
    ma_short = sma(closes, ma_period)
    vol_ma20 = sma(vols, 20)

    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None

    idx = len(closes) - 1
    if idx < 200: return None

    cc = closes[idx]
    m_ma = ma_short[idx]; vavg = vol_ma20[idx]
    if m_ma is None or vavg is None or vavg == 0:
        return None

    btc_bull = False
    if btc_ma200 and btc_closes:
        btc_i = min(idx, len(btc_closes) - 1)
        if btc_i >= 200 and btc_ma200[btc_i]:
            btc_bull = btc_closes[btc_i] >= btc_ma200[btc_i] * 1.005

    entries = get_entries(coin_name)
    should_enter, mult = entry_conditions(
        entries, cc, idx, vols, vavg, m_ma, ma_buf, is_short,
        btc_bull, ext_block, lev_coin, -999,
        ma=ma_short, highs=highs, lows=lows,
        ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer,
        vol_bars=vol_bars,
    )

    if not should_enter:
        return None

    direction = 'BUY' if not is_short else 'SELL'
    return {
        'signal': direction,
        'price': cc,
        'ma': m_ma,
        'reason': f'near_ma ok, vol ok',
        'mult': mult,
    }


def main():
    print("Fetching market data...", file=sys.stderr)
    btc_da = fetch_candles('BTCUSDT', 600)
    trx_da = fetch_candles('TRXUSDT', 600)
    paxg_da = fetch_candles('XAUUSDT', 600)

    data_map = {'BTC': btc_da, 'TRX': trx_da, 'XAU': paxg_da}
    strategies = [(name, data_map.get(name, []), is_short, cfg)
                   for name, is_short, cfg in PYRAMID_STRATEGIES
                   if name in TRADING_COIN_LIST]

    now = datetime.datetime.now()
    print("=" * 60)
    print(f"LIVE PYRAMID SIGNALS — {now:%Y-%m-%d %H:%M}")
    print("=" * 60)

    signals = []
    for name, da, is_short, cfg in strategies:
        sig = check_signal(da, btc_da, is_short, cfg, name)
        if sig:
            print(f"  {name:<6} {sig['signal']:<5} @ ${sig['price']:<10,.4f}  ({sig['reason']})")
            signals.append(sig)
        else:
            if da and len(da) > 0:
                print(f"  {name:<6} HOLD   @ ${da[-1]['close']:<10,.4f}  (no entry condition met)")
            else:
                print(f"  {name:<6} HOLD   (no data)")

    print("=" * 60)
    print(f"Total signals: {len(signals)}")
    if len(signals) > 0:
        print(f"\n::notice::New signals detected: {' | '.join(s['signal'] for s in signals)}")


if __name__ == '__main__':
    main()
