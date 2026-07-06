#!/usr/bin/env python3
"""
Test OKX ↔ DB sync: writes fake state to Firestore, fetches OKX positions,
then resets DB state for any coin that has no OKX position.
"""
import os, sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.state_manager import get_state, set_state, reset_coin_state, get_entries
from utils.okx_utils import okx_get_positions

TEST_COIN = "SYNC_TEST"
OKX_INST = "LINK-USDT-SWAP"


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")


def main():
    log("=== OKX ↔ DB Sync Test ===")

    log(f"Step 1: Write fake state for '{TEST_COIN}' to DB...")
    set_state(TEST_COIN, {
        "entries": [
            {"ep": 15.0, "is_short": False, "hi": 16.0, "lo": 14.5,
             "time": datetime.datetime.now().isoformat()},
            {"ep": 16.5, "is_short": False, "hi": 17.0, "lo": 16.0,
             "time": datetime.datetime.now().isoformat()},
        ],
        "last_entry_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "last_entry_price": 16.5,
        "tp_hit": 1,
        "tp_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "next_pyr_roi": 15,
        "pyr_date": datetime.datetime.now().strftime("%Y-%m-%d"),
    })

    before = get_entries(TEST_COIN)
    log(f"  Before: {len(before)} entries, tp_hit={get_state(TEST_COIN).get('tp_hit')}, "
        f"next_pyr_roi={get_state(TEST_COIN).get('next_pyr_roi')}")

    log("Step 2: Fetch OKX positions...")
    if not os.environ.get("OKX_API_KEY"):
        log("  OKX_API_KEY not set — skipping position fetch, treating as no positions")
        okx_has_position = False
    else:
        try:
            positions = okx_get_positions()
            okx_has_position = any(
                p["instId"] == OKX_INST and float(p.get("pos", 0)) != 0
                for p in positions
            )
            log(f"  OKX has {OKX_INST} position: {okx_has_position}")
        except Exception as e:
            log(f"  OKX fetch failed: {e}")
            okx_has_position = False

    if okx_has_position:
        log(f"  {OKX_INST} exists on OKX — keeping DB state as-is")
    else:
        log(f"Step 3: No {OKX_INST} position on OKX → reset DB state for '{TEST_COIN}'")
        reset_coin_state(TEST_COIN)

    log("Step 4: Verify DB state after sync...")
    after = get_entries(TEST_COIN)
    after_state = get_state(TEST_COIN)
    expected_empty = not okx_has_position

    if expected_empty:
        if len(after) == 0 and after_state.get("tp_hit") == 0 and after_state.get("next_pyr_roi") == 8:
            log("  PASS: State fully reset")
        else:
            log(f"  FAIL: State not reset — entries={len(after)}, tp_hit={after_state.get('tp_hit')}, "
                f"next_pyr_roi={after_state.get('next_pyr_roi')}")
            sys.exit(1)
    else:
        if len(after) == 2 and after_state.get("tp_hit") == 1:
            log("  PASS: State preserved (OKX has position)")
        else:
            log(f"  FAIL: State was modified unexpectedly — entries={len(after)}, tp_hit={after_state.get('tp_hit')}")
            sys.exit(1)

    log("=== Sync test complete ===")


if __name__ == "__main__":
    main()
