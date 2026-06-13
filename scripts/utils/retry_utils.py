"""Shared retry helper for external/network resource calls."""

from __future__ import annotations

import sys
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5
POST_SUCCESS_DELAY_SECONDS = 1


def call_with_retry(
    operation: Callable[[], T],
    *,
    resource_name: str,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
    no_retry_predicate: Optional[Callable[[Exception], bool]] = None,
) -> T:
    """Run *operation* with retry and pacing for external resources.

    Args:
        operation: The callable to execute.
        resource_name: Human-readable name used in warning messages.
        retry_exceptions: Exception types that trigger a retry.
        no_retry_predicate: Optional callable that receives the caught exception
            and returns ``True`` when the error should *not* be retried (e.g. a
            permanent quota-exceeded error).  When it returns ``True`` the
            exception is re-raised immediately without further attempts.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = operation()
            time.sleep(POST_SUCCESS_DELAY_SECONDS)
            return result
        except retry_exceptions as exc:
            if attempt == MAX_RETRIES or (
                no_retry_predicate is not None and no_retry_predicate(exc)
            ):
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
