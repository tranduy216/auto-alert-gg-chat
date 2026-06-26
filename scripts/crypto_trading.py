#!/usr/bin/env python3
"""
Crypto Trading System (v5) — Simple, shared logic with backtest.
Uses entry_conditions from backtest_shared → same signals as historical backtest.
"""
import json, os, sys, datetime, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
def sma(values, period):
    """Simple Moving Average."""
    period = int(period)
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1 : i + 1]) / period)
    return result

from backtest_shared import (
    MA_BUF, TP_SCHEDULE, BTC_SHORT_TP, MAX_CAP, EXT_BLOCK_PCT,
    fetch_paxg, entry_conditions,
)
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_set_leverage,
    okx_place_order, okx_close_position, okx_get_open_orders,
)
from utils.firebase_utils import is_firebase_enabled, get_db

DISCORD_WEBHOOK = os.environ.get("DISCORD_TRADING_WEBHOOK_URL", "")


def fetch_binance(symbol, days=600):
    import requests
    url = 'https://api.binance.com/api/v3/klines'
    start_ms = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp() * 1000)
    candles = []
    while True:
        params = {'symbol': symbol, 'interval': '12h', 'startTime': start_ms, 'limit': 1000}
        resp = requests.get(url, params=params, timeout=30)
        raw = resp.json()
        if not raw or isinstance(raw, dict): break
        candles.extend(raw); start_ms = raw[-1][6] + 1
        if len(raw) < 1000: break
        time.sleep(0.3)
    daily = []
    for i in range(1, len(candles), 2):
        b2 = candles[i-1:i+1]
        daily.append({
            'close': float(b2[-1][4]), 'high': max(float(x[2]) for x in b2),
            'low': min(float(x[3]) for x in b2), 'volume': sum(float(x[5]) for x in b2),
            'time': b2[0][0],
        })
    return daily


def check_signals(coin_da, btc_da, cfg, is_short):
    """Check entry signal at latest bar using shared entry_conditions."""
    if not coin_da or len(coin_da) < 200: return None
    lev_coin = cfg.get('lev', 1.8); ma_buf = cfg.get('buf', 0.03)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_period = cfg.get('ma', 20)
    closes = [c['close'] for c in coin_da]; vols = [c['volume'] for c in coin_da]
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
                                 btc_bull, ext_block, lev_coin, -999)
    return should, cc


def main():
    ts = datetime.datetime.now()
    def log(msg): print(f"[{ts:%H:%M}] {msg}")

    log("Fetching market data...")
    btc_da = fetch_binance('BTCUSDT', 600)
    trx_da = fetch_binance('TRXUSDT', 600)
    paxg_da = fetch_paxg()

    strategies = [
        ('TRX',  trx_da,  False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('PAXG', paxg_da, False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
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
