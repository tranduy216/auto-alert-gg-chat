#!/usr/bin/env python3
"""Test OKX API: place $1 market LONG on LINK-USDT-SWAP, test actions, then close."""

import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from utils.okx_utils import (
    okx_get_account,
    okx_get_positions,
    okx_set_leverage,
    okx_place_order,
    okx_get_open_orders,
    okx_get_algo_orders,
    okx_close_position,
    okx_get_instruments,
    OKXError,
)

LINK_INST = "LINK-USDT-SWAP"
TEST_USD = 1.0


def find_link_instrument():
    """Fetch instrument info for LINK-USDT-SWAP."""
    print(f"[1] Fetching instrument info for {LINK_INST}...")
    instruments = okx_get_instruments("SWAP")
    for inst in instruments:
        if inst.get("instId") == LINK_INST:
            ct_val = float(inst["ctVal"])
            lot_sz = float(inst["lotSz"])
            print(f"    ✓ ctVal={ct_val}, lotSz={lot_sz}")
            return ct_val, lot_sz
    raise RuntimeError(f"{LINK_INST} not found in instruments")


def calc_contracts(ct_val, lot_sz, usd_value, leverage=2.0):
    """Calculate number of contracts for a given USD value."""
    position_value = usd_value * leverage
    contracts = int(position_value / ct_val / lot_sz) * lot_sz
    contracts = max(contracts, lot_sz)
    return str(int(contracts))


def main():
    print("=" * 60)
    print("  OKX API TEST — LINK-USDT-SWAP $1 Market LONG")
    print("=" * 60)

    # Check env vars
    for key in ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"]:
        if not os.environ.get(key):
            print(f"ERROR: {key} not set")
            sys.exit(1)

    # Step 1: Get instrument info
    ct_val, lot_sz = find_link_instrument()

    # Step 2: Set leverage
    time.sleep(5)
    print(f"\n[2] Setting leverage to 2x...")
    result = okx_set_leverage(LINK_INST, 2.0)
    print(f"    ✓ Leverage set: {result}")

    # Step 3: Check account balance
    time.sleep(5)
    print(f"\n[3] Checking account balance...")
    account = okx_get_account()
    if account.get("data"):
        bal = account["data"][0]
        eq = bal.get("totalEq", "N/A")
        print(f"    ✓ Total equity: ${eq}")

    # Step 4: Check existing positions
    time.sleep(5)
    print(f"\n[4] Checking existing positions...")
    positions = okx_get_positions()
    link_pos = [p for p in positions if p.get("instId") == LINK_INST]
    if link_pos:
        print(f"    ⚠ Existing LINK position: {link_pos[0].get('pos', '0')} contracts")
    else:
        print(f"    ✓ No existing LINK position")

    # Step 5: Place $1 market LONG order
    sz = calc_contracts(ct_val, lot_sz, TEST_USD)
    print(f"\n[5] Placing market LONG order: {sz} contracts (~${TEST_USD} @ 2x)...")
    try:
        order = okx_place_order(
            inst_id=LINK_INST,
            td_mode="cross",
            side="buy",
            sz=sz,
        )
        ord_id = order.get("data", [{}])[0].get("ordId", "N/A")
        print(f"    ✓ Order placed: ordId={ord_id}")
    except OKXError as e:
        print(f"    ✗ Order failed: {e}")
        sys.exit(1)

    # Step 6: Wait and check position
    time.sleep(5)
    print(f"\n[6] Checking position after 5s...")
    positions = okx_get_positions()
    link_pos = [p for p in positions if p.get("instId") == LINK_INST]
    if link_pos:
        p = link_pos[0]
        print(f"    ✓ Position open:")
        print(f"      Side: {p.get('posSide', 'net')}")
        print(f"      Size: {p.get('pos', '0')} contracts")
        print(f"      Avg price: {p.get('avgPx', 'N/A')}")
        print(f"      uPnL: {p.get('upl', '0')}")
    else:
        print(f"    ⚠ No position found (may have been filled and closed)")

    # Step 7: Check open orders
    time.sleep(5)
    print(f"\n[7] Checking open orders...")
    open_orders = okx_get_open_orders(LINK_INST)
    if open_orders:
        print(f"    Open orders: {len(open_orders)}")
        for o in open_orders:
            print(f"      ordId={o.get('ordId')} side={o.get('side')} sz={o.get('sz')}")
    else:
        print(f"    ✓ No open orders (market order already filled)")

    # Step 8: Check algo orders
    time.sleep(5)
    print(f"\n[8] Checking algo/stop orders...")
    try:
        algo_orders = okx_get_algo_orders(LINK_INST)
        if algo_orders:
            print(f"    Algo orders: {len(algo_orders)}")
            for o in algo_orders:
                print(f"      algoId={o.get('algoId')} type={o.get('ordType')}")
        else:
            print(f"    ✓ No algo orders")
    except OKXError as e:
        print(f"    ⚠ Algo check: {e}")

    # Step 9: Close position
    time.sleep(5)
    print(f"\n[9] Closing position...")
    try:
        close_result = okx_close_position(LINK_INST)
        print(f"    ✓ Position closed: {close_result}")
    except OKXError as e:
        print(f"    ✗ Close failed: {e}")

    # Step 10: Verify position closed
    time.sleep(5)
    print(f"\n[10] Verifying position closed...")
    positions = okx_get_positions()
    link_pos = [p for p in positions if p.get("instId") == LINK_INST]
    if link_pos:
        pos_sz = float(link_pos[0].get("pos", 0))
        if abs(pos_sz) < 0.001:
            print(f"    ✓ Position closed (size=0)")
        else:
            print(f"    ⚠ Position still open: {pos_sz} contracts")
    else:
        print(f"    ✓ No position (fully closed)")

    print("\n" + "=" * 60)
    print("  OKX API TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
