"""Shared retry helper for external/network resource calls."""

from __future__ import annotations

import sys
import time
from typing import Callable, TypeVar

T = TypeVar("T")

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
POST_SUCCESS_DELAY_SECONDS = 1


def call_with_retry(
    operation: Callable[[], T],
    *,
    resource_name: str,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Run *operation* with retry and pacing for external resources."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = operation()
            time.sleep(POST_SUCCESS_DELAY_SECONDS)
            return result
        except retry_exceptions as exc:
            if attempt == MAX_RETRIES:
                raise
            print(
                (
                    f"Warning: {resource_name} failed "
                    f"(attempt {attempt}/{MAX_RETRIES}): {exc}. "
                    f"Retrying in {RETRY_DELAY_SECONDS}s..."
                ),
                file=sys.stderr,
            )
            time.sleep(RETRY_DELAY_SECONDS)
