"""URL shortener using the is.gd free API.

The is.gd API (https://www.is.gd/apishorteningreference.php) requires no API
key and returns the shortened URL as plain text on success.  The original URL
is returned on failure so shortening can never break the news digest.
"""

from typing import Optional

import requests

from .retry_utils import call_with_retry

TIMEOUT = 10


def shorten_url(url: str) -> str:
    """Shorten *url* via TinyURL; return the original URL on any failure."""
    try:
        def _shorten() -> requests.Response:
            return requests.get(
                "https://is.gd/create.php",
                params={"format": "simple", "url": url},
                timeout=TIMEOUT,
            )

        response = call_with_retry(
            _shorten,
            resource_name="is.gd API",
            retry_exceptions=(requests.RequestException,),
        )
        shortened = response.text.strip()
        if shortened and shortened.startswith("http"):
            return shortened
    except Exception:
        pass
    return url


def shorten_urls_in_articles(articles: list, url_key: str = "link") -> list:
    """Return a new list with every article's *url_key* shortened."""
    result = []
    for article in articles:
        if article.get(url_key):
            article = {**article, url_key: shorten_url(article[url_key])}
        result.append(article)
    return result
