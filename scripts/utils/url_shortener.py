"""URL shortener using the CleanURI free API.

CleanURI requires no API key.  The original URL is returned when the service
fails, so shortening can never break the news digest.
"""

import sys
import time

import requests

from .retry_utils import call_with_retry

TIMEOUT = 10
CLEANURI_API = "https://cleanuri.com/api/v1/shorten"


def _shorten_cleanuri(url: str) -> str:
    # Keep requests spaced out to reduce the chance of CleanURI rate limits.
    time.sleep(0.5)
    response = requests.post(
        CLEANURI_API,
        data={"url": url},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    shortened = response.json().get("result_url", "").strip()
    if not shortened.startswith("http"):
        raise ValueError("unexpected CleanURI response")
    return shortened


def shorten_url(url: str) -> str:
    """Shorten *url* with CleanURI, or return the original URL on failure."""
    try:
        return call_with_retry(
            lambda: _shorten_cleanuri(url),
            resource_name="CleanURI API",
            retry_exceptions=(requests.RequestException, ValueError, KeyError),
        )
    except Exception as exc:
        print(f"Warning: CleanURI could not shorten URL: {exc}", file=sys.stderr)
        return url


def shorten_urls_in_articles(articles: list, url_key: str = "link") -> list:
    """Return a new list with every article's *url_key* shortened."""
    result = []
    for article in articles:
        if article.get(url_key):
            article = {**article, url_key: shorten_url(article[url_key])}
        result.append(article)
    return result
