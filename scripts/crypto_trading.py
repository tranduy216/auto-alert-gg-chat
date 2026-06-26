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
    entry_conditions,
)
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_get_instruments,
    okx_set_leverage,
)
from utils.state_manager import has_entered_today
from backtest_shared import ENTRY_PCT

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
    errors = []

    btc_da = fetch_candles('BTCUSDT', 600)
    if not btc_da or len(btc_da) < 200:
        errors.append("BTC data fetch FAILED")
        btc_da = []

    trx_da = fetch_candles('TRXUSDT', 600)
    if not trx_da or len(trx_da) < 200:
        errors.append("TRX data fetch FAILED")
        trx_da = []

    paxg_da = fetch_candles('XAUUSDT', 600)
    if not paxg_da or len(paxg_da) < 200:
        errors.append("XAU data fetch FAILED")
        paxg_da = []

    if errors and DISCORD_WEBHOOK:
        send_message(DISCORD_WEBHOOK,
            f"*Fetch Errors — {ts:%Y-%m-%d %H:%M}*\n" + "\n".join(f"  {e}" for e in errors))

    strategies = [
        ('TRX',  trx_da,  False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8}),
        ('XAU', paxg_da, False, {'ma': 15, 'buf': 0.05, 'pyr': 3, 'lev': 1.8, 'lower_high': True}),
        ('BTC',  btc_da,  True,  {'ma': 5,  'buf': 0.05, 'pyr': 3, 'lev': 1.6, 'tp': BTC_SHORT_TP}),
    ]

    signals = []
    for name, da, is_short, cfg in strategies:
        sig = check_signals(da, btc_da, cfg, is_short)
        if sig:
            dir = 'BUY' if not is_short else 'SELL'
            signals.append((name, dir, sig[1], cfg.get('lev', 1.8)))
            log(f"  {name}: {dir} @ {sig[1]:.4f}")

    if os.environ.get("OKX_API_KEY"):
        try:
            acct = okx_get_account()
            eq = 0
            for d in acct.get('data', []):
                if isinstance(d, dict):
                    eq = float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
                    if eq > 0: break
            if eq <= 0:
                eq = float(acct.get('totalEq', 0))
            log(f"Equity: ${eq:,.0f}")

            pos = okx_get_positions()
            open_insts = {p['instId'] for p in pos if float(p.get('pos', 0)) != 0}
            log(f"Open positions: {len(open_insts)}")

            instruments = okx_get_instruments('SWAP')
            inst_map = {inst['instId']: inst for inst in instruments}

            SYMBOL_OKX = {'TRX': 'TRX-USDT-SWAP', 'XAU': 'XAU-USDT-SWAP', 'BTC': 'BTC-USDT-SWAP'}

            for name, direction, price, lev in signals:
                inst_id = SYMBOL_OKX.get(name)
                if not inst_id:
                    log(f"  {name}: no instrument mapping, skipped")
                    continue
                if inst_id in open_insts:
                    log(f"  {name}: already in position, skipped")
                    continue
                if inst_id not in inst_map:
                    log(f"  {name}: {inst_id} not available on OKX, skipped")
                    continue

                today = datetime.datetime.now().strftime('%Y-%m-%d')
                if has_entered_today(name):
                    log(f"  {name}: already entered today ({today}), skipped")
                    continue

                usd_val = eq * ENTRY_PCT
                inst_info = inst_map[inst_id]
                ct_val_str = inst_info.get('ctVal', '')
                ct_val = float(ct_val_str) if ct_val_str else 0.01
                sz = max(1, int(usd_val / (price * ct_val)))
                side = 'buy' if direction == 'BUY' else 'sell'

                log(f"  Set leverage {name} {lev}x (disabled)")
                # okx_set_leverage(inst_id, lev)
                log(f"  TRADE {name} {direction} {sz}ct @ ${price:,.4f} (${usd_val:,.0f}, ctVal={ct_val})")
                try:
                    # ORDER PLACEMENT DISABLED — signal-only mode
                    # result = okx_place_order(
                    #     inst_id=inst_id, td_mode='cross',
                    #     side=side, sz=str(sz),
                    # )
                    # log(f"  Order OK: {result.get('data', [{}])[0].get('ordId', '?')}")
                    # record_entry(name, price)
                    log(f"  SIGNAL: {name} {direction} {sz}ct @ ${price:,.4f} (order disabled)")
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                            f"Pyramid Signal: {name} {direction} @ ${price:,.4f}")
                except Exception as trade_err:
                    log(f"  Order FAILED: {trade_err}")
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                            f"FAILED: {name} {direction} — {trade_err}")

        except Exception as e:
            log(f"OKX setup error: {e}")
            import traceback; traceback.print_exc(file=sys.stderr)
            if DISCORD_WEBHOOK:
                send_message(DISCORD_WEBHOOK, f"OKX setup ERROR: {e}")
    else:
        log("OKX not configured — signal only")

    if DISCORD_WEBHOOK and signals:
        summary = "\n".join(f"• {n} {d} @ ${p:,.4f}" for n, d, p, _ in signals)
        send_message(DISCORD_WEBHOOK,
            f"*Pyramid Trading — {ts:%Y-%m-%d}*\n{summary}")

    log(f"Done. {len(signals)} signal(s).")


if __name__ == '__main__':
    main()
