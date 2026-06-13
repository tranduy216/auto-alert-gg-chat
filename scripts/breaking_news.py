#!/usr/bin/env python3
"""Breaking-News Monitor

Runs every 2 hours via GitHub Actions cron (UTC 0,2,4,…,22) plus a special
run at 23:00 UTC (= 06:00 VNT) to flush alerts that were held during quiet
hours.

Workflow:
1. Fetch current Bitcoin price (CoinGecko free API).
2. Fetch recent articles from financial / general news RSS feeds.
3. Ask OpenAI to detect high-impact events (Bitcoin ±4%, central-bank
   decisions, conflicts, etc.).
4. If breaking news is found:
   - Quiet hours (22:00–06:00 VNT): queue alert in Firebase.
   - Otherwise: send immediately to Discord.
5. At 06:00 VNT: flush all queued alerts before the regular news check.

Required environment variables:
  OPENAI_API_KEY                  – OpenAI API key
  DISCORD_BREAKING_WEBHOOK_URL    – Discord incoming webhook URL for the breaking-news channel
  FIREBASE_SERVICE_ACCOUNT        – Firebase service-account JSON (enables queue)
"""

import os
import sys
from datetime import datetime, timezone

import feedparser  # type: ignore
import pytz
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.firebase_utils import (
    get_unsent_queued_alerts,
    mark_alert_sent,
    queue_alert,
    record_sent_alert,
    was_recently_alerted,
)
from utils.discord_webhook import send_message
from utils.openai_utils import detect_breaking_news
from utils.article_prefilter import (
    BREAKING_NEWS_KEYWORDS,
    filter_articles_by_keywords,
)

VNT = pytz.timezone("Asia/Ho_Chi_Minh")

QUIET_START = 22   # 22:00 VNT – quiet period begins
QUIET_END = 6      # 06:00 VNT – quiet period ends

# ---------------------------------------------------------------------------
# News RSS feeds
# ---------------------------------------------------------------------------
BREAKING_NEWS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://rss.cnn.com/rss/money_news_international.rss",
    "https://hnrss.org/frontpage",
]

# Maximum articles to pull from each feed (avoid huge prompts)
MAX_ARTICLES_PER_FEED = 5
MAX_ARTICLES_FOR_AI = 12


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def is_quiet_hours(vnt_time: datetime) -> bool:
    """Return True when VNT hour is inside the 22:00–06:00 quiet window."""
    hour = vnt_time.hour
    return hour >= QUIET_START or hour < QUIET_END


def is_flush_run(vnt_time: datetime) -> bool:
    """Return True when this is the 06:00 VNT queue-flush run.

    The dedicated cron at 23:00 UTC lands at exactly 06:00 VNT.
    A 30-minute window guards against minor scheduler drift.
    """
    return vnt_time.hour == QUIET_END and vnt_time.minute < 30


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def get_bitcoin_price() -> dict:
    """Fetch Bitcoin's USD price and 24-h percentage change from CoinGecko."""
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        response.raise_for_status()
        btc = response.json().get("bitcoin", {})
        return {
            "price": btc.get("usd", 0),
            "change_24h": round(btc.get("usd_24h_change", 0), 2),
        }
    except requests.RequestException as exc:
        print(f"Warning: could not fetch Bitcoin price: {exc}", file=sys.stderr)
        return {}
    except (ValueError, KeyError) as exc:
        print(f"Warning: unexpected Bitcoin API response: {exc}", file=sys.stderr)
        return {}


def fetch_news_articles() -> list:
    """Return the latest articles from all breaking-news RSS feeds."""
    articles: list = []
    for feed_url in BREAKING_NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
                articles.append(
                    {
                        "title": getattr(entry, "title", ""),
                        "link": getattr(entry, "link", ""),
                    }
                )
        except (OSError, ValueError) as exc:
            print(f"Warning: could not fetch {feed_url}: {exc}", file=sys.stderr)
    return articles


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def format_breaking_alert(alert: dict, now_vnt: datetime) -> str:
    """Return a Discord message string for one breaking-news alert."""
    timestamp = now_vnt.strftime("%d/%m/%Y %H:%M (VNT)")
    urls_lines = "\n".join(
        f"🔗 {url}" for url in alert.get("urls", []) if url
    )

    parts = [
        f"🚨 **BREAKING NEWS** — {timestamp}",
        "─" * 44,
        f"📌 **{alert.get('headline', 'Breaking News')}**",
        "",
        f"💥 **Impact:** {alert.get('impact', '')}",
        "",
        f"📋 **Summary:**\n{alert.get('summary', '')}",
    ]
    if urls_lines:
        parts += ["", urls_lines]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Queue flush
# ---------------------------------------------------------------------------

def flush_queued_alerts(webhook_url: str, now_vnt: datetime) -> None:
    """Send all held alerts that were queued during quiet hours."""
    queued = get_unsent_queued_alerts()
    if not queued:
        print("[breaking_news] No queued alerts to flush.")
        return

    print(f"[breaking_news] Flushing {len(queued)} queued alert(s)…")
    header = (
        f"📬 **Queued Alerts** (held during 22:00–06:00 VNT) "
        f"— {now_vnt.strftime('%d/%m/%Y %H:%M (VNT)')}\n{'─' * 44}"
    )
    send_message(webhook_url, header)

    for item in queued:
        alert = item.get("alert", {})
        queued_at = item.get("queued_at_str", "earlier")
        message = format_breaking_alert(alert, now_vnt)
        send_message(webhook_url, f"*Originally detected at {queued_at}*\n{message}")
        mark_alert_sent(item["_doc_id"])
        print(f"[breaking_news] Flushed: {alert.get('headline', 'N/A')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    webhook_url = os.environ.get("DISCORD_BREAKING_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_BREAKING_WEBHOOK_URL is not set.", file=sys.stderr)
        sys.exit(1)

    now_vnt = datetime.now(VNT)
    print(
        f"[breaking_news] Starting at {now_vnt.strftime('%Y-%m-%d %H:%M %Z')}"
    )

    quiet = is_quiet_hours(now_vnt)
    flush = is_flush_run(now_vnt)
    print(f"[breaking_news] quiet_hours={quiet}  flush_run={flush}")

    # Step 1 – flush held alerts when the quiet window ends
    if flush:
        flush_queued_alerts(webhook_url, now_vnt)

    # Step 2 – gather intelligence
    print("[breaking_news] Fetching news articles…")
    raw_articles = fetch_news_articles()
    print(f"[breaking_news] {len(raw_articles)} articles fetched.")

    articles = filter_articles_by_keywords(
        raw_articles,
        BREAKING_NEWS_KEYWORDS,
        max_items=MAX_ARTICLES_FOR_AI,
    )
    print(f"[breaking_news] {len(articles)} keyword-matched articles selected.")

    print("[breaking_news] Fetching Bitcoin price…")
    bitcoin_data = get_bitcoin_price()
    if bitcoin_data:
        print(
            f"[breaking_news] BTC ${bitcoin_data.get('price', 0):,.2f} "
            f"({bitcoin_data.get('change_24h', 0):+.2f}% 24 h)"
        )

    # Step 3 – AI analysis
    print("[breaking_news] Analysing with OpenAI…")
    result = detect_breaking_news(articles, bitcoin_data)

    if not result.get("has_breaking_news"):
        print("[breaking_news] No breaking news detected.")
        return

    alerts = result.get("alerts", [])
    print(f"[breaking_news] {len(alerts)} breaking-news alert(s) detected.")

    # Step 4 – send or queue each alert
    for alert in alerts:
        headline = alert.get("headline", "N/A")

        # Skip duplicates (already alerted within the last 6 hours)
        if was_recently_alerted(alert, within_hours=6):
            print(f"[breaking_news] Skipping duplicate: {headline}")
            continue

        message = format_breaking_alert(alert, now_vnt)
        queued_at_str = now_vnt.strftime("%Y-%m-%d %H:%M %Z")

        if quiet and not flush:
            print(f"[breaking_news] Quiet hours – queuing: {headline}")
            queue_alert(alert=alert, queued_at_str=queued_at_str)
        else:
            print(f"[breaking_news] Sending alert: {headline}")
            send_message(webhook_url, message)
            record_sent_alert(alert)


if __name__ == "__main__":
    main()
