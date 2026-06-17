"""Place a test BTC limit buy (spot) at $20,000 with $5 capital, no leverage."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from utils.okx_utils import okx_place_order, OKXError

def main():
    r = okx_place_order(inst_id="BTC-USDT", td_mode="cash", side="buy", sz="5", px="20000")
    ord_id = r.get("data", [{}])[0].get("ordId", "?")
    print(f"[OK] Test order placed. ordId={ord_id}")
    return ord_id

if __name__ == "__main__":
    try:
        main()
    except OKXError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
