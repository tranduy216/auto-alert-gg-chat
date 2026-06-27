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
    EXT_BLOCK_PCT, SHORT_MAX_MARGIN, SHORT_CLOSE_PCT, PYRAMID_STRATEGIES,
    entry_conditions,
)

_raw = os.environ.get('TRADING_COIN_LIST', '')
TRADING_COIN_LIST = [c.strip() for c in _raw.splitlines() if c.strip()]
from utils.discord_webhook import send_message
from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_place_order, okx_get_instruments,
    okx_set_leverage, okx_close_position,
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
    closes = [c['close'] for c in coin_da]; vols = [c['volume'] for c in coin_da]
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
    mult *= cfg.get('_entry_mult', 1.0)
    return should, mult, cc
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
            avg_px = float(p.get('avgPx') or 0)
            is_short = float(p.get('pos', 0)) < 0
            if avg_px > 0:
                entries = [{'ep': avg_px, 'is_short': is_short, 'hi': avg_px, 'lo': avg_px}]
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

    if os.environ.get("OKX_API_KEY"):
        try:
            okx_positions = okx_get_positions()
            entries_map, pos_map = sync_entries_with_positions(okx_positions, log)
        except Exception as e:
            log(f"  Entries sync skipped: {e}")

    if os.environ.get("OKX_API_KEY"):
        try:
            instruments = okx_get_instruments('SWAP')
            inst_map = {inst['instId']: inst for inst in instruments}
        except Exception as e:
            log(f"  Instruments fetch failed: {e}")
            instruments = []; inst_map = {}

    # ── Exit check (trailing/TP/SL for existing positions) ──
    if os.environ.get("OKX_API_KEY"):
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        for name, is_short, cfg in PYRAMID_STRATEGIES:
            if TRADING_COIN_LIST and name not in TRADING_COIN_LIST: continue
            coin_entries = entries_map.get(name, [])
            da = data_map.get(name, [])
            if not da or not coin_entries: continue
            cc = da[-1]['close']; hi = da[-1]['high']; bl = da[-1]['low']
            lev = cfg.get('lev', 2); trail = cfg.get('trail', 0.80)
            tp = cfg.get('tp');             close_pct = cfg.get('close_pct', SHORT_CLOSE_PCT)
            inst_id = SYMBOL_OKX.get(name)
            pos = pos_map.get(inst_id, {})

            # Update peak/trough for each entry
            for e in coin_entries:
                if e.get('is_short'):
                    lo = e.get('lo', cc)
                    e['lo'] = min(lo, bl)
                else:
                    hi_prev = e.get('hi', cc)
                    e['hi'] = max(hi_prev, hi)

            # Compute avg weighted EP
            total_mp = sum(e['mp'] for e in coin_entries if 'mp' in e) or len(coin_entries)
            avg_ep = sum(e['ep'] * (e.get('mp', 1) if 'mp' in e else 1) for e in coin_entries) / total_mp

            roi = (cc - avg_ep) / avg_ep * 100 * lev if not is_short else (avg_ep - cc) / avg_ep * 100 * lev

            # Long: close check (trailing or MA crossover)
            if not is_short:
                exit_mode = cfg.get('exit_mode', 'trailing')
                if exit_mode == 'ma_cross':
                    cc_long = da[-1]['close']
                    ma_s = sma([c['close'] for c in da], cfg.get('ma_short', 40))
                    ma_l_vals = sma([c['close'] for c in da], cfg.get('ma_long', 90))
                    mbuf = cfg.get('ma_buf', 0.03)
                    idx_close = len(da) - 1
                    close_trig = (idx_close >= cfg.get('ma_long', 90)
                                   and ma_s[idx_close] is not None
                                   and ma_l_vals[idx_close] is not None
                                   and ma_s[idx_close] < ma_l_vals[idx_close] * (1 - mbuf))
                    if close_trig:
                        log(f"  {name}: MA crossover close (MA40<MA90*{1-mbuf})")
                        try:
                            okx_close_position(inst_id, pos_side='net', mgn_mode='cross')
                            clear_entries(name)
                            log(f"  {name}: position closed")
                        except Exception as e:
                            log(f"  {name}: close FAILED: {e}")
                        continue
                else:
                    peak = max(e.get('hi', cc) for e in coin_entries)
                    if cc <= peak * trail:
                        log(f"  {name}: trailing stop (cc={cc:.4f} <= peak={peak:.4f} * {trail})")
                        try:
                            okx_close_position(inst_id, pos_side='net', mgn_mode='cross')
                            clear_entries(name)
                            log(f"  {name}: position closed")
                        except Exception as e:
                            log(f"  {name}: close FAILED: {e}")
                        continue

            # Long: TP check (1x per day)
            if not is_short and tp:
                tp_date = get_state(name).get('tp_date', '')
                if tp_date == today: continue
                tp_hit = get_state(name).get('tp_hit', 0)
                for stage in range(tp_hit, len(tp)):
                    trg, cf = tp[stage]
                    if roi >= trg:
                        pos_qty = abs(float(pos.get('pos', 0)))
                        if pos_qty <= 0: break
                        close_ct = max(1, int(pos_qty * cf + 0.5))
                        try:
                            okx_place_order(inst_id=inst_id, td_mode='cross',
                                side='sell', sz=str(close_ct), reduce_only=True)
                            log(f"  {name}: TP {trg}% → close {close_ct}ct")
                            set_state(name, {'tp_hit': stage + 1, 'tp_date': today})
                        except Exception as e:
                            log(f"  {name}: TP {trg}% FAILED: {e}")
                    else:
                        break

            # Short: trailing stop
            if is_short:
                trough = min(e.get('lo', cc) for e in coin_entries)
                if cc >= trough * (1 + close_pct):
                    log(f"  {name}: trailing stop (cc={cc:.4f} >= trough={trough:.4f} * {1+close_pct})")
                    try:
                        okx_close_position(inst_id, pos_side='net', mgn_mode='cross')
                        clear_entries(name)
                        today = datetime.datetime.now().strftime('%Y-%m-%d')
                        set_state(name, {'last_sl_date': today})
                        log(f"  {name}: position closed")
                    except Exception as e:
                        log(f"  {name}: close FAILED: {e}")
                    continue

            # Short: TP check
            if is_short and tp:
                tp_date = get_state(name).get('tp_date', '')
                if tp_date == today: continue
                tp_hit = get_state(name).get('tp_hit', 0)
                for stage in range(tp_hit, len(tp)):
                    trg, cf = tp[stage]
                    if roi >= trg:
                        pos_qty = abs(float(pos.get('pos', 0)))
                        if pos_qty <= 0: break
                        close_ct = max(1, int(pos_qty * cf + 0.5))
                        try:
                            okx_place_order(inst_id=inst_id, td_mode='cross',
                                side='buy', sz=str(close_ct), reduce_only=True)
                            log(f"  {name}: TP {trg}% → close {close_ct}ct")
                            set_state(name, {'tp_hit': stage + 1, 'tp_date': today})
                        except Exception as e:
                            log(f"  {name}: TP {trg}% FAILED: {e}")
                    else:
                        break

            # Update entries in state_manager
            clear_entries(name)
            for e in coin_entries:
                add_entry(name, e['ep'], e.get('is_short', False), e.get('hi'), e.get('lo'))

    # Refresh entries_map from Firestore after exit actions
    if os.environ.get("OKX_API_KEY"):
        for coin in SYMBOL_OKX:
            entries_map[coin] = get_entries(coin)

    # ── Pyramid (XAU): ROI >= next_pyr_roi → add entry, next += 7% ──
    if os.environ.get("OKX_API_KEY"):
        for name, is_short, cfg in PYRAMID_STRATEGIES:
            if TRADING_COIN_LIST and name not in TRADING_COIN_LIST: continue
            if is_short or not cfg.get('_pyramid', False): continue
            coin_entries = entries_map.get(name, [])
            da = data_map.get(name, [])
            if not da or not coin_entries: continue
            cc = da[-1]['close']
            lev = cfg.get('lev', 2)
            total_mp = sum(e['mp'] for e in coin_entries if 'mp' in e) or len(coin_entries)
            avg_ep = sum(e['ep'] * (e.get('mp', 1) if 'mp' in e else 1) for e in coin_entries) / total_mp
            roi = (cc - avg_ep) / avg_ep * 100 * lev
            pyr_roi = get_state(name).get('next_pyr_roi', 8)
            pyr_date = get_state(name).get('pyr_date', '')
            if roi >= pyr_roi and pyr_date != today:
                usd_val = eq * lev * ENTRY_PCT * cfg.get('_entry_mult', 1.0)
                inst_id = SYMBOL_OKX.get(name)
                ct_val = float(next((i.get('ctVal', '0.01') for i in instruments if i['instId'] == inst_id), '0.01'))
                sz = max(1, int(usd_val / (cc * ct_val)))
                try:
                    r = okx_place_order(inst_id=inst_id, td_mode='cross',
                        side='buy', sz=str(sz))
                    log(f"  {name}: PYRAMID @ ${cc:.4f} ({roi:.1f}% ROI)")
                    add_entry(name, cc, False)
                    set_state(name, {'next_pyr_roi': pyr_roi + 7, 'pyr_date': today})
                except Exception as e:
                    log(f"  {name}: PYRAMID FAILED: {e}")

    # ── Entry check ──
    signals = []
    traded_count = 0
    for name, is_short, cfg in PYRAMID_STRATEGIES:
        if TRADING_COIN_LIST and name not in TRADING_COIN_LIST: continue
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

            for name, direction, price, lev, trail, mult in signals:
                inst_id = SYMBOL_OKX.get(name)
                if not inst_id:
                    log(f"  {name}: no instrument mapping, skipped")
                    continue
                if inst_id not in inst_map:
                    log(f"  {name}: {inst_id} not available on OKX, skipped")
                    continue

                today = datetime.datetime.now().strftime('%Y-%m-%d')

                if direction == 'SELL':
                    last_sl = get_state(name).get('last_sl_date', '')
                    if last_sl:
                        days = (datetime.datetime.now() - datetime.datetime.strptime(last_sl, '%Y-%m-%d')).days
                        if days < 2:
                            log(f"  {name}: short entry cooldown {days}d/2d, skipped")
                            continue
                    last_entry = get_state(name).get('last_entry_date', '')
                    if last_entry:
                        days = (datetime.datetime.now() - datetime.datetime.strptime(last_entry, '%Y-%m-%d')).days
                        if days < 2:
                            log(f"  {name}: short entry cooldown {days}d/2d, skipped")
                            continue
                elif has_entered_today(name):
                    log(f"  {name}: already entered today, skipped")
                    continue

                if direction == 'SELL':
                    btc_pos = pos_map.get(inst_id, {})
                    existing_margin = float(btc_pos.get('margin', 0))
                    new_margin = usd_val / lev
                    if existing_margin + new_margin > eq * SHORT_MAX_MARGIN:
                        log(f"  {name}: short cap {SHORT_MAX_MARGIN*100:.0f}% margin, skipped")
                        continue

                usd_val = eq * lev * ENTRY_PCT * mult
                if direction == 'SELL':
                    usd_val *= 2
                inst_info = inst_map[inst_id]
                ct_val_str = inst_info.get('ctVal', '')
                ct_val = float(ct_val_str) if ct_val_str else 0.01
                sz = max(1, int(usd_val / (price * ct_val)))
                side = 'buy' if direction == 'BUY' else 'sell'
                td_mode = 'cross'
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
