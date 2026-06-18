"""Test: OPEN LONG LINK → amend stoploss → close."""
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

# === STEP 1: OPEN LONG with stoploss ===
print("[test] OPEN LONG 1 ct @ market with stoploss...")
open_r = okx("POST", "/api/v5/trade/order", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "market",
    "sz": "1",
    "attachAlgoOrds": [{
        "slTriggerPx": "4.90",
        "slOrdPx": "-1",
        "sz": "1",
        "ordType": "conditional",
        "side": "sell",
    }],
})
oid = open_r.get("data", [{}])[0].get("ordId", "")
if not oid:
    print(f"[test] FAILED: {json.dumps(open_r)}"); sys.exit(1)
print(f"[test] ✅ OPENED: {oid}")

time.sleep(5)

# === STEP 2: Get algo order and amend ===
print("[test] Fetching algo stops...")
algos = okx("GET", "/api/v5/trade/orders-algo-pending?instId=LINK-USDT-SWAP&ordType=conditional")
data = algos.get("data", [])
print(f"[test] Algo stops: {len(data)} found")
if data:
    algo_id = data[0]["algoId"]
    old_sl = data[0].get("slTriggerPx", "?")
    print(f"[test] Current stoploss: ${old_sl} (algoId: {algo_id})")
    
    print("[test] Amending stoploss to $4.95...")
    amend_r = okx("POST", "/api/v5/trade/amend-algo-order", {
        "instId": "LINK-USDT-SWAP",
        "algoId": algo_id,
        "newSlTriggerPx": "4.95",
    })
    print(f"[test] Amend result: code={amend_r.get('code')} msg={amend_r.get('msg')}")
    
    if amend_r.get("code") == "0":
        print("[test] ✅ Stoploss amended successfully!")
    else:
        print(f"[test] ⚠️ Amend failed: {json.dumps(amend_r)}")
else:
    print("[test] ⚠️ No algo stops found")

time.sleep(5)

# === STEP 3: Close ===
print("[test] Closing LONG...")
close_r = okx("POST", "/api/v5/trade/close-position", {
    "instId": "LINK-USDT-SWAP",
    "mgnMode": "cross",
})
if close_r.get("code") == "0":
    print("[test] ✅ ALL OK: OPEN → AMEND STOP → CLOSE")
else:
    print(f"[test] Close: {json.dumps(close_r)}")
