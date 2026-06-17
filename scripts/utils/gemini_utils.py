"""OpenRouter AI helpers for news summarisation and breaking-news detection."""

import json
import os
from typing import Any, Dict, List

import requests

from .retry_utils import call_with_retry

OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class AIError(Exception):
    pass


def _call_openrouter(
    system_prompt: str,
    user_prompt: str,
    response_format: str | None = None,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise AIError("OPENROUTER_API_KEY is not set")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body: dict = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
    }
    if response_format:
        body["response_format"] = {"type": response_format}

    def _do_request() -> str:
        resp = requests.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        if not text:
            raise AIError("Empty response from OpenRouter")
        return text

    try:
        return call_with_retry(
            _do_request,
            resource_name="OpenRouter",
            retry_exceptions=(requests.RequestException, AIError),
        )
    except Exception as exc:
        raise AIError(str(exc)) from exc


SYSTEM_PROMPT_SUMMARISE = """You are a professional news curator. Respond ONLY with valid JSON."""

USER_PROMPT_SUMMARISE_TPL = """Review the articles below and:

1. From EACH topic group, select the most important and impactful articles.
   Topics: AI (gồm cả tin về các công ty AI lớn), Java, Developer (lập trình,
   framework, performance), Big Tech (Google, Microsoft, Apple, Meta, Amazon…),
   Finance, Commodities.
2. If a topic has no relevant articles, omit it.

Articles to review:
{articles}

Respond ONLY with valid JSON — an array of objects, each with:
- "topic": topic name in English (AI / Java / Developer / Big Tech / Finance / Commodities)
- "title": descriptive title in Vietnamese
- "url": the article URL exactly as given"""


def summarise_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    articles_text = "\n\n".join(
        f"Title: {a.get('title', '')}\n"
        f"URL: {a.get('link', '')}\n"
        f"Topic: {a.get('topic', '')}"
        for a in articles
    )
    user_prompt = USER_PROMPT_SUMMARISE_TPL.format(articles=articles_text)
    text = _call_openrouter(SYSTEM_PROMPT_SUMMARISE, user_prompt, "json_object")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    data = json.loads(text)
    if isinstance(data, list) and all(isinstance(i, dict) and "title" in i for i in data):
        return data
    print(f"[gemini_utils] AI returned unexpected format: {type(data).__name__}", file=sys.stderr)
    return []


SYSTEM_PROMPT_BREAKING = """You are a financial analyst monitoring breaking news for major events
that could have a huge impact on global finance. Respond ONLY with valid JSON."""

USER_PROMPT_BREAKING_TPL = """Criteria that qualify as BREAKING NEWS:
- Bitcoin 24-h price change exceeds ±4 %
- Major decisions from significant economies (US Fed, ECB, PBoC, etc.)
- Military conflicts starting, escalating, or ending
- Major corporate collapses or mergers with global market impact
- Supply-chain disruptions affecting key commodities
- Pandemic or major public-health declarations
{btc_line}

Recent news articles:
{articles}

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


def detect_breaking_news(
    articles: List[Dict[str, Any]], bitcoin_data: Dict[str, Any]
) -> Dict[str, Any]:
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

    user_prompt = USER_PROMPT_BREAKING_TPL.format(
        btc_line=btc_line, articles=articles_text
    )
    text = _call_openrouter(SYSTEM_PROMPT_BREAKING, user_prompt, "json_object")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)
