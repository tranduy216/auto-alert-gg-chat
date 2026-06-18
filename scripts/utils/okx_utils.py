"""OKX API v5 — authenticated REST client for placing orders, managing positions."""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from .retry_utils import call_with_retry

OKX_BASE = "https://www.okx.com"
OKX_INSTRUMENTS: Dict[str, str] = {
    "BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP", "BNB": "BNB-USDT-SWAP",
    "PAXG": "PAXG-USDT-SWAP",
    "TRX": "TRX-USDT-SWAP",
    "SOL": "SOL-USDT-SWAP",
}
LEVERAGE = 2.5


class OKXError(Exception):
    pass


class OKXMetadataError(OKXError):
    pass


def _okx_sign(
    method: str, path: str, body: Any, api_key: str, api_secret: str, passphrase: str
) -> Tuple[str, str, str]:
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body_str = json.dumps(body) if body else ""
    msg = ts + method.upper() + path + body_str
    mac = hmac.new(
        api_secret.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    )
    sign = base64.b64encode(mac.digest()).decode("utf-8")
    return ts, sign, api_key, passphrase


def _okx_request(method: str, path: str, body: Any = None) -> dict:
    api_key = os.environ.get("OKX_API_KEY")
    api_secret = os.environ.get("OKX_API_SECRET")
    passphrase = os.environ.get("OKX_API_PASSPHRASE")
    if not api_key or not api_secret or not passphrase:
        raise OKXError("OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE must be set")

    ts, sign, key, pwd = _okx_sign(method, path, body, api_key, api_secret, passphrase)
    headers = {
        "OK-ACCESS-KEY": key,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": pwd,
        "Content-Type": "application/json",
    }
    url = f"{OKX_BASE}{path}"

    def _do() -> requests.Response:
        resp = requests.request(method, url, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        return resp

    try:
        resp = call_with_retry(
            _do,
            resource_name=f"OKX {method} {path}",
            retry_exceptions=(requests.RequestException,),
        )
        data = resp.json()
        if data.get("code") != "0":
            raise OKXError(f"OKX error {data.get('code')}: {data.get('msg', '')}")
        return data
    except Exception as exc:
        raise OKXError(str(exc)) from exc


def okx_get_account() -> dict:
    """Return account equity / balance info."""
    return _okx_request("GET", "/api/v5/account/balance")


def okx_get_positions(inst_type: str = "SWAP") -> List[dict]:
    """Return all open positions."""
    data = _okx_request("GET", f"/api/v5/account/positions?instType={inst_type}")
    return data.get("data", [])


def okx_set_leverage(inst_id: str, lever: float, mgn_mode: str = "cross") -> dict | None:
    """Set leverage for an instrument."""
    try:
        return _okx_request("POST", "/api/v5/account/set-leverage", {
            "instId": inst_id,
            "lever": str(int(lever)),
            "mgnMode": mgn_mode,
        })
    except OKXError:
        return None


def okx_place_order(
    inst_id: str,
    td_mode: str,
    side: str,
    sz: str,
    px: Optional[str] = None,
    pos_side: Optional[str] = None,
) -> dict:
    """Place an order.
    
    - td_mode: 'cross' for cross-margin
    - side: 'buy' or 'sell'
    - sz: size in contracts
    - px: limit price (None = market order)
    - pos_side: 'long' or 'short' (required for SWAP reduce)
    """
    body: dict = {
        "instId": inst_id,
        "tdMode": td_mode,
        "side": side,
        "sz": sz,
        "ordType": "limit" if px else "market",
    }
    if px:
        body["px"] = px
    if pos_side:
        body["posSide"] = pos_side
    return _okx_request("POST", "/api/v5/trade/order", body)


def okx_close_position(inst_id: str, pos_side: str = "net", mgn_mode: str = "cross") -> dict:
    """Close a position entirely via market order. Defaults to net mode."""
    return _okx_request("POST", "/api/v5/trade/close-position", {
        "instId": inst_id,
        "posSide": pos_side,
        "mgnMode": mgn_mode,
    })


def okx_get_open_orders(inst_id: Optional[str] = None) -> List[dict]:
    """Get all open orders (pending)."""
    path = "/api/v5/trade/orders-pending"
    if inst_id:
        path += f"?instId={inst_id}"
    data = _okx_request("GET", path)
    return data.get("data", [])


def okx_cancel_order(inst_id: str, ord_id: str) -> dict:
    """Cancel an open order."""
    return _okx_request("POST", "/api/v5/trade/cancel-order", {
        "instId": inst_id,
        "ordId": ord_id,
    })


def okx_get_instruments(inst_type: str = "SWAP") -> List[dict]:
    """Get instrument details (ctVal, lot size, etc.)."""
    data = _okx_request("GET", f"/api/v5/public/instruments?instType={inst_type}")
    return data.get("data", [])


def okx_get_candles(inst_id: str, bar: str = "1D", limit: int = 30) -> Optional[List[dict]]:
    """Fetch OHLCV candles (fallback for market data, not authenticated)."""
    try:
        resp = requests.get(
            f"{OKX_BASE}/api/v5/market/candles",
            params={"instId": inst_id, "bar": bar, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            return None
        raw = list(reversed(data["data"]))
        return [
            {"open_time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
            for k in raw
        ]
    except Exception as exc:
        print(f"[okx_utils] candle fetch failed: {exc}", file=sys.stderr)
        return None


def _parse_required_positive_float(inst: dict, field: str) -> float:
    raw_value = inst.get(field)
    if raw_value in (None, ""):
        raise OKXMetadataError(f"missing {field}")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise OKXMetadataError(f"invalid {field}={raw_value!r}") from exc
    if value <= 0:
        raise OKXMetadataError(f"invalid {field}={value}")
    return value


def _parse_optional_float(inst: dict, field: str, default: float) -> float:
    raw_value = inst.get(field)
    if raw_value in (None, ""):
        return default
    return float(raw_value)


def get_instrument_map() -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Return ({instId: {ctVal, ctMult, lotSz}}, {instId: skip_reason}) for SWAP instruments."""
    instruments = okx_get_instruments("SWAP")
    m: Dict[str, dict] = {}
    skipped: Dict[str, str] = {}
    for inst in instruments:
        inst_id = inst.get("instId", "")
        if not inst_id:
            continue
        try:
            m[inst_id] = {
                "ctVal": _parse_required_positive_float(inst, "ctVal"),
                "ctMult": _parse_optional_float(inst, "ctMult", 1.0),
                "lotSz": _parse_required_positive_float(inst, "lotSz"),
            }
        except (OKXMetadataError, ValueError) as exc:
            skipped[inst_id] = str(exc)
            print(f"[okx_utils] Skipping {inst_id}: {exc}", file=sys.stderr)
    return m, skipped


def calc_contract_size(coin: str, equity_usd: float, capital_pct: float,
                       leverage: float, instrument_map: dict) -> Tuple[str, str, float]:
    """Calculate number of contracts and limit price for a new position.
    
    Returns (sz, price, position_value_usd).
    """
    inst_id = OKX_INSTRUMENTS[coin]
    info = instrument_map.get(inst_id)
    if not info:
        raise OKXMetadataError(f"missing instrument metadata for {inst_id}")

    ct_val = info.get("ctVal")
    lot_sz = info.get("lotSz")
    if not isinstance(ct_val, (int, float)) or ct_val <= 0:
        raise OKXMetadataError(f"invalid ctVal for {inst_id}")
    if not isinstance(lot_sz, (int, float)) or lot_sz <= 0:
        raise OKXMetadataError(f"invalid lotSz for {inst_id}")

    position_value = equity_usd * capital_pct * leverage
    contracts = int(position_value / ct_val / lot_sz) * lot_sz
    contracts = max(contracts, lot_sz)
    return str(int(contracts)), inst_id, position_value


def get_okx_position_for_coin(positions: List[dict], coin: str) -> Optional[dict]:
    """Find OKX position dict for a coin, if open."""
    inst_id = OKX_INSTRUMENTS.get(coin)
    if not inst_id:
        return None
    for p in positions:
        if p["instId"] == inst_id:
            return p
    return None
