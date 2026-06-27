#!/usr/bin/env python3
"""
Test OKX core actions: open entry, get position, close partial, close all.
No algos. Run: python3 scripts/test_okx_link.py
"""
import os, sys, json, time, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.okx_utils import (
    okx_get_account, okx_get_positions, okx_place_order,
    okx_close_position, okx_get_instruments,
)

INST_ID = 'LINK-USDT-SWAP'

def log(msg): print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

def get_pos():
    for p in okx_get_positions('SWAP'):
        if p['instId'] == INST_ID and float(p.get('pos', 0)) != 0:
            return p
    return None

def main():
    print("=" * 60)
    print("OKX CORE ACTIONS TEST — Market Order Only")
    print("=" * 60)

    # 1. Account
    acct = okx_get_account()
    eq = next((float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
               for d in acct.get('data', []) if isinstance(d, dict) and float(d.get('totalEq', 0)) > 0), 0)
    log(f"Equity: ${eq:,.0f}")

    # 2. Instrument
    instruments = okx_get_instruments('SWAP')
    inst = next((i for i in instruments if i['instId'] == INST_ID), None)
    if not inst: log(f"ERROR: {INST_ID} not found"); return
    ct_val = float(inst.get('ctVal', '0.01'))
    lot_sz = float(inst.get('lotSz', '1'))
    max_lev = float(inst.get('lever', '0'))
    log(f"ctVal={ct_val}  lotSz={lot_sz}  maxLev={max_lev:.0f}x")

    # 3. Check existing
    pos = get_pos()
    if pos:
        log(f"Existing: {abs(float(pos['pos']))}ct LONG @ ${float(pos.get('avgPx',0)):.2f}")
        log(f"Closing existing first...")
        okx_close_position(INST_ID, pos_side='net', mgn_mode='isolated')
        log("Closed.")
        time.sleep(1)

    # 4. Open 1ct MARKET long
    log("\n--- OPEN ENTRY ---")
    log("Placing 1ct MARKET long (cross)...")
    try:
        r = okx_place_order(inst_id=INST_ID, td_mode='cross', side='buy', sz='1')
        oid = r.get('data', [{}])[0].get('ordId', '?')
        log(f"Order placed: {oid}")
    except Exception as e:
        log(f"Order FAILED: {e}"); return

    time.sleep(2)
    pos = get_pos()
    if not pos:
        log("No position found after order"); return
    avg_px = float(pos.get('avgPx', 0))
    pos_qty = abs(float(pos['pos']))
    margin = float(pos.get('margin', 0))
    upl = float(pos.get('upl', 0))
    log(f"Position: {pos_qty}ct @ ${avg_px:.2f}  Margin=${margin:.2f}  UPL=${upl:.2f}")

    # 5. Close partial (50%)
    log("\n--- CLOSE PARTIAL ---")
    close_sz = max(lot_sz, int(pos_qty * 0.5 / lot_sz) * lot_sz)
    log(f"Closing {close_sz}ct (reduce_only)...")
    try:
        r = okx_place_order(inst_id=INST_ID, td_mode='cross',
            side='sell', sz=str(close_sz), reduce_only=True)
        oid = r.get('data', [{}])[0].get('ordId', '?')
        log(f"Partial close: {oid}")
    except Exception as e:
        log(f"Partial close FAILED: {e}")

    time.sleep(2)
    pos = get_pos()
    if pos:
        remain = abs(float(pos['pos']))
        log(f"Remaining: {remain}ct @ ${float(pos.get('avgPx',0)):.2f}")
    else:
        log("Position fully closed by partial order")

    # 6. Close all remaining
    log("\n--- CLOSE ALL ---")
    pos = get_pos()
    if pos:
        try:
            okx_close_position(INST_ID, pos_side='net', mgn_mode='cross')
            log("Position closed.")
        except Exception as e:
            log(f"Close FAILED: {e}")

    time.sleep(1)
    pos = get_pos()
    log(f"Final position: {'None' if not pos else abs(float(pos['pos']))}")

    log("\nDone.")

if __name__ == '__main__':
    main()
