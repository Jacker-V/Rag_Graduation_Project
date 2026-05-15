import os
import random
import time
import threading
from contextlib import contextmanager
from typing import Callable, TypeVar


T = TypeVar("T")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def is_transient_llm_error(exc: Exception) -> bool:
    msg = str(exc).lower()

    transient_markers = [
        "503",
        "unavailable",
        "overloaded",
        "temporarily",
        "try again later",
        "rate limit",
        "ratelimit",
        "too many requests",
        "429",
        "resourceexhausted",
        "deadline exceeded",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "service unavailable",
        "internal error",
        "server error",
    ]

    return any(marker in msg for marker in transient_markers)


class _GlobalLimiter:
    def __init__(self) -> None:
        max_concurrent = _env_int("LLM_MAX_CONCURRENT_REQUESTS", 2)
        if max_concurrent < 1:
            max_concurrent = 1
        self._sem = threading.BoundedSemaphore(max_concurrent)

    @contextmanager
    def slot(self):
        self._sem.acquire()
        try:
            yield
        finally:
            self._sem.release()


_global_limiter: _GlobalLimiter | None = None


def global_limiter() -> _GlobalLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = _GlobalLimiter()
    return _global_limiter


def run_with_retries(operation: Callable[[], T]) -> T:
    max_retries = _env_int("LLM_MAX_RETRIES", 3)
    base_delay = _env_float("LLM_RETRY_BASE_SECONDS", 1.0)
    max_delay = _env_float("LLM_RETRY_MAX_SECONDS", 10.0)

    attempt = 0
    while True:
        try:
            with global_limiter().slot():
                return operation()
        except Exception as exc:
            attempt += 1
            if attempt > max_retries or not is_transient_llm_error(exc):
                raise

            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = delay * random.uniform(0.85, 1.25)
            time.sleep(delay)
