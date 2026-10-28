import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from afinario.cancellation import AnalysisCancelled
from afinario.config import Settings
from afinario.domain import Status
from afinario.transport import ProviderError, Transport


def test_independent_providers_overlap_instead_of_holding_global_lock():
    barrier = threading.Barrier(2)

    def handler(_):
        barrier.wait(timeout=2)
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(Settings(), client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(transport.json, provider, "GET", "https://example.test")
                for provider in ("acoustid", "musicbrainz")
            ]
            assert all(future.result(timeout=3)[0] == {"ok": True} for future in futures)


def test_acoustid_requests_share_concurrency_and_start_interval():
    state_lock = threading.Lock()
    active, peak = 0, 0
    starts = []

    def handler(_):
        nonlocal active, peak
        with state_lock:
            starts.append(time.monotonic())
            active += 1
            peak = max(peak, active)
        threading.Event().wait(0.03)
        with state_lock:
            active -= 1
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(Settings(), client)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(transport.json, "acoustid", "GET", "https://example.test")
                for _ in range(3)
            ]
            for future in futures:
                future.result(timeout=4)
    assert peak == 1
    assert all(b - a >= 0.34 for a, b in zip(starts, starts[1:], strict=False))


def test_shazam_wait_does_not_block_other_service_and_can_cancel():
    waiting = threading.Event()

    class StopEvent(threading.Event):
        def wait(self, timeout=None):
            waiting.set()
            return super().wait(timeout)

    stop = StopEvent()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        transport = Transport(Settings(), client, stop)
        transport._next["shazamio"] = time.monotonic() + 30
        with ThreadPoolExecutor(max_workers=2) as pool:
            paused = pool.submit(transport.json, "shazamio", "GET", "https://example.test")
            try:
                assert waiting.wait(2)
                other = pool.submit(transport.json, "acoustid", "GET", "https://example.test")
                assert other.result(timeout=1)[0] == {}
            finally:
                stop.set()
            with pytest.raises(AnalysisCancelled):
                paused.result(timeout=2)


def test_rate_limit_cooldown_does_not_extend_for_every_skipped_file(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("afinario.transport.time.monotonic", lambda: now[0])
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        transport = Transport(Settings(), client)
        transport.record_failure("shazamio", Status.RATE_LIMIT)
        assert transport._cooldowns["shazamio"][0] == 60
        now[0] = 10
        with pytest.raises(ProviderError) as error:
            transport.before_call("shazamio")
        transport.record_failure("shazamio", error.value.status, error.value.retry_after_seconds)
        assert transport._cooldowns["shazamio"][0] == 60
        now[0] = 61
        transport.record_failure("shazamio", Status.RATE_LIMIT)
        assert transport._cooldowns["shazamio"][0] == 181


def test_paid_provider_allows_bounded_parallel_requests():
    barrier = threading.Barrier(2)

    def handler(_):
        barrier.wait(timeout=2)
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(Settings(analysis_workers=2), client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(transport.json, "audd", "GET", "https://example.test") for _ in range(2)
            ]
            for future in futures:
                assert future.result(timeout=3)[0] == {}
