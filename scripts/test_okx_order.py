#!/usr/bin/env python3
"""Test OKX API: place 10 USD LINK limit order at $5000, cancel after 10s."""
import json, os, sys, time, hmac, base64, requests
from datetime import datetime

def _okx_sign(ts: str, method: str, path: str, body: str, secret: str) -> str:
    msg = ts + method + path + body
    mac = hmac.new(secret.encode(), msg.encode(), 'sha256')
    return base64.b64encode(mac.digest()).decode()

def okx_request(method: str, path: str, body: dict = None) -> dict:
    api_key = os.environ["OKX_API_KEY"]
    api_secret = os.environ["OKX_API_SECRET"]
    passphrase = os.environ["OKX_API_PASSPHRASE"]
    ts = datetime.utcnow().isoformat()[:-3] + "Z"
    body_str = json.dumps(body) if body else ""
    sig = _okx_sign(ts, method, path, body_str, api_secret)
    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    resp = requests.request(method, f"https://www.okx.com{path}", headers=headers, data=body_str, timeout=10)
    return resp.json()

# Place limit order: LINK, buy long, 10 USD, limit price $5000 (won't fill)
sz = "0.002"  # ~10 USD at current LINK price
print(f"[test] Placing LINK limit order: 10 USD @ $5000...")
result = okx_request("POST", "/api/v5/trade/order", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "ordType": "limit",
    "sz": sz,
    "px": "5000",
})
print(f"[test] Order result: {json.dumps(result, indent=2)}")

order_id = result.get("data", [{}])[0].get("ordId", "")
if not order_id:
    print("[test] FAILED: no order ID")
    sys.exit(1)

print(f"[test] Order placed: {order_id}. Waiting 10s before cancel...")
time.sleep(10)

print(f"[test] Cancelling order {order_id}...")
cancel = okx_request("POST", "/api/v5/trade/cancel-order", {
    "instId": "LINK-USDT-SWAP",
    "ordId": order_id,
})
print(f"[test] Cancel result: {json.dumps(cancel, indent=2)}")
if cancel.get("code") == "0":
    print("[test] ✅ SUCCESS: API working, order placed and cancelled")
else:
    print(f"[test] Cancel may have failed: {cancel}")
