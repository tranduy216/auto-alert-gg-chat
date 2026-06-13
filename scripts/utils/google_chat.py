"""Helper for sending messages to a Google Chat webhook."""

import json
import requests


def send_message(webhook_url: str, text: str) -> None:
    """Send a plain-text message to a Google Chat webhook.

    Args:
        webhook_url: The incoming webhook URL for the Google Chat space.
        text: Message body (Google Chat markdown is supported).

    Raises:
        requests.HTTPError: If the request fails.
    """
    payload = {"text": text}
    response = requests.post(
        webhook_url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=15,
    )
    response.raise_for_status()
