"""Test OKX API: market short 1 ct LINK, close after 10s."""
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

# === STEP 1: Market Short 1 ct LINK ===
print("[test] Opening SHORT 1 ct LINK @ market...")
open_r = okx("POST", "/api/v5/trade/order", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "posSide": "short",
    "ordType": "market",
    "sz": "1",
})
oid = open_r.get("data", [{}])[0].get("ordId", "")
if not oid:
    print(f"[test] FAILED open: {json.dumps(open_r)}")
    sys.exit(1)
print(f"[test] SHORT opened: {oid}")

time.sleep(3)  # wait for fill

# === STEP 2: Wait 10s ===
print("[test] Waiting 10s...")
time.sleep(10)

# === STEP 3: Close position ===
print("[test] Closing SHORT (buy back 1 ct)...")
close_r = okx("POST", "/api/v5/trade/close-position", {
    "instId": "LINK-USDT-SWAP",
    "mgnMode": "cross",
    "posSide": "short",
})
print(f"[test] Close result: {json.dumps(close_r)}")

if close_r.get("code") == "0":
    print("[test] ✅ OKX API OK - SHORT opened & closed")
else:
    print(f"[test] Close may have failed: {close_r}")
