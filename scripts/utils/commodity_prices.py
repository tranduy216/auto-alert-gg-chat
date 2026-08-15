"""Fetch and format a small, key-free commodity market snapshot.

Prices come from Yahoo Finance chart data (public delayed futures quotes).  The
module deliberately keeps the calculation local: the report can still be
generated when the AI provider is unavailable, and no price claim is invented
when a market feed fails.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

import requests

from .retry_utils import call_with_retry


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Yahoo futures symbols.  Keep this list focused so the twice-daily workflow
# stays fast and the Discord message remains readable.
COMMODITY_CONTRACTS: List[Dict[str, str]] = [
    {"name": "Vàng", "symbol": "GC=F", "unit": "USD/oz"},
    {"name": "Bạc", "symbol": "SI=F", "unit": "USD/oz"},
    {"name": "Đồng", "symbol": "HG=F", "unit": "USD/lb"},
    {"name": "Dầu WTI", "symbol": "CL=F", "unit": "USD/thùng"},
    {"name": "Khí tự nhiên", "symbol": "NG=F", "unit": "USD/MMBtu"},
    {"name": "Gạo thô", "symbol": "ZR=F", "unit": "cent/100 lb"},
    {"name": "Đường", "symbol": "SB=F", "unit": "cent/lb"},
    {"name": "Cà phê", "symbol": "KC=F", "unit": "cent/lb"},
    {"name": "Cao su", "symbol": "RSS3", "unit": "(chưa có dữ liệu)"},
    {"name": "Heo hơi", "symbol": "HE=F", "unit": "cent/lb"},
    {"name": "Ngô", "symbol": "ZC=F", "unit": "cent/bushel"},
    {"name": "Lúa mì", "symbol": "ZW=F", "unit": "cent/bushel"},
]

# Used to attach at most one relevant selected article to a price alert.
COMMODITY_ALIASES = {
    "Vàng": ["gold", "vàng"],
    "Bạc": ["silver", "bạc"],
    "Đồng": ["copper", "đồng"],
    "Dầu WTI": ["oil", "crude", "dầu"],
    "Khí tự nhiên": ["natural gas", "gas", "khí đốt"],
    "Gạo thô": ["rice", "gạo"],
    "Đường": ["sugar", "đường"],
    "Cà phê": ["coffee", "cà phê"],
    "Cao su": ["rubber", "cao su"],
    "Heo hơi": ["pork", "hog", "livestock", "heo", "lợn"],
    "Ngô": ["corn", "maize", "ngô"],
    "Lúa mì": ["wheat", "lúa mì"],
}


def _fetch_chart(symbol: str) -> List[float]:
    def fetch() -> List[float]:
        response = requests.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": "1y", "interval": "1d", "events": "history"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result") or []
        if not result:
            raise ValueError(f"no chart result for {symbol}")
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        values = [float(value) for value in closes if value is not None]
        if not values:
            raise ValueError(f"no closing prices for {symbol}")
        return values

    return call_with_retry(
        fetch,
        resource_name=f"Yahoo commodity {symbol}",
        retry_exceptions=(requests.RequestException, ValueError, KeyError, TypeError),
    )


def _period_status(prices: List[float], days: int) -> Dict[str, Any]:
    window = prices[-days:]
    current = prices[-1]
    high = max(window)
    low = min(window)
    start = window[0]
    return {
        "return_pct": (current / start - 1) * 100 if start else 0.0,
        "from_high_pct": (current / high - 1) * 100 if high else 0.0,
        "is_high": current >= high * 0.9995,
        "is_low": current <= low * 1.0005,
    }


def is_notable(item: Dict[str, Any]) -> bool:
    """Return true for a meaningful trend or an extreme rolling level."""
    thresholds = {"3T": 5.0, "6T": 8.0, "1N": 12.0}
    for period, threshold in thresholds.items():
        status = item["periods"][period]
        if status["is_high"] or status["is_low"]:
            return True
        if abs(status["return_pct"]) >= threshold:
            return True
    return False


def fetch_commodity_snapshot() -> List[Dict[str, Any]]:
    """Return available contracts with 3-, 6- and 12-month status."""
    snapshot: List[Dict[str, Any]] = []
    for contract in COMMODITY_CONTRACTS:
        try:
            prices = _fetch_chart(contract["symbol"])
            snapshot.append(
                {
                    **contract,
                    "price": prices[-1],
                    "periods": {
                        "3T": _period_status(prices, min(63, len(prices))),
                        "6T": _period_status(prices, min(126, len(prices))),
                        "1N": _period_status(prices, min(252, len(prices))),
                    },
                }
            )
        except Exception as exc:  # one unavailable contract must not break digest
            print(f"Warning: could not fetch commodity {contract['symbol']}: {exc}", file=sys.stderr)
    return snapshot


def format_commodity_snapshot(
    snapshot: List[Dict[str, Any]], articles: List[Dict[str, Any]] | None = None
) -> str:
    """Format a compact Vietnamese section suitable for a Discord message."""
    notable = [item for item in snapshot if is_notable(item)]
    if not notable:
        return ""
    lines = ["📊 HÀNG HÓA ĐÁNG CHÚ Ý (giá futures tham chiếu, có thể trễ)"]
    articles = articles or []
    for item in notable:
        signals = []
        for period in ("3T", "6T", "1N"):
            status = item["periods"][period]
            if status["is_high"]:
                signals.append(f"đỉnh {period}")
            elif status["is_low"]:
                signals.append(f"đáy {period}")
            elif abs(status["return_pct"]) >= {"3T": 5, "6T": 8, "1N": 12}[period]:
                signals.append(f"{status['return_pct']:+.1f}%/{period}")
        lines.append(f"• {item['name']}: {item['price']:,.2f} {item['unit']} — {', '.join(signals)}")
        aliases = COMMODITY_ALIASES.get(item["name"], [])
        related = next(
            (
                article for article in articles
                if any(alias in str(article.get("title", "")).lower() for alias in aliases)
            ),
            None,
        )
        if related:
            title = related.get("title", "Tin liên quan")
            url = related.get("url") or related.get("link")
            lines.append(f"  📰 {title}")
            if url:
                lines.append(f"  🔗 {url}")
    return "\n".join(lines)
