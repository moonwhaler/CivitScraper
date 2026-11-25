"""429 handling: back off without tripping the circuit breaker."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock

import pytest

from civitscraper.api.circuit_breaker import CircuitBreaker
from civitscraper.api.exceptions import RateLimitError
from civitscraper.api.request import RequestHandler


def make_handler(responses):
    handler = RequestHandler(
        base_url="https://example.invalid/api/v1",
        rate_limiter=MagicMock(),
        circuit_breaker=CircuitBreaker(failure_threshold=2, reset_timeout=60),
        max_retries=3,
        base_retry_delay=0,
    )
    handler.session = MagicMock()
    handler.session.request.side_effect = responses
    return handler


def response(status, headers=None, text="{}"):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.text = text
    return r


def test_429_bursts_do_not_open_circuit(monkeypatch):
    monkeypatch.setattr("civitscraper.api.request.time.sleep", lambda s: None)
    handler = make_handler(
        [response(429, {"Retry-After": "0"})] * 3 + [response(200, text='{"ok": 1}')]
    )

    assert handler.get("model-versions/by-hash/ABC") == '{"ok": 1}'
    assert not handler.circuit_breaker.is_open("model-versions")


def test_429_exhausted_raises_rate_limit_error(monkeypatch):
    monkeypatch.setattr("civitscraper.api.request.time.sleep", lambda s: None)
    handler = make_handler([response(429, {"Retry-After": "2"})] * 4)

    with pytest.raises(RateLimitError):
        handler.get("models/1")
    assert not handler.circuit_breaker.is_open("models")


@pytest.mark.parametrize(
    "header, expected",
    [("7", 7.0), ("1.5", 1.5), ("-3", 0.0), ("99999", 300.0), (None, 4.0), ("soon", 4.0)],
)
def test_retry_after_seconds(header, expected):
    assert RequestHandler._retry_after_seconds(header, 4.0) == expected


def test_retry_after_http_date():
    when = datetime.now(timezone.utc) + timedelta(seconds=30)
    seconds = RequestHandler._retry_after_seconds(format_datetime(when, usegmt=True), 4.0)
    assert 25 <= seconds <= 30
