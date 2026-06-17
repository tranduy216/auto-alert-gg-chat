import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from utils.okx_utils import okx_cancel_order

# Cancel both test orders
for inst, oid in [("BTC-USDT-SWAP", "3664592653822205952"),
                  ("LINK-USDT-SWAP", "3664595522994577408")]:
    try:
        okx_cancel_order(inst, oid)
        print(f"[OK] {inst} {oid} cancelled")
    except Exception as e:
        print(f"[skip] {inst} {oid}: {e}")
