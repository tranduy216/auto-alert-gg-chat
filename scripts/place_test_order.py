"""Debug: try placing order and show full response (bypass okx_place_order)."""
import sys, os, json, base64, hashlib, hmac, time, requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

api_key = os.environ["OKX_API_KEY"]
api_secret = os.environ["OKX_API_SECRET"]
passphrase = os.environ["OKX_API_PASSPHRASE"]

# Build request manually
ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
body = {
    "instId": "BTC-USDT-SWAP",
    "tdMode": "cross",
    "side": "buy",
    "posSide": "long",
    "sz": "1",
    "px": "20000",
    "ordType": "limit",
}
body_str = json.dumps(body)
msg = ts + "POST" + "/api/v5/trade/order" + body_str
mac = hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256)
sign = base64.b64encode(mac.digest()).decode()

headers = {
    "OK-ACCESS-KEY": api_key,
    "OK-ACCESS-SIGN": sign,
    "OK-ACCESS-TIMESTAMP": ts,
    "OK-ACCESS-PASSPHRASE": passphrase,
    "Content-Type": "application/json",
}
resp = requests.post("https://www.okx.com/api/v5/trade/order", headers=headers, json=body, timeout=15)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text}")
