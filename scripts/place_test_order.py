import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from utils.okx_utils import okx_place_order, okx_set_leverage

inst = "BTC-USDT-SWAP"

okx_set_leverage(inst, 1, "cross")
r = okx_place_order(inst, "cross", "buy", "1", "20000", "long")
ord_id = r.get("data", [{}])[0].get("ordId", "?")
print(f"[OK] Order placed. ordId={ord_id}")
