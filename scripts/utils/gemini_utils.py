"""Google Gemini helpers for news summarisation and breaking-news detection."""

import json
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai  # type: ignore
from google.api_core import exceptions as google_exceptions  # type: ignore

from .retry_utils import call_with_retry

GEMINI_MODEL = "gemini-2.5-flash"

_model: Optional[genai.GenerativeModel] = None


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        _model = genai.GenerativeModel(GEMINI_MODEL)
    return _model


# ---------------------------------------------------------------------------
# Daily digest – select top-2 per topic and summarise
# ---------------------------------------------------------------------------

def summarise_articles(articles: List[Dict[str, Any]]) -> str:
    """From each topic select the 2 most important articles and produce a digest.

    For every topic group the model picks the 2 most impactful articles,
    writes a 2-3 sentence summary for each, and groups them under topic headings.

    Returns a formatted multi-section report string.
    """
    articles_text = "\n\n".join(
        f"Title: {a.get('title', '')}\n"
        f"URL: {a.get('link', '')}\n"
        f"Topic: {a.get('topic', '')}"
        for a in articles
    )

    prompt = f"""You are a professional news curator. Review the articles below and:

1. From EACH topic group, select the 2 most important and impactful articles.
   Prioritise articles that report major developments, have broad market or
   industry impact, or break new ground.
2. For each selected article write a 2-3 sentence summary.
3. Group the selected articles under clear topic headings.
4. For every article include its URL.
5. Use emoji icons to make the output scannable
   (🤖 AI, ☕ Java, 💻 Dev, 💰 Finance, 🛢️ Commodities).
6. If a topic has no relevant articles, omit that section entirely.

Select at most 2 articles per topic.

Articles to review:
{articles_text}

Produce a clean, concise report in English."""

    response = call_with_retry(
        lambda: _get_model().generate_content(prompt),
        resource_name="Gemini summarise_articles",
        retry_exceptions=(google_exceptions.GoogleAPIError,),
    )
    return response.text.strip()


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
      "headline": "short headline",
      "impact": "why this matters for global finance",
      "summary": "2-3 sentences",
      "urls": ["url1", "url2"]
    }}
  ]
}}"""

    response = call_with_retry(
        lambda: _get_model().generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        ),
        resource_name="Gemini detect_breaking_news",
        retry_exceptions=(google_exceptions.GoogleAPIError,),
    )
    return json.loads(response.text)
