"""Helper for sending messages to a Discord webhook."""

import json
import requests

from .retry_utils import call_with_retry


def send_message(webhook_url: str, text: str) -> None:
    """Send a plain-text message to a Discord webhook.

    Args:
        webhook_url: The incoming webhook URL for the Discord channel.
        text: Message body.

    Raises:
        requests.HTTPError: If the request fails.
    """
    payload = {"content": text}
    def _post_webhook() -> None:
        response = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=15,
        )
        response.raise_for_status()

    call_with_retry(
        _post_webhook,
        resource_name="Discord webhook",
        retry_exceptions=(requests.RequestException,),
    )
