#!/usr/bin/env python3
"""Daily RSS Digest

Runs twice a day (7:30 AM VNT and 7:30 PM VNT via GitHub Actions cron).

Workflow:
1. Fetch RSS articles published in the last 24 hours from curated feeds.
2. Use OpenAI to filter relevant topics and produce a concise summary.
3. Send the digest to a Discord channel via an incoming webhook.

Required environment variables:
  OPENAI_API_KEY       – OpenAI API key
  DISCORD_WEBHOOK_URL  – Discord incoming webhook URL
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import feedparser  # type: ignore
import pytz

# Allow running as a top-level script inside the ``scripts/`` directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.discord_webhook import send_message
from utils.openai_utils import summarise_articles

VNT = pytz.timezone("Asia/Ho_Chi_Minh")

# ---------------------------------------------------------------------------
# RSS feed catalogue
# Topics: AI, Java, Developer, Finance, Commodities
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    # Artificial Intelligence
    {
        "url": "https://www.artificialintelligence-news.com/feed/",
        "topic": "AI",
    },
    {
        "url": "https://www.technologyreview.com/feed/",
        "topic": "AI",
    },
    # Java / JVM
    {
        "url": "https://www.infoq.com/feed/?topic=java",
        "topic": "Java",
    },
    # Software development
    {
        "url": "https://hnrss.org/frontpage",
        "topic": "Developer",
    },
    {
        "url": "https://dev.to/feed",
        "topic": "Developer",
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


def fetch_recent_articles(hours: int = 24) -> list:
    """Return articles published within the last *hours* hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles: list = []

    for feed_info in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries:
                pub_time = _parse_entry_time(entry)
                if pub_time is None or pub_time < cutoff:
                    continue
                articles.append(
                    {
                        "title": getattr(entry, "title", ""),
                        "link": getattr(entry, "link", ""),
                        "summary": getattr(entry, "summary", ""),
                        "published": pub_time.isoformat(),
                        "topic": feed_info["topic"],
                    }
                )
        except (OSError, ValueError) as exc:
            print(
                f"Warning: could not fetch {feed_info['url']}: {exc}",
                file=sys.stderr,
            )

    return articles


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


def format_digest_message(summary: str, now_vnt: datetime) -> str:
    """Wrap the AI summary in a Discord-friendly header."""
    timestamp = now_vnt.strftime("%d/%m/%Y %I:%M %p (VNT)")
    header = f"📰 *Daily News Digest* — {timestamp}\n{'─' * 44}\n\n"
    return header + summary


def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(1)

    now_vnt = datetime.now(VNT)
    print(f"[rss_digest] Starting at {now_vnt.strftime('%Y-%m-%d %H:%M %Z')}")

    print("[rss_digest] Fetching RSS feeds…")
    articles = fetch_recent_articles(hours=24)
    print(f"[rss_digest] {len(articles)} recent articles found.")

    if not articles:
        print("[rss_digest] No recent articles – skipping digest.")
        return

    print("[rss_digest] Summarising with OpenAI…")
    summary = summarise_articles(articles)

    message = format_digest_message(summary, now_vnt)

    print("[rss_digest] Sending to Discord…")
    send_message(webhook_url, message)
    print("[rss_digest] Done.")


if __name__ == "__main__":
    main()
