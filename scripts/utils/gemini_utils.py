"""Google Gemini helpers for news summarisation and breaking-news detection."""

import json
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors as genai_errors

from .retry_utils import call_with_retry

GEMINI_MODEL = "gemini-2.5-flash"

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


# ---------------------------------------------------------------------------
# Daily digest – select top-3 per topic and summarise
# ---------------------------------------------------------------------------


def summarise_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """From each topic select the 3 most important articles.

    Returns a list of dicts with keys: ``topic``, ``title``, ``url``.
    """
    articles_text = "\n\n".join(
        f"Title: {a.get('title', '')}\n"
        f"URL: {a.get('link', '')}\n"
        f"Topic: {a.get('topic', '')}"
        for a in articles
    )

    prompt = f"""You are a professional news curator. Review the articles below and:

1. From EACH topic group, select the 3 most important and impactful articles.
2. If a topic has no relevant articles, omit it.

Articles to review:
{articles_text}

Respond ONLY with valid JSON — an array of objects, each with:
- "topic": topic name in English (AI / Java / Developer / Finance / Commodities)
- "title": title or short summary in Vietnamese (descriptive, 30 words limit)
- "url": the article URL exactly as given"""

    response = call_with_retry(
        lambda: _get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        ),
        resource_name="Gemini summarise_articles",
        retry_exceptions=(genai_errors.APIError,),
    )
    return json.loads(response.text)


# ---------------------------------------------------------------------------
# Breaking news – detect high-impact financial events
# ---------------------------------------------------------------------------


def detect_breaking_news(
    articles: List[Dict[str, Any]], bitcoin_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Analyse recent news and Bitcoin price for major financial-impact events.

    Returns a dict with keys:
        ``has_breaking_news`` (bool) and ``alerts`` (list of alert dicts).

    Each alert dict has: headline, impact, summary, urls.
    """
    articles_text = "\n\n".join(
        f"Title: {a.get('title', '')}\n"
        f"URL: {a.get('link', '')}"
        for a in articles
    )

    btc_line = ""
    if bitcoin_data:
        change = bitcoin_data.get("change_24h", 0)
        btc_line = (
            f"\nBitcoin: ${bitcoin_data.get('price', 0):,.2f} | "
            f"24-h change: {change:+.2f}%"
        )

    prompt = f"""You are a financial analyst monitoring breaking news for major events
that could have a huge impact on global finance.

Criteria that qualify as BREAKING NEWS:
- Bitcoin 24-h price change exceeds ±4 %
- Major decisions from significant economies (US Fed, ECB, PBoC, etc.)
- Military conflicts starting, escalating, or ending
- Major corporate collapses or mergers with global market impact
- Supply-chain disruptions affecting key commodities
- Pandemic or major public-health declarations
{btc_line}

Recent news articles:
{articles_text}

Respond ONLY with valid JSON in this exact schema:
{{
  "has_breaking_news": true | false,
  "alerts": [
    {{
      "headline": "descriptive title in Vietnamese with cause and effect, e.g. 'Trump tăng thuế. Thị trường chứng khoán Mỹ giảm mạnh.'",
      "urls": ["url1", "url2"]
    }}
  ]
}}"""

    response = call_with_retry(
        lambda: _get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        ),
        resource_name="Gemini detect_breaking_news",
        retry_exceptions=(genai_errors.APIError,),
    )
    return json.loads(response.text)
