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
        "reasoning",
        "multimodal",
        "fine-tuning",
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
        "culture",
        "performance",
        "framework",
        "architecture",
        "design",
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
    ],
    "Finance": [
        "inflation",
        "interest rate",
        "federal reserve",
        "central bank",
        "stocks",
        "bonds",
        "recession",
        "gdp",
        "unemployment",
        "earnings",
        "market",
        "tariff",
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
) -> List[Dict[str, Any]]:
    """Keep keyword-matched articles per topic, ranked by keyword hit count."""
    by_topic: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for article in articles:
        topic = str(article.get("topic", ""))
        keywords = topic_keywords.get(topic, [])
        score = keyword_hit_count(article.get("title", ""), keywords)
        if score > 0:
            by_topic[topic].append({**article, "_keyword_score": score})

    filtered: List[Dict[str, Any]] = []
    for topic in topic_keywords.keys():
        ranked = sorted(
            by_topic.get(topic, []),
            key=lambda item: item.get("_keyword_score", 0),
            reverse=True,
        )[:max_per_topic]
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
