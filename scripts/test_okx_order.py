"""Test OKX API: place small LINK limit buy at $0.01, cancel after 10s."""
import json, os, sys, time, hmac, base64, requests
from datetime import datetime

def _okx_sign(ts, method, path, body, secret):
    msg = ts + method + path + (json.dumps(body) if body else "")
    mac = hmac.new(secret.encode(), msg.encode(), 'sha256')
    return base64.b64encode(mac.digest()).decode()

def okx_request(method, path, body=None):
    api_key = os.environ["OKX_API_KEY"]
    api_secret = os.environ["OKX_API_SECRET"]
    passphrase = os.environ["OKX_API_PASSPHRASE"]
    ts = datetime.utcnow().isoformat()[:-3] + "Z"
    sig = _okx_sign(ts, method, path, body, api_secret)
    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    resp = requests.request(method, f"https://www.okx.com{path}", headers=headers,
                            data=json.dumps(body) if body else None, timeout=10)
    return resp.json()

# Place a tiny limit buy at $0.01 (won't fill, LINK ≈ $5)
body = {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "limit",
    "sz": "1",
    "px": "0.01",
}
print(f"[test] Placing LINK limit buy: 1 ct @ $0.01...")
result = okx_request("POST", "/api/v5/trade/order", body)
print(f"[test] Order: {json.dumps(result, indent=2)}")

oid = result.get("data", [{}])[0].get("ordId", "")
if not oid:
    print("[test] FAILED")
    sys.exit(1)

print(f"[test] Order placed: {oid}. Waiting 10s...")
time.sleep(10)

print(f"[test] Cancelling...")
cancel = okx_request("POST", "/api/v5/trade/cancel-order", {
    "instId": "LINK-USDT-SWAP",
    "ordId": oid,
})
if cancel.get("code") == "0":
    print("[test] ✅ OKX API OK - order placed & cancelled")
else:
    print(f"[test] Cancel: {json.dumps(cancel, indent=2)}")
