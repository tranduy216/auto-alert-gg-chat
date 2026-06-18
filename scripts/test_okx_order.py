"""Test: OPEN LONG LINK → place stoploss → update stoploss → close."""
import json, os, sys, time, hmac, base64, requests
from datetime import datetime

def okx_sign(ts, method, path, body, secret):
    msg = ts + method + path + (json.dumps(body) if body else "")
    mac = hmac.new(secret.encode(), msg.encode(), 'sha256')
    return base64.b64encode(mac.digest()).decode()

def okx(method, path, body=None):
    k, s, p = os.environ["OKX_API_KEY"], os.environ["OKX_API_SECRET"], os.environ["OKX_API_PASSPHRASE"]
    ts = datetime.utcnow().isoformat()[:-3] + "Z"
    sig = okx_sign(ts, method, path, body, s)
    r = requests.request(method, f"https://www.okx.com{path}",
        headers={"OK-ACCESS-KEY":k,"OK-ACCESS-SIGN":sig,"OK-ACCESS-TIMESTAMP":ts,
                 "OK-ACCESS-PASSPHRASE":p,"Content-Type":"application/json"},
        data=json.dumps(body) if body else None, timeout=10)
    return r.json()

# === STEP 1: OPEN LONG 1 ct LINK with stoploss ===
entry_px = 5.0  # LINK ≈ $5
sl_px = f"{entry_px * 0.98:.2f}"  # 6%/3x = 2% below
print(f"[test] OPEN LONG 1 ct @ market, stoploss @ ${sl_px}...")
open_r = okx("POST", "/api/v5/trade/order", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "market",
    "sz": "1",
    "slTriggerPx": sl_px,
    "slOrdPx": "-1",
})
oid = open_r.get("data", [{}])[0].get("ordId", "")
if not oid:
    print(f"[test] FAILED: {json.dumps(open_r)}"); sys.exit(1)
print(f"[test] ✅ OPENED: {oid}")

time.sleep(5)

# === STEP 2: Check existing algo stops ===
print("[test] Fetching algo stops...")
algos = okx("GET", "/api/v5/trade/orders-algo-pending?instId=LINK-USDT-SWAP&ordType=conditional")
print(f"[test] Algo stops: {len(algos.get('data',[]))} found")
old_ids = [o["algoId"] for o in algos.get("data",[]) if o.get("algoId")]
print(f"[test] IDs: {old_ids}")

# === STEP 3: Cancel old stop, place new one ===
if old_ids:
    print(f"[test] Cancelling old stop(s): {old_ids}...")
    cancel_r = okx("POST", "/api/v5/trade/cancel-algos", {
        "instId": "LINK-USDT-SWAP",
        "algoIds": old_ids,
    })
    print(f"[test] Cancel result: code={cancel_r.get('code')}")

new_sl = f"{entry_px * 0.97:.2f}"  # tighter: 9%/3x = 3% below
print(f"[test] Placing new stoploss @ ${new_sl}...")
new_algo = okx("POST", "/api/v5/trade/order-algo", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "sz": "1",
    "ordType": "conditional",
    "triggerPx": new_sl,
    "triggerPxType": "last",
    "tpTriggerPxType": "last",
})
print(f"[test] New algo: code={new_algo.get('code')} {json.dumps(new_algo.get('data',[{}])[0])}")

time.sleep(5)

# === STEP 4: Close everything ===
print("[test] Closing LONG (sell 1 ct @ market)...")
close_r = okx("POST", "/api/v5/trade/close-position", {
    "instId": "LINK-USDT-SWAP",
    "mgnMode": "cross",
})
print(f"[test] Close: code={close_r.get('code')}")
if close_r.get("code") == "0":
    print("[test] ✅ ALL OK: OPEN → STOPLOSS → UPDATE STOP → CLOSE")
else:
    print(f"[test] Close full: {json.dumps(close_r)}")
PYEOF

if close_r.get("code") == "0":
    print("[test] ✅ OKX API OK - SHORT opened & closed")
else:
    print(f"[test] Close may have failed: {close_r}")
