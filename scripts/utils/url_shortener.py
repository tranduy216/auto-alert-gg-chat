"""URL handling helpers.

News messages deliberately keep the original article URLs.  Short-link
providers can be blocked or show an intermediate page in Discord.
"""

from typing import Any


def shorten_url(url: str) -> str:
    """Return the original URL; kept for backwards-compatible callers."""
    return url


def shorten_urls_in_articles(articles: list, url_key: str = "link") -> list:
    """Return a copy of articles with original URLs unchanged."""
    return [dict(article) for article in articles]
