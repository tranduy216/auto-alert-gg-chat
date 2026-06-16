"""Helper for sending messages to a Discord webhook."""

import json
from datetime import datetime, timezone, timedelta

import requests

from .retry_utils import call_with_retry

# Discord webhook content limit per message
CHAR_LIMIT = 2000

SILENT_START = 22.5  # 22:30 VNT
SILENT_END = 5.5     # 05:30 VNT


def _is_silent_hours() -> bool:
    utc = datetime.now(timezone.utc)
    vnt_hour = utc.hour + 7 + utc.minute / 60.0
    vnt_hour = vnt_hour % 24
    if SILENT_START <= vnt_hour or vnt_hour < SILENT_END:
        return True
    return False


def send_message(webhook_url: str, text: str) -> None:
    """Send a plain-text message (or split messages) to a Discord webhook.

    Discord's ``content`` field has a 2000-character limit.  If *text* exceeds
    that, it is split on newline boundaries and sent as separate messages.

    Args:
        webhook_url: The incoming webhook URL for the Discord channel.
        text: Message body.
    """
    if _is_silent_hours():
        print("[discord_webhook] Silent hours – skipping notification.")
        return
    for chunk in _chunk_text(text, CHAR_LIMIT):
        _post_chunk(webhook_url, chunk)


def _chunk_text(text: str, limit: int) -> list[str]:
    """Split *text* into *limit*-sized pieces, breaking on newlines."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        # Try to break at the last newline before the limit
        break_at = text.rfind("\n", 0, limit)
        if break_at == -1:
            break_at = limit
        chunks.append(text[:break_at])
        text = text[break_at:].lstrip("\n")
    return chunks


def _post_chunk(webhook_url: str, text: str) -> None:
    """Post a single message chunk to the webhook."""
    payload = {"content": text}

    def _post() -> None:
        response = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=15,
        )
        response.raise_for_status()

    call_with_retry(
        _post,
        resource_name="Discord webhook",
        retry_exceptions=(requests.RequestException,),
    )
