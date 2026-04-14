"""Retry decorator with exponential backoff."""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable

import structlog

logger = structlog.get_logger()


def retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator that retries an async function on specified exceptions.

    Uses exponential backoff: wait = backoff_base ** attempt seconds.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable as e:
                    last_exception = e
                    if attempt < max_attempts:
                        wait = backoff_base**attempt
                        logger.warning(
                            "retry_attempt",
                            function=func.__name__,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            wait_seconds=wait,
                            error=str(e),
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "retry_exhausted",
                            function=func.__name__,
                            attempts=max_attempts,
                            error=str(e),
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
