"""Retry decorator using tenacity with exponential backoff."""
from __future__ import annotations

from typing import Any, Callable, Type

from loguru import logger
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def with_retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    reraise: bool = True,
    exception_types: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator factory for retrying functions with exponential backoff.

    Args:
        max_attempts:    Total attempts (including the first try).
        backoff_factor:  Multiplier applied to wait between retries.
        min_wait:        Minimum seconds to wait between retries.
        max_wait:        Maximum seconds to wait between retries.
        reraise:         If True, re-raise the last exception after all attempts fail.
        exception_types: Tuple of exception classes that trigger a retry.
    """
    def decorator(fn: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=backoff_factor, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(exception_types),
            reraise=reraise,
        )
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator


def log_retry_attempt(retry_state: Any) -> None:
    """Tenacity before-sleep callback that logs retry attempts."""
    logger.warning(
        f"Retry {retry_state.attempt_number} for {retry_state.fn.__name__} "
        f"after error: {retry_state.outcome.exception()}"
    )
