from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from afinario.domain import Status
from afinario.transport import ProviderError, Transport


@pytest.mark.parametrize(
    "code,status",
    [
        (404, Status.NOT_FOUND),
        (401, Status.AUTH),
        (403, Status.AUTH),
        (429, Status.RATE_LIMIT),
        (503, Status.UNAVAILABLE),
        (400, Status.INVALID),
        (302, Status.INVALID),
    ],
)
def test_http_categories(transport_factory, code, status):
    transport = transport_factory(lambda _: httpx.Response(code, json={}))
    with pytest.raises(ProviderError) as error:
        transport.json("test", "GET", "https://example.test")
    assert error.value.status == status
    assert error.value.attempts == 1


def test_transient_retry_and_shared_cooldown(transport_factory):
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "2"})
            if len(calls) == 1
            else (httpx.Response(200, json={"ok": True}))
        )

    transport = transport_factory(handler, attempts=2)
    data, attempts = transport.json("test", "GET", "https://example.test")
    assert data == {"ok": True}
    assert attempts == 2
    assert "test" in transport._next


def test_long_retry_after_does_not_retry_early(transport_factory):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    transport = transport_factory(handler, attempts=3)
    with pytest.raises(ProviderError) as error:
        transport.json("test", "GET", "https://example.test")
    assert error.value.status == Status.RATE_LIMIT
    assert len(calls) == 1


def test_auth_failure_suspends_provider(transport_factory):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    transport = transport_factory(handler, attempts=3)
    for _ in range(2):
        with pytest.raises(ProviderError):
            transport.json("test", "GET", "https://example.test")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>error</html>"),
        httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{"),
        httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"x" * 2_000_001),
    ],
)
def test_invalid_and_oversized_responses(transport_factory, response):
    transport = transport_factory(lambda _: response)
    with pytest.raises(ProviderError) as error:
        transport.json("test", "GET", "https://example.test")
    assert error.value.status == Status.INVALID


def test_network_exception_is_sanitized(transport_factory):
    def handler(request):
        raise httpx.ConnectError("SECRET appears in upstream exception", request=request)

    transport = transport_factory(handler, attempts=2)
    with pytest.raises(ProviderError) as error:
        transport.json("test", "GET", "https://example.test")
    assert error.value.status == Status.NETWORK
    assert error.value.attempts == 2
    assert "SECRET" not in str(error.value)


def test_retry_after_date_and_invalid():
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=30))
    assert 28 <= Transport.retry_after(date) <= 31
    assert Transport.retry_after("invalid") == 1
    assert Transport.retry_after("-1") == 0


def test_cancelled_transport_never_sends_request():
    import threading

    from afinario.cancellation import AnalysisCancelled
    from afinario.config import Settings

    stop = threading.Event()
    stop.set()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected HTTP"))
    ) as client:
        transport = Transport(Settings(), client, cancelled=stop)
        with pytest.raises(AnalysisCancelled):
            transport.json("test", "GET", "https://example.test")
