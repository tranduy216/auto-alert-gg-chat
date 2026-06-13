"""OpenAI helpers for news summarisation and breaking-news detection."""

import json
import os
from typing import Dict, Any, List

from typing import Optional

from openai import OpenAI, OpenAIError  # type: ignore

from .retry_utils import call_with_retry

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


# ---------------------------------------------------------------------------
# Daily digest – summarise & filter RSS articles
# ---------------------------------------------------------------------------

def summarise_articles(articles: List[Dict[str, Any]]) -> str:
    """Filter and summarise a list of RSS articles by topic.

    Topics of interest: AI/ML, Java, Software Development, Finance/Economics,
    Commodity prices (oil, gold, rubber, etc.).

    Returns a formatted multi-section report string.
    """
    articles_text = "\n\n".join(
        f"Title: {a.get('title', '')}\n"
        f"URL: {a.get('link', '')}\n"
        f"Topic: {a.get('topic', '')}"
        for a in articles
    )

    prompt = f"""You are a professional news curator. Review the articles below and:

1. Keep ONLY articles that are relevant to these topics:
   - Artificial Intelligence / Machine Learning
   - Java programming / JVM ecosystem
   - Software development & engineering
   - Finance, economics, global markets
   - Commodity prices: oil, gold, rubber, or other major commodities

2. For each relevant article write a 2-3 sentence summary.
3. Group the selected articles under clear topic headings.
4. For every article include its URL.
5. Use emoji icons to make the output scannable (e.g. 🤖 for AI, ☕ for Java, 💻 for Dev, 💰 for Finance, 🛢️ for commodities).
6. If no relevant articles are found, say so briefly.

Articles to review:
{articles_text}

Produce a clean, concise report in English."""

    response = call_with_retry(
        lambda: _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional news curator and financial analyst.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
        ),
        resource_name="OpenAI summarise_articles",
        retry_exceptions=(OpenAIError,),
    )
    return response.choices[0].message.content.strip()


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
        lambda: _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional financial analyst. "
                        "Always respond with valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            response_format={"type": "json_object"},
        ),
        resource_name="OpenAI detect_breaking_news",
        retry_exceptions=(OpenAIError,),
    )
    return json.loads(response.choices[0].message.content)
