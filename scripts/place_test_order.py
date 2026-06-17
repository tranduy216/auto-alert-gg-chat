import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from utils.okx_utils import okx_place_order, okx_cancel_order

# cancel BTC order from earlier if still open
try:
    okx_cancel_order("BTC-USDT-SWAP", "3664592653822205952")
    print("[OK] BTC order cancelled")
except Exception as e:
    print(f"[skip] BTC cancel: {e}")

# LINK limit buy @ $5, $10 capital → 2 contracts (≈1 LINK/ct)
r = okx_place_order("LINK-USDT-SWAP", "cross", "buy", "2", "5")
ord_id = r.get("data", [{}])[0].get("ordId", "?")
print(f"[OK] LINK order placed. ordId={ord_id}")
