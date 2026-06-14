"""Shared keyword-based prefilter helpers for token-efficient AI calls."""

from collections import defaultdict
from typing import Any, Dict, Iterable, List

# Daily digest topic keywords (editable map).
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "AI": [
        "gpt",
        "gemini",
        "claude",
        "llama",
        "mistral",
        "openai",
        "anthropic",
        "deepmind",
        "model",
        "ai agent",
        "ai os",
        "agentic runtime",
        "digital workforce",
        "autonomous organization",
        "reasoning",
        "multimodal",
        "fine-tuning",
        "frontier model",
        "agi",
    ],
    "Java": [
        "java",
        "jvm",
        "spring",
        "spring boot",
        "kotlin",
        "gradle",
        "maven",
        "quarkus",
        "micronaut",
        "virtual threads",
        "jdk",
        "openjdk",
    ],
    "Developer": [
        "programming",
        "programmer",
        "performance",
        "framework",
        "architecture",
        "design",
        "design pattern",
        "scalability",
        "reliability",
        "observability",
        "refactoring",
        "clean code",
        "engineering",
        "developer experience",
        "testing",
        "devops",
        "api",
        "platform",
        "security",
        "compiler",
        "runtime",
        "concurrency",
        "debugging",
    ],
    "Big Tech": [
        "google",
        "microsoft",
        "apple",
        "meta",
        "amazon",
        "netflix",
        "tesla",
        "nvidia",
        "intel",
        "amd",
        "oracle",
        "ibm",
        "salesforce",
        "acquisition",
        "layoff",
        "antitrust",
        "big tech",
        "silicon valley",
        "biggest",
        "giant",
    ],
    "Finance": [
        "inflation",
        "interest rate",
        "federal reserve",
        "fed",
        "central bank",
        "monetary policy",
        "quantitative easing",
        "tightening",
        "stocks",
        "stock market",
        "bonds",
        "treasury",
        "recession",
        "gdp",
        "unemployment",
        "jobless",
        "payroll",
        "earnings",
        "market",
        "tariff",
        "trade war",
        "economy",
        "economic",
        "slowdown",
        "downturn",
        "crash",
        "bear market",
        "bull market",
        "volatility",
        "short selling",
        "short squeeze",
        "hedge fund",
        "etf",
        "dividend",
        "banking",
        "bank run",
        "liquidity",
        "default",
        "debt",
        "deficit",
        "fiscal",
        "stimulus",
        "currency",
        "forex",
        "dollar",
        "yuan",
        "yen",
        "euro",
        "cpi",
        "ppi",
        "yield curve",
        "rating",
        "downgrade",
        "bailout",
        "securities",
        "commodities trading",
        "futures",
        "derivatives",
    ],
    "Technical Trend": [
        "ai coding agent",
        "agentic workflow",
        "claude code",
        "openhands",
        "mcp",
        "software architecture",
        "distributed systems",
        "system design",
        "kafka",
        "postgresql",
        "engineering leadership",
        "staff engineer",
        "team topology",
        "developer experience",
        "product strategy",
        "b2b saas",
        "developer tools",
        "engineering trends",
        "technology forecast",
        "ai software development",
    ],
    "Commodities": [
        "oil",
        "gold",
        "gas",
        "rubber",
        "copper",
        "silver",
        "crude",
        "opec",
        "supply",
        "demand",
        "commodity",
    ],
}

# Breaking-news keywords: finance + high-impact risk events.
BREAKING_NEWS_KEYWORDS: List[str] = sorted(
    set(
        TOPIC_KEYWORDS["Finance"]
        + TOPIC_KEYWORDS["Commodities"]
        + [
            "bitcoin",
            "fed",
            "ecb",
            "pboc",
            "war",
            "conflict",
            "ceasefire",
            "sanction",
            "merger",
            "collapse",
            "supply chain",
            "pandemic",
            "outbreak",
        ]
    )
)


def _normalise(text: str) -> str:
    return str(text).lower().strip()


def keyword_hit_count(text: str, keywords: Iterable[str]) -> int:
    normalised_text = _normalise(text)
    return sum(1 for keyword in keywords if _normalise(keyword) in normalised_text)


def filter_articles_by_topic_keywords(
    articles: List[Dict[str, Any]],
    topic_keywords: Dict[str, List[str]],
    max_per_topic: int,
    topic_limits: Dict[str, int] | None = None,
) -> List[Dict[str, Any]]:
    """Keep keyword-matched articles per topic, ranked by keyword hit count.

    ``topic_limits`` overrides ``max_per_topic`` for specific topics.
    """
    by_topic: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for article in articles:
        topic = str(article.get("topic", ""))
        keywords = topic_keywords.get(topic, [])
        score = keyword_hit_count(article.get("title", ""), keywords)
        if score > 0:
            by_topic[topic].append({**article, "_keyword_score": score})

    filtered: List[Dict[str, Any]] = []
    for topic in topic_keywords.keys():
        limit = topic_limits.get(topic, max_per_topic) if topic_limits else max_per_topic
        ranked = sorted(
            by_topic.get(topic, []),
            key=lambda item: item.get("_keyword_score", 0),
            reverse=True,
        )[:limit]
        for item in ranked:
            item.pop("_keyword_score", None)
            filtered.append(item)

    return filtered


def filter_articles_by_keywords(
    articles: List[Dict[str, Any]],
    keywords: List[str],
    max_items: int,
) -> List[Dict[str, Any]]:
    """Keep top keyword-matched articles from a flat article list."""
    ranked = []
    for article in articles:
        score = keyword_hit_count(article.get("title", ""), keywords)
        if score > 0:
            ranked.append({**article, "_keyword_score": score})

    ranked.sort(key=lambda item: item.get("_keyword_score", 0), reverse=True)
    selected = ranked[:max_items]
    for item in selected:
        item.pop("_keyword_score", None)
    return selected
