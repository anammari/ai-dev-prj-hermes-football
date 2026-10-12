"""Rate-limited client for football-data.org v4."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

MAX_REQUESTS_PER_MINUTE = 10
QUOTA_WINDOW_SECONDS = 60.0


class UpstreamError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DataNotAvailable(UpstreamError):
    """The account cannot read this upstream resource (commonly HTTP 403)."""


class ResourceNotFound(UpstreamError):
    """The upstream resource does not exist for this plan or season (HTTP 404)."""


@dataclass(slots=True)
class ClientStats:
    calls_used: int = 0
    rate_limit_hits: int = 0


class TokenBucket:
    """A one-token bucket limits sustained traffic to ten calls per minute without bursts."""

    def __init__(
        self,
        *,
        rate: float = MAX_REQUESTS_PER_MINUTE / 60,
        capacity: float = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self.rate = rate
        self.capacity = capacity
        self._clock = clock
        self._sleep = sleep
        self._tokens = capacity
        self._updated = clock()
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, self._clock() + max(0.0, seconds))

    def acquire(self) -> None:
        while True:
            now = self._clock()
            if now < self._blocked_until:
                self._sleep(self._blocked_until - now)
                continue
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            self._sleep((1 - self._tokens) / self.rate)


class RateLimiter:
    """Local token-bucket safety net plus upstream quota-header pacing."""

    def __init__(
        self,
        *,
        bucket: TokenBucket | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bucket = bucket or TokenBucket(clock=clock)
        self._clock = clock

    def before_request(self) -> None:
        self.bucket.acquire()

    def observe(self, headers: Mapping[str, str]) -> bool:
        normalized = {key.lower(): value for key, value in headers.items()}
        available = normalized.get("x-requests-available-minute")
        if available is None:
            available = normalized.get("x-requestsavailable")
        reset = normalized.get("x-requestcounter-reset")
        try:
            remaining = int(available) if available is not None else None
            reset_seconds = max(0.0, float(reset)) if reset is not None else 0.0
        except ValueError:
            return False
        if remaining is not None and remaining <= 0:
            # Without a reset header, wait out a whole quota window rather than guess a shorter one.
            self.bucket.block_for(reset_seconds if reset_seconds > 0 else QUOTA_WINDOW_SECONDS)
            return True
        if remaining is not None and reset_seconds > 0:
            self.bucket.block_for(reset_seconds / (remaining + 1))
        return False


class FootballDataClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout: float = 30,
        max_retries: int = 3,
        limiter: RateLimiter | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key or api_key.lower().startswith("replace-with-"):
            raise ValueError("UPSTREAM_API_KEY must be set to a football-data.org API token")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Auth-Token": api_key},
            timeout=timeout,
            transport=transport,
        )
        self._limiter = limiter or RateLimiter(clock=clock)
        self._sleep = sleep
        self._clock = clock
        self.max_retries = max_retries
        self.stats = ClientStats()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FootballDataClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def get_json(self, endpoint: str, params: Mapping[str, object] | None = None) -> dict[str, Any]:
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        query = dict(params or {})
        for attempt in range(self.max_retries + 1):
            self._limiter.before_request()
            self.stats.calls_used += 1
            try:
                response = self._client.get(path, params=query)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise UpstreamError(f"upstream transport failed for {path}") from exc
                self._sleep(min(2**attempt, 30))
                continue

            quota_blocked = self._limiter.observe(response.headers)
            if quota_blocked:
                self.stats.rate_limit_hits += 1
            if response.status_code == 403:
                raise DataNotAvailable(f"upstream resource unavailable: {path}", status_code=403)
            if response.status_code == 404:
                raise ResourceNotFound(f"upstream returned HTTP 404 (resource not found) for {path}", status_code=404)
            if response.status_code == 429 or response.status_code >= 500:
                if response.status_code == 429 and not quota_blocked:
                    self.stats.rate_limit_hits += 1
                if attempt == self.max_retries:
                    raise UpstreamError(
                        f"upstream returned HTTP {response.status_code} for {path}",
                        status_code=response.status_code,
                    )
                retry_after = _retry_after(response.headers.get("Retry-After"))
                self._sleep(max(retry_after, min(2**attempt, 30)))
                continue
            if response.is_error:
                raise UpstreamError(
                    f"upstream returned HTTP {response.status_code} for {path}",
                    status_code=response.status_code,
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError(f"upstream returned invalid JSON for {path}") from exc
            if not isinstance(payload, dict):
                raise UpstreamError(f"upstream returned a non-object response for {path}")
            return payload
        raise AssertionError("retry loop exited unexpectedly")


def _retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
        except ValueError:
            return 0.0
