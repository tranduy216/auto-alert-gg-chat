#!/usr/bin/env python3
"""
Crypto Trading System (v6) — Shared logic with backtest.
Uses entry_conditions from backtest_shared → same signals as historical backtest.
Entries tracked via state_manager, synced with OKX positions each run.
"""
import os, sys, time, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backtest_shared import (
    sma, fetch_candles,
    BTC_SHORT_TP, EXT_BLOCK_PCT, SHORT_MARGIN_CAP, PYRAMID_STRATEGIES,
    entry_conditions,
)
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_place_order, okx_get_instruments,
    okx_set_leverage, okx_place_algo,
)
from utils.state_manager import has_entered_today, record_entry, get_entries, add_entry, clear_entries, get_state, set_state
from backtest_shared import ENTRY_PCT

DISCORD_WEBHOOK = os.environ.get("DISCORD_TRADING_WEBHOOK_URL", "")

SYMBOL_OKX = {'TRX': 'TRX-USDT-SWAP', 'XAU': 'XAU-USDT-SWAP', 'BTC': 'BTC-USDT-SWAP'}
COIN_FROM_INST = {v: k for k, v in SYMBOL_OKX.items()}


def check_signals(coin_da, btc_da, cfg, is_short, entries=None):
    """Check entry signal at latest bar using shared entry_conditions."""
    if not coin_da or len(coin_da) < 200: return None
    if entries is None: entries = []
    lev_coin = cfg.get('lev', 1.8); ma_buf = cfg.get('buf', 0.03)
    ext_block = cfg.get('ext_block', EXT_BLOCK_PCT)
    ma_period = cfg.get('ma', 20)
    ma_slope = cfg.get('ma_slope', False)
    lower_high = cfg.get('lower_high', False)
    asym_buffer = cfg.get('asym_buffer', False)
    pyr_roi = cfg.get('pyr', 5)
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
    should, mult = entry_conditions(entries, cc, idx, vols, vv, mm, ma_buf, is_short,
                                    btc_bull, ext_block, lev_coin, -999,
                                    ma=ma, highs=highs, lows=lows,
                                    ma_slope=ma_slope, lower_high=lower_high, asym_buffer=asym_buffer)
    if should and is_short:
        mult = 1.0
    if not should and entries and mult > 0 and not is_short:
        last_ep = entries[-1]['ep']
        roi = (cc - last_ep) / last_ep * 100 * lev_coin
        if roi >= pyr_roi:
            should = True
    return should, mult, cc


def sync_entries_with_positions(okx_positions, log):
    """Sync Firestore entries with actual OKX positions."""
    pos_map = {COIN_FROM_INST.get(p['instId']): p for p in okx_positions
               if COIN_FROM_INST.get(p['instId']) and float(p.get('pos', 0)) != 0}
    entries_map = {}
    for coin in SYMBOL_OKX:
        stored = get_entries(coin)
        has_position = coin in pos_map
        if not stored and not has_position:
            entries_map[coin] = []
            continue
        if has_position and not stored:
            p = pos_map[coin]
            avg_px = float(p.get('avgPx', 0))
            is_short = float(p.get('pos', 0)) < 0
            if avg_px > 0:
                entries = [{'ep': avg_px, 'is_short': is_short}]
                entries_map[coin] = entries
                for e in entries:
                    add_entry(coin, e['ep'], e['is_short'])
                log(f"  {coin}: reconstructed entry from OKX @ {avg_px}")
            else:
                entries_map[coin] = []
        elif stored and not has_position:
            clear_entries(coin)
            if coin == 'BTC':
                today = datetime.datetime.now().strftime('%Y-%m-%d')
                set_state(coin, {'last_sl_date': today})
            log(f"  {coin}: cleared stale entries (position closed)")
            entries_map[coin] = []
        else:
            entries_map[coin] = stored
    return entries_map, pos_map


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

    data_map = {'BTC': btc_da, 'TRX': trx_da, 'XAU': paxg_da}

    entries_map = {}
    pos_map = {}
    if os.environ.get("OKX_API_KEY"):
        try:
            okx_positions = okx_get_positions()
            entries_map, pos_map = sync_entries_with_positions(okx_positions, log)
        except Exception as e:
            log(f"  Entries sync skipped: {e}")

    signals = []
    traded_count = 0
    for name, is_short, cfg in PYRAMID_STRATEGIES:
        da = data_map.get(name, [])
        sig = check_signals(da, btc_da, cfg, is_short, entries_map.get(name, []))
        if sig:
            should, mult, price = sig
            dir = 'BUY' if not is_short else 'SELL'
            signals.append((name, dir, price, cfg.get('lev', 1.8), cfg.get('trail', 0.80), mult))
            log(f"  {name}: {dir} @ {price:.4f}  mult={mult:.1f}x")

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

            btc_bull = False
            if btc_da and len(btc_da) >= 200:
                btc_closes = [c['close'] for c in btc_da]
                btc_ma200 = sma(btc_closes, 200)
                if btc_ma200[-1]:
                    btc_bull = btc_closes[-1] >= btc_ma200[-1] * 1.005

            instruments = okx_get_instruments('SWAP')
            inst_map = {inst['instId']: inst for inst in instruments}

            for name, direction, price, lev, trail, mult in signals:
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

                if direction == 'SELL':
                    last_sl = get_state(name).get('last_sl_date', '')
                    if last_sl:
                        days = (datetime.datetime.now() - datetime.datetime.strptime(last_sl, '%Y-%m-%d')).days
                        if days < 1:
                            log(f"  {name}: SL cooldown {days}d/1d, skipped")
                            continue

                if direction == 'SELL':
                    btc_pos = pos_map.get(inst_id, {})
                    existing_margin = float(btc_pos.get('margin', 0))
                    new_margin = usd_val / lev
                    if existing_margin + new_margin > eq * 0.25:
                        log(f"  {name}: short cap 25% margin ({SHORT_MARGIN_CAP*400:.0f}% exp), skipped")
                        continue

                usd_val = eq * lev * ENTRY_PCT * mult
                inst_info = inst_map[inst_id]
                ct_val_str = inst_info.get('ctVal', '')
                ct_val = float(ct_val_str) if ct_val_str else 0.01
                sz = max(1, int(usd_val / (price * ct_val)))
                side = 'buy' if direction == 'BUY' else 'sell'
                td_mode = 'isolated' if direction == 'SELL' else 'cross'
                okx_lev = round(lev)

                log(f"  TRADE {name} {direction} {sz}ct @ ${price:,.4f} (${usd_val:,.0f}, mult={mult:.1f}x, ctVal={ct_val})")
                try:
                    result = okx_place_order(
                        inst_id=inst_id, td_mode=td_mode,
                        side=side, sz=str(sz),
                    )
                    log(f"  Order OK: {result.get('data', [{}])[0].get('ordId', '?')}")
                    traded_count += 1
                    time.sleep(1.5)
                    okx_set_leverage(inst_id, okx_lev)
                    log(f"  Leverage set {okx_lev}x")
                    if direction == 'BUY':
                        try:
                            trail_pct = str(round(1 - trail, 2))
                            okx_place_algo(
                                inst_id=inst_id, td_mode=td_mode,
                                side='sell', sz=str(sz),
                                ord_type='move_order_stop',
                                callback_ratio=trail_pct,
                            )
                            log(f"  Trailing stop set ({round((1-trail)*100)}%)")
                        except Exception as trail_err:
                            log(f"  Trailing stop FAILED (non-critical): {trail_err}")
                    if direction == 'SELL':
                        tp_sz_sum = 0
                        for trg, frac in BTC_SHORT_TP:
                            tp_price = round(price * (1 - trg / (100 * lev)), 1)
                            tp_sz = max(1, int(sz * frac + 0.5))
                            tp_sz_sum += tp_sz
                            try:
                                okx_place_algo(
                                    inst_id=inst_id, td_mode=td_mode,
                                    side='buy', sz=str(tp_sz),
                                    ord_type='conditional', pos_side='short',
                                    tp_trigger_px=str(tp_price),
                                )
                            except Exception as tp_err:
                                log(f"  TP {trg}% failed: {tp_err}")
                        log(f"  TP ladder set ({tp_sz_sum}/{sz}ct)")
                        sl_price = round(price * (1 + SHORT_SL_ROI / (100 * lev)), 1)
                        try:
                            okx_place_algo(
                                inst_id=inst_id, td_mode=td_mode,
                                side='buy', sz=str(sz),
                                ord_type='conditional', pos_side='short',
                                sl_trigger_px=str(sl_price),
                            )
                            log(f"  Stop loss set @ ${sl_price:,.1f} ({SHORT_SL_ROI}% ROI)")
                        except Exception as sl_err:
                            log(f"  SL failed: {sl_err}")
                    record_entry(name, price)
                    add_entry(name, price, direction == 'SELL')
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                            f"TRADE: {name} {direction} {sz}ct @ ${price:,.4f}")
                except Exception as trade_err:
                    log(f"  Order FAILED: {trade_err}")
                    if DISCORD_WEBHOOK:
                        send_message(DISCORD_WEBHOOK,
                            f"FAILED: {name} {direction} — {trade_err}")

            log("Done trading.")

        except Exception as e:
            log(f"OKX setup error: {e}")
            import traceback; traceback.print_exc(file=sys.stderr)
            if DISCORD_WEBHOOK:
                send_message(DISCORD_WEBHOOK, f"OKX setup ERROR: {e}")
    else:
        log("OKX not configured — signal only")

    if DISCORD_WEBHOOK and traded_count > 0:
        summary = "\n".join(f"  {n} {d} @ ${p:,.4f}" for n, d, p, *_ in signals)
        send_message(DISCORD_WEBHOOK,
            f"*Pyramid Trading — {ts:%Y-%m-%d}*\n{summary}")

    log(f"Done. {len(signals)} signal(s){'' if traded_count == len(signals) else f' ({traded_count} placed, {len(signals)-traded_count} skipped)'}.")


if __name__ == '__main__':
    main()
