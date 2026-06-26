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
    okx_get_account, okx_get_positions, okx_place_order, okx_get_instruments,
    okx_set_leverage, okx_close_position,
)
from utils.state_manager import has_entered_today, record_entry, get_state, set_state
from backtest_shared import ENTRY_PCT, TRAIL_PCT

DISCORD_WEBHOOK = os.environ.get("DISCORD_TRADING_WEBHOOK_URL", "")

SYMBOL_OKX = {'TRX': 'TRX-USDT-SWAP', 'XAU': 'XAU-USDT-SWAP', 'BTC': 'BTC-USDT-SWAP'}
COIN_FROM_INST = {v: k for k, v in SYMBOL_OKX.items()}


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


def manage_positions(log, btc_bull=False):
    """Check open positions: trailing stop for longs, TP ladder + trend exit for short BTC."""
    try:
        pos = okx_get_positions()
    except Exception as e:
        log(f"  Position check failed: {e}")
        return
    for p in pos:
        inst_id = p.get('instId', '')
        pos_qty = abs(float(p.get('pos', 0)))
        if pos_qty == 0:
            continue
        coin = COIN_FROM_INST.get(inst_id, '')
        if not coin:
            continue

        avg_px = float(p.get('avgPx', 0))
        mark_px = float(p.get('markPx', 0))
        if not avg_px or not mark_px:
            continue

        is_long = float(p.get('pos', 0)) > 0
        state = get_state(coin)

        if is_long:
            trail_high = max(state.get('trail_high', 0), avg_px, mark_px)
            if mark_px > trail_high:
                trail_high = mark_px
            if mark_px <= trail_high * TRAIL_PCT:
                log(f"  CLOSE {coin}: trailing stop @ ${mark_px:,.2f} (hi=${trail_high:,.2f}, drop={(1-mark_px/trail_high)*100:.1f}%)")
                try:
                    okx_close_position(inst_id)
                    set_state(coin, {'trail_high': 0, 'tp_stage': 0})
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                            f"CLOSE {coin}: trailing stop @ ${mark_px:,.2f}")
                except Exception as e:
                    log(f"  CLOSE {coin} failed: {e}")
            else:
                set_state(coin, {'trail_high': trail_high})
        else:
            if btc_bull:
                log(f"  CLOSE {coin}: BTC bull regime (close all short)")
                try:
                    okx_close_position(inst_id)
                    set_state(coin, {'tp_stage': 0})
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK, f"CLOSE {coin}: BTC bull regime")
                except Exception as e:
                    log(f"  CLOSE {coin} failed: {e}")
                continue
            tp_stage = state.get('tp_stage', 0)
            if tp_stage < len(BTC_SHORT_TP):
                trg, frac = BTC_SHORT_TP[tp_stage]
                roi = (avg_px - mark_px) / avg_px * 100 * 1.6
                if roi >= trg:
                    close_sz = max(1, int(pos_qty * frac + 0.5))
                    log(f"  TP {coin} stage {tp_stage+1}: ROI={roi:.1f}% → close {close_sz}ct")
                    try:
                        okx_place_order(inst_id=inst_id, td_mode='cross',
                            side='buy', sz=str(close_sz), pos_side='short', reduce_only=True)
                        set_state(coin, {'tp_stage': tp_stage + 1})
                        if DISCORD_WEBHOOK:
                            send_message(DISCORD_WEBHOOK,
                                f"TP {coin} stage {tp_stage+1}: closed {frac*100:.0f}% @ ROI {roi:.1f}%")
                    except Exception as e:
                        log(f"  TP {coin} failed: {e}")


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

            # BTC regime: entry < MA200*1.005 (generous), exit > MA200*0.995 (tight)
            btc_bull = False
            btc_bull_exit = False
            if btc_da and len(btc_da) >= 200:
                btc_closes = [c['close'] for c in btc_da]
                btc_ma200 = sma(btc_closes, 200)
                if btc_ma200[-1]:
                    btc_bull = btc_closes[-1] >= btc_ma200[-1] * 1.005
                    btc_bull_exit = btc_closes[-1] > btc_ma200[-1] * 0.995

            log("Checking positions...")
            manage_positions(log, btc_bull_exit)

            pos = okx_get_positions()
            pos_map = {p['instId']: p for p in pos if float(p.get('pos', 0)) != 0}
            log(f"Open positions: {len(pos_map)}")

            instruments = okx_get_instruments('SWAP')
            inst_map = {inst['instId']: inst for inst in instruments}

            for name, direction, price, lev in signals:
                inst_id = SYMBOL_OKX.get(name)
                if not inst_id:
                    log(f"  {name}: no instrument mapping, skipped")
                    continue
                if inst_id not in inst_map:
                    log(f"  {name}: {inst_id} not available on OKX, skipped")
                    continue

                today = datetime.datetime.now().strftime('%Y-%m-%d')
                if has_entered_today(name):
                    log(f"  {name}: already entered today ({today}), skipped")
                    continue

                mult = 1.0
                if inst_id in pos_map:
                    avg_px = float(pos_map[inst_id].get('avgPx', 0))
                    if avg_px > 0:
                        if direction == 'SELL':
                            roi = (avg_px - price) / avg_px * 100 * lev
                        else:
                            roi = (price - avg_px) / avg_px * 100 * lev
                        if roi > 15:     mult = 2.5
                        elif roi > 10:   mult = 2.0
                        elif roi > 5:    mult = 1.5
                        elif roi > 0:    mult = 1.2
                        elif roi > -5:   mult = 0.75
                        else:            mult = 0.5

                usd_val = eq * ENTRY_PCT * mult
                inst_info = inst_map[inst_id]
                ct_val_str = inst_info.get('ctVal', '')
                ct_val = float(ct_val_str) if ct_val_str else 0.01
                sz = max(1, int(usd_val / (price * ct_val)))
                side = 'buy' if direction == 'BUY' else 'sell'

                log(f"  Set leverage {name} {lev}x")
                okx_set_leverage(inst_id, lev)
                log(f"  TRADE {name} {direction} {sz}ct @ ${price:,.4f} (${usd_val:,.0f}, mult={mult}x, ctVal={ct_val})")
                try:
                    result = okx_place_order(
                        inst_id=inst_id, td_mode='cross',
                        side=side, sz=str(sz),
                    )
                    log(f"  Order OK: {result.get('data', [{}])[0].get('ordId', '?')}")
                    record_entry(name, price)
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                            f"TRADE: {name} {direction} {sz}ct @ ${price:,.4f}")
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
