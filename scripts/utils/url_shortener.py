"""URL shortener using the is.gd free API.

The is.gd API is tried first, followed by CleanURI.  Both require no API key;
the original URL is returned only when both providers fail, so shortening can
never break the news digest.
"""

import sys

import requests

from .retry_utils import call_with_retry

TIMEOUT = 10
ISGD_API = "https://is.gd/create.php"
CLEANURI_API = "https://cleanuri.com/api/v1/shorten"


def _shorten_isgd(url: str) -> str:
    response = requests.get(
        ISGD_API,
        params={"format": "simple", "url": url},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    shortened = response.text.strip()
    if not shortened.startswith("http"):
        raise ValueError(f"unexpected is.gd response: {shortened[:120]}")
    return shortened


def _shorten_cleanuri(url: str) -> str:
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
    """Shorten *url*, trying is.gd then CleanURI, or return the original URL."""
    for provider, operation in (("is.gd", _shorten_isgd), ("CleanURI", _shorten_cleanuri)):
        try:
            return call_with_retry(
                lambda operation=operation: operation(url),
                resource_name=f"{provider} API",
                retry_exceptions=(requests.RequestException, ValueError, KeyError),
            )
        except Exception as exc:
            print(f"Warning: {provider} could not shorten URL: {exc}", file=sys.stderr)
    return url


def shorten_urls_in_articles(articles: list, url_key: str = "link") -> list:
    """Return a new list with every article's *url_key* shortened."""
    result = []
    for article in articles:
        if article.get(url_key):
            article = {**article, url_key: shorten_url(article[url_key])}
        result.append(article)
    return result
