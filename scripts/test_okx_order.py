"""Test: SHORT LINK 2USD (1x) → add 1USD → update stoploss."""
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

# === STEP 0: Set leverage to 1x ===
print("[test] Setting leverage to 1x...")
lev_r = okx("POST", "/api/v5/account/set-leverage", {
    "instId": "LINK-USDT-SWAP",
    "lever": "1",
    "mgnMode": "cross",
})
print(f"[test] Leverage: code={lev_r.get('code')}")

# === STEP 1: Get current price, then SHORT with stoploss ===
ticker = okx("GET", "/api/v5/market/ticker?instId=LINK-USDT")
tdata = ticker.get("data", [{}])
entry_px = float(tdata[0].get("last", 5.0))
sl_px = f"{entry_px * 1.06:.2f}"
print(f"[test] Current price: ${entry_px}, stoploss @ ${sl_px}")

print(f"[test] SHORT 4 ct @ market, stoploss @ ${sl_px}...")
open_r = okx("POST", "/api/v5/trade/order", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "ordType": "market",
    "sz": "4",
    "attachAlgoOrds": [{
        "slTriggerPx": sl_px,
        "slOrdPx": "-1",
        "sz": "4",
        "ordType": "conditional",
        "side": "buy",
    }],
})
oid = open_r.get("data", [{}])[0].get("ordId", "")
if not oid:
    print(f"[test] FAILED: {json.dumps(open_r)}"); sys.exit(1)
print(f"[test] ✅ SHORT OPENED: {oid}")

time.sleep(5)

# === STEP 2: Get algo stop ===
print("[test] Fetching algo stops...")
algos = okx("GET", "/api/v5/trade/orders-algo-pending?instId=LINK-USDT-SWAP&ordType=conditional")
data = algos.get("data", [])
if data:
    algo_id = data[0]["algoId"]
    old_sl = data[0].get("slTriggerPx", "?")
    print(f"[test] Current stoploss: ${old_sl} (algoId: {algo_id})")
else:
    print("[test] ⚠️ No algo stop found")
    algo_id = None

time.sleep(5)

# === STEP 3: ADD 2 ct (~1 USD) ===
print("[test] ADD 2 ct SHORT @ market...")
add_r = okx("POST", "/api/v5/trade/order", {
    "instId": "LINK-USDT-SWAP",
    "tdMode": "cross",
    "side": "sell",
    "ordType": "market",
    "sz": "2",
})
print(f"[test] ADD result: code={add_r.get('code')}")

time.sleep(3)

# === STEP 4: Amend stoploss to current price × 1.06 ===
if algo_id:
    # Get current market price for amended stop
    ticker = okx("GET", "/api/v5/market/ticker?instId=LINK-USDT")
    tdata = ticker.get("data", [{}])
    cur_px = float(tdata[0].get("last", entry_px))
    new_sl = f"{cur_px * 1.06:.2f}"
    print(f"[test] Current price: ${cur_px}, amending stoploss to ${new_sl}...")
    amend_r = okx("POST", "/api/v5/trade/amend-algo-order", {
        "instId": "LINK-USDT-SWAP",
        "algoId": algo_id,
        "newSlTriggerPx": new_sl,
    })
    print(f"[test] Amend result: code={amend_r.get('code')} msg={amend_r.get('msg')}")
    if amend_r.get("code") == "0":
        print("[test] ✅ Stoploss amended!")
    else:
        print(f"[test] ⚠️ Amend failed: {json.dumps(amend_r)}")

time.sleep(5)

# === STEP 5: Close ===
print("[test] Closing SHORT...")
close_r = okx("POST", "/api/v5/trade/close-position", {
    "instId": "LINK-USDT-SWAP",
    "mgnMode": "cross",
    "posSide": "short",
})
if close_r.get("code") == "0":
    print("[test] ✅ ALL OK: SHORT → ADD → AMEND STOP → CLOSE")
else:
    print(f"[test] Close: {json.dumps(close_r)}")
