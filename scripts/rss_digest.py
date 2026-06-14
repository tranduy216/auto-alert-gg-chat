#!/usr/bin/env python3
"""Daily RSS Digest

Runs twice a day (7:30 AM VNT and 7:30 PM VNT via GitHub Actions cron).

Workflow:
1. Fetch RSS articles published in the last 24 hours from curated feeds.
2. Use Google Gemini to select the 2 most important articles per topic and
   produce a concise summary.
3. Send the digest to a Discord channel via an incoming webhook.

Required environment variables:
  GEMINI_API_KEY             – Google Gemini API key
  DISCORD_DAILY_WEBHOOK_URL  – Discord incoming webhook URL for the daily digest channel
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import feedparser  # type: ignore
import pytz
from google.genai import errors as genai_errors  # type: ignore

# Allow running as a top-level script inside the ``scripts/`` directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.article_prefilter import (
    TOPIC_KEYWORDS,
    filter_articles_by_topic_keywords,
)
from utils.discord_webhook import send_message
from utils.gemini_utils import summarise_articles
from utils.retry_utils import call_with_retry
from utils.url_shortener import shorten_urls_in_articles

VNT = pytz.timezone("Asia/Ho_Chi_Minh")

# ---------------------------------------------------------------------------
# RSS feed catalogue
# Topics: Technical Trend, AI, Java, Developer, Big Tech, Finance, Commodities
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    # Artificial Intelligence (feeds về AI + big AI companies)
    {
        "url": "https://www.technologyreview.com/feed/",
        "topic": "AI",
    },
    {
        "url": "https://blog.research.google/feed/",
        "topic": "AI",
    },
    {
        "url": "https://ai.meta.com/blog/feed/",
        "topic": "AI",
    },
    # Java / JVM
    {
        "url": "https://www.infoq.com/feed/?topic=java",
        "topic": "Java",
    },
    # Technical Trend (engineering leadership, architecture, AI tools)
    {
        "url": "https://hnrss.org/frontpage",
        "topic": "Technical Trend",
    },
    # Developer (programmer, framework, performance)
    {
        "url": "https://dev.to/feed",
        "topic": "Developer",
    },
    {
        "url": "https://github.blog/feed/",
        "topic": "Developer",
    },
    {
        "url": "https://stackoverflow.blog/feed/",
        "topic": "Developer",
    },
    # Big Tech
    {
        "url": "https://techcrunch.com/feed/",
        "topic": "Big Tech",
    },
    {
        "url": "https://www.theverge.com/rss/index.xml",
        "topic": "Big Tech",
    },
    {
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "topic": "Big Tech",
    },
    # Finance & crypto
    {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "topic": "Finance",
    },
    {
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "topic": "Finance",
    },
    # Commodities
    {
        "url": "https://oilprice.com/rss/main",
        "topic": "Commodities",
    },
    {
        "url": "https://www.kitco.com/rss/kitconews.xml",
        "topic": "Commodities",
    },
]

MAX_ARTICLES_PER_FEED = 7
MAX_ARTICLES_PER_TOPIC = 2


def fetch_recent_articles(hours: int = 24) -> list:
    """Return articles published within the last *hours* hours.

    Per feed: keep at most ``MAX_ARTICLES_PER_FEED`` newest articles.
    Across all feeds: de-duplicate by URL (first occurrence wins).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles: list = []

    for feed_info in RSS_FEEDS:
        try:
            feed = call_with_retry(
                lambda url=feed_info["url"]: feedparser.parse(url),
                resource_name=f"RSS feed {feed_info['url']}",
                retry_exceptions=(OSError, ValueError),
            )
            entries = []
            for entry in feed.entries:
                pub_time = _parse_entry_time(entry)
                if pub_time is None or pub_time < cutoff:
                    continue
                entries.append(
                    {
                        "title": getattr(entry, "title", ""),
                        "link": getattr(entry, "link", ""),
                        "published": pub_time.isoformat(),
                        "topic": feed_info["topic"],
                    }
                )
            # Keep newest N per feed
            entries.sort(key=lambda e: e["published"], reverse=True)
            articles.extend(entries[:MAX_ARTICLES_PER_FEED])
        except (OSError, ValueError) as exc:
            print(
                f"Warning: could not fetch {feed_info['url']}: {exc}",
                file=sys.stderr,
            )

    # De-duplicate by URL across all feeds
    seen_urls: set = set()
    deduped: list = []
    for a in articles:
        url = a.get("link", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(a)

    # Group by topic and cap per topic
    topic_groups: dict = defaultdict(list)
    for a in deduped:
        topic_groups[a.get("topic", "")].append(a)

    result: list = []
    for topic in TOPIC_KEYWORDS.keys():
        ranked = sorted(
            topic_groups.get(topic, []),
            key=lambda item: item.get("published", ""),
            reverse=True,
        )
        result.extend(ranked[:MAX_ARTICLES_PER_TOPIC])

    return result


def _parse_entry_time(entry) -> datetime | None:
    """Extract a timezone-aware UTC datetime from a feedparser entry."""
    import time as _time

    for attr in ("published_parsed", "updated_parsed"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                ts = _time.mktime(raw)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                pass
    return None


def format_digest_message(selected: list[dict], now_vnt: datetime, char_limit: int = 2000) -> str:
    """Format selected articles, dropping lowest-priority items if over char_limit."""
    timestamp = now_vnt.strftime("%d/%m/%Y %I:%M %p (VNT)")
    header = f"Daily News Digest — {timestamp}"

    candidates = list(selected)
    while candidates:
        lines = [header, ""]
        for item in candidates:
            lines.append(f"• {item['title']}")
            lines.append(f"  🔗 {item['url']}")
            lines.append("")
        msg = "\n".join(lines).rstrip("\n")
        if len(msg) <= char_limit:
            return msg
        candidates.pop()

    return header


def main() -> None:
    webhook_url = os.environ.get("DISCORD_DAILY_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_DAILY_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(1)

    now_vnt = datetime.now(VNT)
    print(f"[rss_digest] Starting at {now_vnt.strftime('%Y-%m-%d %H:%M %Z')}")

    print("[rss_digest] Fetching RSS feeds…")
    recent_articles = fetch_recent_articles(hours=24)
    print(f"[rss_digest] {len(recent_articles)} recent articles found.")

    articles = filter_articles_by_topic_keywords(
        recent_articles,
        TOPIC_KEYWORDS,
        max_per_topic=MAX_ARTICLES_PER_TOPIC,
        topic_limits={
            "Technical Trend": 4,
            "Developer": 3,
            "AI": 3,
            "Java": 2,
        },
    )
    print(f"[rss_digest] {len(articles)} keyword-matched articles selected.")

    if not articles:
        print("[rss_digest] No recent articles – skipping digest.")
        return

    print("[rss_digest] Shortening URLs…")
    articles = shorten_urls_in_articles(articles)

    print("[rss_digest] Summarising with Gemini…")
    try:
        selected = summarise_articles(articles)
    except genai_errors.APIError as exc:
        print(f"[rss_digest] Gemini API error – skipping digest: {exc}", file=sys.stderr)
        sys.exit(1)

    if not selected:
        print("[rss_digest] No articles selected by AI – skipping digest.")
        return

    message = format_digest_message(selected, now_vnt)

    print("[rss_digest] Sending to Discord…")
    send_message(webhook_url, message)
    print("[rss_digest] Done.")


def run() -> None:
    try:
        main()
    except Exception as exc:
        webhook_url = os.environ.get("DISCORD_DAILY_WEBHOOK_URL")
        if webhook_url:
            send_message(webhook_url, f"Cannot run due to {exc}")
        raise


if __name__ == "__main__":
    run()
