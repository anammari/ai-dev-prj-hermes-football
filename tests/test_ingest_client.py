from __future__ import annotations

import httpx
import pytest

from ingest.client import DataNotAvailable, FootballDataClient, RateLimiter, TokenBucket, UpstreamError


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_token_bucket_sustains_no_more_than_ten_requests_per_minute() -> None:
    clock = FakeClock()
    bucket = TokenBucket(clock=clock.now, sleep=clock.sleep)

    for _ in range(11):
        bucket.acquire()

    assert clock.value == pytest.approx(60)


def test_documented_quota_headers_block_until_reset() -> None:
    clock = FakeClock()
    limiter = RateLimiter(
        bucket=TokenBucket(clock=clock.now, sleep=clock.sleep),
        clock=clock.now,
    )

    assert limiter.observe({"x-requests-available-minute": "0", "X-RequestCounter-Reset": "12"})
    limiter.before_request()
    assert clock.value == pytest.approx(12)


def test_positive_upstream_quota_controls_request_spacing() -> None:
    clock = FakeClock()
    limiter = RateLimiter(
        bucket=TokenBucket(clock=clock.now, sleep=clock.sleep),
        clock=clock.now,
    )

    assert not limiter.observe({"x-requests-available-minute": "9", "X-RequestCounter-Reset": "60"})
    limiter.before_request()
    assert clock.value == pytest.approx(6)


def test_client_retries_rate_limits_and_counts_calls() -> None:
    clock = FakeClock()
    responses = iter(
        [
            httpx.Response(
                429,
                headers={"x-requests-available-minute": "0", "X-RequestCounter-Reset": "4"},
                json={"message": "rate limited"},
            ),
            httpx.Response(200, json={"matches": []}),
        ]
    )
    client = FootballDataClient(
        base_url="https://example.test",
        api_key="test-token",
        transport=httpx.MockTransport(lambda _request: next(responses)),
        limiter=RateLimiter(
            bucket=TokenBucket(clock=clock.now, sleep=clock.sleep),
            clock=clock.now,
        ),
        clock=clock.now,
        sleep=clock.sleep,
    )
    try:
        assert client.get_json("/matches") == {"matches": []}
        assert client.stats.calls_used == 2
        assert client.stats.rate_limit_hits == 1
        assert clock.value >= 4
    finally:
        client.close()


def test_forbidden_resource_is_reported_without_retries() -> None:
    client = FootballDataClient(
        base_url="https://example.test",
        api_key="test-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(403)),
    )
    try:
        with pytest.raises(DataNotAvailable):
            client.get_json("/competitions/unknown/standings")
        assert client.stats.calls_used == 1
    finally:
        client.close()


def test_non_retryable_errors_and_missing_credentials_are_explicit() -> None:
    client = FootballDataClient(
        base_url="https://example.test",
        api_key="test-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )
    try:
        with pytest.raises(UpstreamError, match="HTTP 404"):
            client.get_json("/not-found")
    finally:
        client.close()
    with pytest.raises(ValueError, match="UPSTREAM_API_KEY"):
        FootballDataClient(base_url="https://example.test", api_key="replace-with-token")
