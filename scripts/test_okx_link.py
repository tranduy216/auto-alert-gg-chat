#!/usr/bin/env python3
"""
Test OKX: open 1 LINK contract long, set TP ladder + trailing stop.
Auto mode for CI. Run: python3 scripts/test_okx_link.py
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
TP_SCHED = [(3, 0.25), (6, 0.25), (9, 0.25), (12, 0.25)]
TRAIL_CALLBACK = '0.20'

def log(msg): print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

def get_pos():
    for p in okx_get_positions('SWAP'):
        if p['instId'] == INST_ID and float(p.get('pos', 0)) != 0:
            return p
    return None

def cancel_algos(inst_id):
    for ot in ['conditional', 'move_order_stop']:
        orders = okx_get_algo_orders(inst_id, ot)
        if orders:
            ids = [o['algoId'] for o in orders]
            okx_cancel_algo(inst_id, ids)
            log(f"  Cancelled {len(ids)} {ot}")
            time.sleep(0.5)

def main():
    print("=" * 60)
    print("OKX LINK TEST — TP Ladder + Trailing Stop (auto)")
    print("=" * 60)

    # 1. Account
    acct = okx_get_account()
    eq = next((float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
               for d in acct.get('data', []) if isinstance(d, dict) and float(d.get('totalEq', 0)) > 0), 0)
    log(f"Equity: ${eq:,.0f}")

    # 2. Instrument
    instruments = okx_get_instruments('SWAP')
    inst_info = next((i for i in instruments if i['instId'] == INST_ID), None)
    if not inst_info:
        log(f"ERROR: {INST_ID} not found"); return
    ct_val = float(inst_info.get('ctVal', '0.01'))
    lot_sz = float(inst_info.get('lotSz', '1'))
    log(f"ctVal={ct_val}  lotSz={lot_sz}  maxLev={inst_info.get('lever','?')}x")

    # 3. Cancel existing
    cancel_algos(INST_ID)

    # 4. Check existing
    pos = get_pos()
    if pos:
        qty = abs(float(pos['pos']))
        side = 'LONG' if float(pos['pos']) > 0 else 'SHORT'
        log(f"Existing: {qty}ct {side} @ ${float(pos.get('avgPx',0)):.2f}")

    # 5. Place 1ct MARKET long
    log(f"Placing 1ct MARKET long...")
    try:
        r = okx_place_order(inst_id=INST_ID, td_mode='isolated', side='buy', sz='1')
        oid = r.get('data', [{}])[0].get('ordId', '?')
        log(f"Order: {oid}")
        time.sleep(2)
    except Exception as e:
        log(f"Order FAILED: {e}"); return

    pos = get_pos()
    if not pos:
        log("No position after order"); return
    avg_px = float(pos.get('avgPx', 0))
    pos_qty = abs(float(pos['pos']))
    log(f"Filled: {pos_qty}ct @ ${avg_px:.2f}")

    # 6. TP ladder
    tp_ids = []
    for trg_pct, frac in TP_SCHED:
        tp_price = round(avg_px * (1 + trg_pct / (100 * LEV)), 4)
        tp_sz = max(1, int(pos_qty * frac + 0.5))
        try:
            r = okx_place_algo(inst_id=INST_ID, td_mode='isolated',
                side='sell', sz=str(tp_sz),
                ord_type='conditional', pos_side='long',
                tp_trigger_px=str(tp_price))
            aid = r.get('data', [{}])[0].get('algoId', '?')
            tp_ids.append(aid)
            log(f"  TP {trg_pct}% @ ${tp_price:.4f} sz={tp_sz} → {aid}")
        except Exception as e:
            log(f"  TP {trg_pct}% FAILED: {e}")
    log(f"TP: {len(tp_ids)}/{len(TP_SCHED)} ok")

    # 7. Trailing stop
    trail_sz = pos_qty - sum(max(1, int(pos_qty * f + 0.5)) for _, f in TP_SCHED)
    if trail_sz <= 0:
        trail_sz = pos_qty
    try:
        r = okx_place_algo(inst_id=INST_ID, td_mode='isolated',
            side='sell', sz=str(trail_sz),
            ord_type='move_order_stop', callback_ratio=TRAIL_CALLBACK)
        aid = r.get('data', [{}])[0].get('algoId', '?')
        log(f"Trail: {trail_sz}ct cb={TRAIL_CALLBACK} → {aid}")
    except Exception as e:
        log(f"Trail FAILED: {e}")

    # 8. Show algos
    log("\n--- Algo orders ---")
    for ot in ['conditional', 'move_order_stop']:
        for o in okx_get_algo_orders(INST_ID, ot):
            log(f"  [{ot}] sz={o.get('sz','?')} TP={o.get('tpTriggerPx','-')} CB={o.get('callbackRatio','-')}%")

    # 9. Cleanup
    cancel_algos(INST_ID)
    pos = get_pos()
    if pos:
        try:
            okx_close_position(INST_ID, pos_side='long', mgn_mode='isolated')
            log("Position closed.")
        except Exception as e:
            log(f"Close FAILED: {e}")
    log("Done.")

if __name__ == '__main__':
    main()
