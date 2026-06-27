#!/usr/bin/env python3
"""
Test OKX: open 1 LINK contract long, set TP ladder + trailing stop.
All market orders for instant fill.
Run: python3 scripts/test_okx_link.py
"""
import os, sys, json, time, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_place_order,
    okx_place_algo, okx_cancel_algo, okx_get_algo_orders,
    okx_close_position, okx_get_instruments,
)

INST_ID = 'LINK-USDT-SWAP'
LEV = 2
# TP: close fractions at ROI targets
TP_SCHED = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
TRAIL_CALLBACK = '0.20'  # 20% trailing callback (tight for test)


def log(msg): print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")


def get_link_position():
    for p in okx_get_positions('SWAP'):
        if p['instId'] == INST_ID and float(p.get('pos', 0)) != 0:
            return p
    return None


def cancel_all_algos(inst_id):
    for ord_type in ['conditional', 'move_order_stop']:
        orders = okx_get_algo_orders(inst_id, ord_type)
        if orders:
            ids = [o['algoId'] for o in orders]
            log(f"  Cancelling {len(ids)} {ord_type} orders...")
            okx_cancel_algo(inst_id, ids)
            time.sleep(0.5)


def main():
    print("=" * 60)
    print("OKX LINK TEST — TP Ladder + Trailing Stop")
    print("=" * 60)

    # 1. Account info
    acct = okx_get_account()
    eq = 0
    for d in acct.get('data', []):
        if isinstance(d, dict):
            eq = float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
            if eq > 0: break
    log(f"Equity: ${eq:,.0f}")

    # 2. Instrument info
    instruments = okx_get_instruments('SWAP')
    inst_info = None
    for inst in instruments:
        if inst['instId'] == INST_ID:
            inst_info = inst
            break
    if not inst_info:
        log(f"ERROR: {INST_ID} not found")
        return
    ct_val = float(inst_info.get('ctVal', '0.01'))
    lot_sz = float(inst_info.get('lotSz', '1'))
    log(f"ctVal={ct_val}  lotSz={lot_sz}")
    log(f"Max lev={inst_info.get('lever', '?')}x")

    # 3. Cancel existing orders if any
    cancel_all_algos(INST_ID)

    # 4. Check existing position
    pos = get_link_position()
    if pos:
        qty = abs(float(pos['pos']))
        side = 'LONG' if float(pos['pos']) > 0 else 'SHORT'
        log(f"Existing position: {qty}ct {side} @ ${float(pos.get('avgPx',0)):.2f}")
        log(f"  UPL=${float(pos.get('upl',0)):.2f}  Margin=${float(pos.get('margin',0)):.2f}")
    else:
        log(f"No existing {INST_ID} position")

    # 5. Place 1 contract long (market)
    use_market = input("\nPlace 1 LINK long market? (y/N): ").strip().lower()
    if use_market == 'y':
        log(f"Placing 1ct LIMIT at current price...")
        log(f"Warning: LIMIT may not fill. Use market for instant fill.")
        ans = input("  Use MARKET instead? (Y/n): ").strip().lower()
        is_market = ans != 'n'
        if is_market:
            log(f"Placing 1ct MARKET long...")
        else:
            log(f"Placing 1ct LIMIT long... (may not fill)")
        
        try:
            result = okx_place_order(
                inst_id=INST_ID, td_mode='isolated',
                side='buy', sz='1',
            )
            ord_id = result.get('data', [{}])[0].get('ordId', '?')
            log(f"Order placed: {ord_id}")
            
            # Wait for fill
            if is_market:
                time.sleep(2)
                pos = get_link_position()
                if pos:
                    qty = abs(float(pos['pos']))
                    log(f"Filled: {qty}ct @ ${float(pos.get('avgPx',0)):.2f}")
                else:
                    log(f"Order may not have filled yet")
        except Exception as e:
            log(f"Order FAILED: {e}")
            return

    # 6. Place TP ladder
    pos = get_link_position()
    if not pos:
        log("No position to place TP on")
        return

    pos_qty = abs(float(pos['pos']))
    avg_px = float(pos.get('avgPx', 0))
    log(f"\nCurrent: {pos_qty}ct @ ${avg_px:.2f}")

    ans = input(f"Place TP ladder ({len(TP_SCHED)} stages)? (y/N): ").strip().lower()
    if ans == 'y':
        tp_ids = []
        for trg_pct, frac in TP_SCHED:
            tp_price = round(avg_px * (1 + trg_pct / (100 * LEV)), 4)
            tp_sz = max(1, int(pos_qty * frac + 0.5))
            log(f"  TP {trg_pct}% @ ${tp_price:.4f} → close {tp_sz}ct ({frac*100:.0f}%)")
            try:
                result = okx_place_algo(
                    inst_id=INST_ID, td_mode='isolated',
                    side='sell', sz=str(tp_sz),
                    ord_type='conditional', pos_side='long',
                    tp_trigger_px=str(tp_price),
                )
                algo_id = result.get('data', [{}])[0].get('algoId', '?')
                tp_ids.append(algo_id)
                log(f"    OK: {algo_id}")
            except Exception as e:
                log(f"    FAILED: {e}")
        log(f"TP ladder: {len(tp_ids)}/{len(TP_SCHED)} placed")

    # 7. Place trailing stop
    ans = input(f"Place trailing stop ({TRAIL_CALLBACK} callback)? (y/N): ").strip().lower()
    if ans == 'y':
        # Remaining size after TP
        tp_sz_sum = sum(max(1, int(pos_qty * f + 0.5)) for _, f in TP_SCHED)
        trail_sz = pos_qty - tp_sz_sum
        if trail_sz <= 0:
            trail_sz = pos_qty  # fallback: trail full position
            log(f"  TP covers 100%, setting trail on full position")
        log(f"  Trail {trail_sz}ct callback={TRAIL_CALLBACK} ({(1-float(TRAIL_CALLBACK))*100:.0f}% from peak)")
        try:
            result = okx_place_algo(
                inst_id=INST_ID, td_mode='isolated',
                side='sell', sz=str(trail_sz),
                ord_type='move_order_stop',
                callback_ratio=TRAIL_CALLBACK,
            )
            algo_id = result.get('data', [{}])[0].get('algoId', '?')
            log(f"    OK: {algo_id}")
        except Exception as e:
            log(f"    FAILED: {e}")

    # 8. Show final algo state
    log("\n--- Final algo orders ---")
    for ord_type in ['conditional', 'move_order_stop']:
        orders = okx_get_algo_orders(INST_ID, ord_type)
        for o in orders:
            tp_px = o.get('tpTriggerPx', '-')
            sl_px = o.get('slTriggerPx', '-')
            cb = o.get('callbackRatio', '-')
            log(f"  [{ord_type}] id={o.get('algoId','?')[:12]} sz={o.get('sz','?')} "
                f"TP={tp_px} SL={sl_px} CB={cb}%")

    # 9. Cleanup?
    ans = input(f"\nClose position + cancel algos? (y/N): ").strip().lower()
    if ans == 'y':
        cancel_all_algos(INST_ID)
        pos = get_link_position()
        if pos:
            try:
                okx_close_position(INST_ID, pos_side='long', mgn_mode='isolated')
                log("Position closed.")
            except Exception as e:
                log(f"Close failed: {e}")

    log("Done.")


if __name__ == '__main__':
    main()
