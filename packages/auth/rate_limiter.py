from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import threading
from typing import Callable

from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Check if the request for the given key is within the rate limit.
        Returns:
            (is_allowed: bool, retry_after_seconds: int)
        """
        now = datetime.now(timezone.utc).timestamp()
        window_start = now - window_seconds

        with self._lock:
            history = self._requests[key]
            # Prune expired timestamps
            valid_history = [ts for ts in history if ts > window_start]
            self._requests[key] = valid_history

            if len(valid_history) >= max_requests:
                # Oldest timestamp in window determines retry-after
                oldest_ts = valid_history[0]
                retry_after = max(1, int(oldest_ts + window_seconds - now) + 1)
                return False, retry_after

            # Record this request
            valid_history.append(now)
            return True, 0

    def reset(self):
        """Reset all rate limiter state (useful for tests)."""
        with self._lock:
            self._requests.clear()


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


def rate_limit_dependency(
    max_requests: int,
    window_seconds: int,
    key_prefix: str = "general",
    get_key: Callable[[Request], str] | None = None,
):
    """
    FastAPI dependency factory to enforce rate limiting.
    """
    def dependency(request: Request):
        if get_key is not None:
            sub_key = get_key(request)
        else:
            client_ip = request.client.host if request.client else "unknown"
            sub_key = client_ip

        rate_key = f"{key_prefix}:{sub_key}"
        allowed, retry_after = rate_limiter.check(
            key=rate_key,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
