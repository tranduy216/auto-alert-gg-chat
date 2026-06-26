#!/usr/bin/env python3
"""
Crypto Trading System (v5) — Simple, shared logic with backtest.
Uses entry_conditions from backtest_shared → same signals as historical backtest.
"""
import os, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import (
    sma, fetch_candles,
    BTC_SHORT_TP, EXT_BLOCK_PCT,
    fetch_paxg, entry_conditions,
)
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions,
)

DISCORD_WEBHOOK = os.environ.get("DISCORD_TRADING_WEBHOOK_URL", "")


def check_signals(coin_da, btc_da, cfg, is_short):
    """Check entry signal at latest bar using shared entry_conditions."""
    if not coin_da or len(coin_da) < 200: return None
    lev_coin = cfg.get('lev', 1.8); ma_buf = cfg.get('buf', 0.03)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_period = cfg.get('ma', 20)
    ma_slope = cfg.get('ma_slope', False)
    lower_high = cfg.get('lower_high', False)
    asym_buffer = cfg.get('asym_buffer', False)
    closes = [c['close'] for c in coin_da]; vols = [c['volume'] for c in coin_da]
    highs = [c['high'] for c in coin_da]; lows = [c['low'] for c in coin_da]
    ma = sma(closes, ma_period); vma = sma(vols, 20)
    btc_closes = [c['close'] for c in btc_da] if btc_da else None
    btc_ma200 = sma(btc_closes, 200) if btc_closes else None
    idx = len(closes) - 1
    cc = closes[idx]; mm = ma[idx]; vv = vma[idx]
    if mm is None or vv is None or vv == 0: return None
    btc_bull = False
    if btc_ma200 and btc_closes:
        bi = min(idx, len(btc_closes) - 1)
        if bi >= 200 and btc_ma200[bi]:
            btc_bull = btc_closes[bi] > btc_ma200[bi]
    should, _ = entry_conditions([], cc, idx, vols, vv, mm, ma_buf, is_short,
                                 btc_bull, ext_block, lev_coin, -999,
                                 ma=ma, highs=highs, lows=lows,
                                 ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer)
    return should, cc


def main():
    ts = datetime.datetime.now()
    def log(msg): print(f"[{ts:%H:%M}] {msg}")

    log("Fetching market data...")
    btc_da = fetch_candles('BTCUSDT', 600)
    trx_da = fetch_candles('TRXUSDT', 600)
    paxg_da = fetch_paxg()

    strategies = [
        ('TRX',  trx_da,  False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('PAXG', paxg_da, False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8, 'lower_high': True}),
        ('BTC',  btc_da,  True,  {'ma': 5,  'buf': 0.05, 'pyr': 3, 'lev': 1.6, 'tp': BTC_SHORT_TP}),
    ]

    signals = []
    for name, da, is_short, cfg in strategies:
        sig = check_signals(da, btc_da, cfg, is_short)
        if sig:
            dir = 'BUY' if not is_short else 'SELL'
            signals.append((name, dir, sig[1]))
            log(f"  {name}: {dir} @ {sig[1]:.4f}")

    if os.environ.get("OKX_API_KEY"):
        log("OKX checking positions...")
        try:
            acct = okx_get_account()
            pos = okx_get_positions()
            log(f"  Equity: {acct.get('eq', '?'):>10}")
            log(f"  Open positions: {len(pos)}")
            for name, direction, price in signals:
                log(f"  Signal: {name} {direction} @ {price:.4f}")
                if DISCORD_WEBHOOK:
                    send_message(DISCORD_WEBHOOK,
                        f"Pyramid Signal: {name} {direction} @ {price:.4f}")
        except Exception as e:
            log(f"  OKX error: {e}")
    else:
        log("OKX not configured — signal only")

    if DISCORD_WEBHOOK and signals:
        summary = "\n".join(f"• {n} {d} @ ${p:,.4f}" for n, d, p in signals)
        send_message(DISCORD_WEBHOOK,
            f"*Pyramid Trading — {ts:%Y-%m-%d}*\n{summary}")

    log(f"Done. {len(signals)} signal(s).")


if __name__ == '__main__':
    main()
