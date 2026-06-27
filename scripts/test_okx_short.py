#!/usr/bin/env python3
"""
Test BTC short: TP ladder (4/7/10/13%) + pyramid + margin cap 50% exposure.
Shared constants from backtest_shared.py.
"""
import os, sys, json, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.okx_utils import okx_get_positions, okx_place_order, okx_get_account
from backtest_shared import SHORT_MAX_MARGIN, ENTRY_PCT
from utils.state_manager import get_entries, set_state, get_state, add_entry

INST_ID = 'BTC-USDT-SWAP'
LEV = 2
PYR_ROI = 3


def main():
    print("=" * 60)
    print("BTC SHORT — TP Ladder + Pyramid + Margin Cap")
    print(f"TP: {BTC_SHORT_TP}")
    print(f"Margin cap: {SHORT_MARGIN_CAP} ({SHORT_MARGIN_CAP*2*100:.0f}% exposure at {LEV}x)")
    print("=" * 60)

    pos = None
    for p in okx_get_positions('SWAP'):
        if p['instId'] == INST_ID and float(p.get('pos', 0)) < 0:
            pos = p
            break

    if not pos:
        print("\nNo BTC short position.")
        return

    pos_qty = abs(float(pos['pos']))
    avg_px = float(pos.get('avgPx', 0))
    margin = float(pos.get('margin', 0))
    upl = float(pos.get('upl', 0))
    roi = upl / margin * 100 if margin else 0
    btc_da = fetch_candles('BTCUSDT', 10)
    live_price = btc_da[-1]['close'] if btc_da else avg_px

    acct = okx_get_account()
    eq = 0
    for d in acct.get('data', []):
        if isinstance(d, dict):
            eq = float(d.get('totalEq', 0) or d.get('eq', 0) or 0)
            if eq > 0: break

    print(f"\n  Equity:    ${eq:,.0f}")
    print(f"  Contracts:  {pos_qty}")
    print(f"  Avg entry:  ${avg_px:,.1f}")
    print(f"  Live px:    ${live_price:,.1f}")
    print(f"  Margin:     ${margin:,.0f} ({margin/eq*100:.1f}% equity)")
    print(f"  ROI:        {roi:+.1f}%")

    entries = get_entries('BTC')
    total_short_mp = sum(1 for _ in entries)  # approximate
    print(f"\n  Firestore entries: {len(entries)}")
    for i, e in enumerate(entries):
        roi_i = (e['ep'] - live_price) / e['ep'] * 100 * LEV
        print(f"    [{i}] ep=${e['ep']:,.1f} ROI={roi_i:+.1f}%")

    tp_stage = get_state('BTC').get('tp_stage', 0)
    print(f"\n  TP stage: {tp_stage} / {len(BTC_SHORT_TP)}")

    # ── Check each TP stage ──
    for stage in range(tp_stage, len(BTC_SHORT_TP)):
        trg, frac = BTC_SHORT_TP[stage]
        if roi >= trg:
            close_ct = max(1, int(pos_qty * frac + 0.5))
            print(f"\n  STAGE {stage+1}: ROI {roi:+.1f}% >= {trg}%")
            print(f"    → Close {close_ct}ct ({frac*100:.0f}%) @ ${live_price:,.1f}")

            ans = input(f"    Execute? (y/N): ").strip().lower()
            if ans == 'y':
                try:
                    okx_place_order(
                        inst_id=INST_ID, td_mode='isolated',
                        side='buy', sz=str(close_ct),
                        pos_side='short', reduce_only=True,
                    )
                    set_state('BTC', {'tp_stage': stage + 1})
                    print(f"    OK. Stage {stage+1} done.")

                    # Pyramid add after TP (except last stage)
                    if stage + 1 < len(BTC_SHORT_TP):
                        new_mp = ENTRY_PCT * eq
                        if total_short_mp * eq * ENTRY_PCT + new_mp <= SHORT_MARGIN_CAP * 10000:
                            print(f"    → Pyramid entry @ ${live_price:,.1f} ({new_mp/eq*100:.1f}% equity)")
                            ans2 = input(f"    Add pyramid? (y/N): ").strip().lower()
                            if ans2 == 'y':
                                add_entry('BTC', live_price, True)
                                total_short_mp += 1
                                print(f"    Saved.")
                        else:
                            print(f"    → Pyramid blocked: margin cap reached")
                except Exception as e:
                    print(f"    FAILED: {e}")
            else:
                print(f"    Skipped.")
        else:
            print(f"\n  STAGE {stage+1}: ROI {roi:+.1f}% < {trg}% — skip")
            break

    # ── Pyramid (separate from TP) ──
    if entries:
        last_ep = entries[-1]['ep']
        pyr_roi = (last_ep - live_price) / last_ep * 100 * LEV
        if pyr_roi >= PYR_ROI:
            new_mp = ENTRY_PCT * eq
            if total_short_mp * eq * ENTRY_PCT + new_mp <= SHORT_MARGIN_CAP * 10000:
                print(f"\n  PYRAMID: roi from last {pyr_roi:+.1f}% >= {PYR_ROI}%")
                ans = input(f"    Add entry @ ${live_price:,.1f}? (y/N): ").strip().lower()
                if ans == 'y':
                    add_entry('BTC', live_price, True)
                    print(f"    Saved.")
            else:
                print(f"\n  PYRAMID: {pyr_roi:+.1f}% >= {PYR_ROI}%, but margin cap reached")
        else:
            print(f"\n  PYRAMID: {pyr_roi:+.1f}% < {PYR_ROI}%")

    print(f"\nDone. tp_stage={get_state('BTC').get('tp_stage', 0)} entries={len(get_entries('BTC'))}")


if __name__ == '__main__':
    main()
