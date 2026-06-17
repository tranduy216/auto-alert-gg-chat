import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from utils.okx_utils import okx_place_order, okx_get_account

acct = okx_get_account()
print(f"Account: {json.dumps(acct, indent=2)}")
