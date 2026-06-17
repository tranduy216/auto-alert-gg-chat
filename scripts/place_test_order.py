import sys, os, json, base64, hashlib, hmac, requests
from datetime import datetime

api_key = os.environ["OKX_API_KEY"]
api_secret = os.environ["OKX_API_SECRET"]
passphrase = os.environ["OKX_API_PASSPHRASE"]

ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
body = {"instId": "LINK-USDT-SWAP", "ordId": "3664595522994577408"}
body_str = json.dumps(body)
msg = ts + "POST" + "/api/v5/trade/cancel-order" + body_str
mac = hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256)
sign = base64.b64encode(mac.digest()).decode()

headers = {
    "OK-ACCESS-KEY": api_key,
    "OK-ACCESS-SIGN": sign,
    "OK-ACCESS-TIMESTAMP": ts,
    "OK-ACCESS-PASSPHRASE": passphrase,
    "Content-Type": "application/json",
}
resp = requests.post("https://www.okx.com/api/v5/trade/cancel-order", headers=headers, json=body, timeout=15)
print(f"Cancel response: {resp.text}")
