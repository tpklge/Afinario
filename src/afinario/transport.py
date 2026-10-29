"""HTTP compartilhado com filas independentes e uma chamada ativa por provedor."""

import json
import math
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from afinario.cancellation import AnalysisCancelled, check_cancelled
from afinario.config import Settings
from afinario.domain import Status


class ProviderError(Exception):
    def __init__(
        self, status: Status, message: str, attempts: int = 0, retry_after_seconds: float = 0
    ):
        super().__init__(message)
        self.status, self.attempts = status, attempts
        self.retry_after_seconds = retry_after_seconds


class Transport:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        cancelled: threading.Event | None = None,
    ):
        self.settings, self.cancelled = settings, cancelled
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds, connect=10),
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._lock = threading.RLock()
        self._next: dict[str, float] = {}
        self._auth_blocked: set[str] = set()
        self._gates: dict[str, threading.BoundedSemaphore] = {}
        self._cooldowns: dict[str, tuple[float, Status]] = {}
        self._penalties: dict[str, int] = {}
        # Local scheduling choices, not a statement of Shazam's undocumented quota.
        self._intervals = {
            "acoustid": 0.35,
            "musicbrainz": 1.05,
            "shazamio": settings.shazam_interval_seconds,
            "audd": 0,
            "lrclib": 0.5,
            "lyrics.ovh": 1,
        }

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _raise_paused(self, provider: str) -> None:
        check_cancelled(self.cancelled)
        with self._lock:
            if provider in self._auth_blocked:
                raise ProviderError(Status.AUTH, "Credencial inválida; provedor suspenso.")
            until, status = self._cooldowns.get(provider, (0, Status.RATE_LIMIT))
            remaining = until - time.monotonic()
            if remaining > 0:
                raise ProviderError(
                    status,
                    "Fonte em pausa temporária; tente novamente depois.",
                    retry_after_seconds=remaining,
                )

    def _wait(self, provider: str) -> None:
        while True:
            self._raise_paused(provider)
            with self._lock:
                target = self._next.get(provider, 0)
                delay = max(0, target - time.monotonic())
            # Never sleep while holding the global state lock: other providers proceed.
            if delay:
                if self.cancelled is None:
                    time.sleep(delay)
                elif self.cancelled.wait(delay):
                    raise AnalysisCancelled
            self._raise_paused(provider)
            with self._lock:
                if self._next.get(provider, 0) > target:
                    continue
                self._next[provider] = max(target, time.monotonic()) + self._intervals.get(
                    provider, 1
                )
                return

    def before_call(self, provider: str) -> None:
        self._wait(provider)

    @contextmanager
    def provider_slot(self, provider: str):
        with self._lock:
            gate = self._gates.setdefault(
                provider,
                threading.BoundedSemaphore(
                    self.settings.analysis_workers if provider == "audd" else 1
                ),
            )
        while True:
            self._raise_paused(provider)
            if gate.acquire(timeout=0.1):
                break
        try:
            self.before_call(provider)
            yield
        finally:
            gate.release()

    def record_failure(self, provider: str, status: Status, retry_after_seconds: float = 0) -> None:
        with self._lock:
            if status == Status.AUTH:
                self._auth_blocked.add(provider)
            if status in (Status.RATE_LIMIT, Status.UNAVAILABLE):
                now = time.monotonic()
                until, _ = self._cooldowns.get(provider, (0, status))
                if until <= now:
                    count = min(5, self._penalties.get(provider, 0) + 1)
                    self._penalties[provider] = count
                    until = now + min(900, 60 * 2 ** (count - 1))
                until = max(until, now + retry_after_seconds)
                self._cooldowns[provider] = (until, status)
                self._next[provider] = max(self._next.get(provider, 0), until)

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._penalties.pop(provider, None)

    def _defer(self, provider: str, seconds: float) -> None:
        with self._lock:
            self._next[provider] = max(self._next.get(provider, 0), time.monotonic() + seconds)

    @staticmethod
    def retry_after(value: str | None) -> float:
        if not value:
            return 1
        try:
            seconds = float(value)
            return max(0, seconds) if math.isfinite(seconds) else 60
        except ValueError:
            try:
                target = parsedate_to_datetime(value)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                return max(0, (target - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return 1

    @contextmanager
    def _request_slot(self, provider: str, before_send: Callable[[], None] | None):
        with self.provider_slot(provider):
            if before_send is not None:
                before_send()
            yield

    def _request(
        self,
        provider: str,
        method: str,
        url: str,
        attempt: int,
        before_send: Callable[[], None] | None = None,
        application_error_statuses: tuple[int, ...] = (),
        **kwargs: Any,
    ):
        with (
            self._request_slot(provider, before_send),
            self.client.stream(method, url, **kwargs) as response,
        ):
            code = response.status_code
            if code == 404:
                raise ProviderError(Status.NOT_FOUND, "Nenhum resultado encontrado.", attempt)
            if code in (401, 403):
                self.record_failure(provider, Status.AUTH)
                raise ProviderError(Status.AUTH, "Credencial ou acesso recusado.", attempt)
            if code == 429 or code >= 500:
                status = Status.RATE_LIMIT if code == 429 else Status.UNAVAILABLE
                retry_header = response.headers.get("Retry-After")
                delay = max(2 ** (attempt - 1), self.retry_after(retry_header))
                if code == 429 and retry_header is None:
                    delay = max(60, delay)
                if attempt == self.settings.attempts or delay > 30:
                    self.record_failure(provider, status, delay)
                else:
                    self._defer(provider, delay)
                raise ProviderError(
                    status,
                    "Fonte temporariamente indisponível.",
                    attempt,
                    retry_after_seconds=delay,
                )
            if not 200 <= code < 300 and code not in application_error_statuses:
                raise ProviderError(
                    Status.INVALID, f"Resposta HTTP inesperada (HTTP {code}).", attempt
                )
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise ProviderError(Status.INVALID, "Resposta não é JSON.", attempt)
            body = bytearray()
            for chunk in response.iter_bytes():
                check_cancelled(self.cancelled)
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ProviderError(Status.INVALID, "Resposta excede o limite.", attempt)
            try:
                data = json.loads(body)
            except (ValueError, UnicodeError) as exc:
                raise ProviderError(Status.INVALID, "JSON inválido.", attempt) from exc
            if not 200 <= code < 300 and (
                not isinstance(data, dict) or data.get("status") != "error"
            ):
                raise ProviderError(
                    Status.INVALID, f"Resposta HTTP inesperada (HTTP {code}).", attempt
                )
            return data

    def json(
        self,
        provider: str,
        method: str,
        url: str,
        *,
        max_attempts: int | None = None,
        before_send: Callable[[], None] | None = None,
        application_error_statuses: tuple[int, ...] = (),
        **kwargs: Any,
    ) -> tuple[Any, int]:
        limit = self.settings.attempts if max_attempts is None else max_attempts
        if type(limit) is not int or not 1 <= limit <= 3:
            raise ValueError("Número de tentativas inválido.")
        for attempt in range(1, limit + 1):
            try:
                return self._request(
                    provider,
                    method,
                    url,
                    attempt,
                    before_send,
                    application_error_statuses=application_error_statuses,
                    **kwargs,
                ), attempt
            except ProviderError as exc:
                if (
                    exc.status not in (Status.RATE_LIMIT, Status.UNAVAILABLE)
                    or attempt == limit
                    or exc.retry_after_seconds > 30
                    or exc.attempts == 0
                ):
                    raise
            except httpx.TransportError:
                if attempt == limit:
                    raise ProviderError(
                        Status.NETWORK, "Falha de rede ou timeout.", attempt
                    ) from None
                self._defer(provider, 2 ** (attempt - 1))
        raise AssertionError("unreachable")
