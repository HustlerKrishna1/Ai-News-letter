"""Exponential-backoff retry decorator for flaky network calls.

Only retries transient errors (network, timeouts, 5xx). Non-transient
failures (4xx, malformed JSON, AttributeError) bubble immediately so bugs
don't hide behind retries.
"""
from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable, Tuple, Type

import requests

log = logging.getLogger(__name__)

DEFAULT_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, requests.HTTPError):
        return False
    resp = getattr(exc, "response", None)
    if resp is None:
        return True
    return resp.status_code >= 500 or resp.status_code in {408, 425, 429}


def with_retry(
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    exceptions: Tuple[Type[BaseException], ...] = DEFAULT_EXCEPTIONS,
) -> Callable:
    """Retry a function on transient errors with exponential backoff + jitter."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == attempts:
                        break
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay += random.uniform(0, delay * 0.25)
                    log.warning(
                        "%s attempt %d/%d failed (%s); retrying in %.1fs",
                        func.__name__, attempt, attempts, exc, delay,
                    )
                    time.sleep(delay)
                except requests.HTTPError as exc:
                    if not _is_retryable_http_error(exc) or attempt == attempts:
                        raise
                    last_exc = exc
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay += random.uniform(0, delay * 0.25)
                    log.warning(
                        "%s attempt %d/%d got %s; retrying in %.1fs",
                        func.__name__, attempt, attempts,
                        exc.response.status_code if exc.response else "HTTPError",
                        delay,
                    )
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator
