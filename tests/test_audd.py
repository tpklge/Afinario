import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from afinario.audd import AudD, AudDBudget
from afinario.config import Settings
from afinario.domain import ProviderResult, RecordingCandidate, Status
from afinario.identification import IdentificationService, RecognitionOptions
from afinario.inventory import read_track
from afinario.logging_config import RedactSecrets
from afinario.provider_cache import ProviderCache, cache_key
from afinario.resolver import DecisionStatus
from afinario.transport import Transport


def test_standard_multipart_normalizes_without_inventing_duration(transport_factory):
    def handler(request):
        assert str(request.url) == "https://api.audd.io/"
        assert "TOKEN-SECRET" not in str(request.url)
        body = request.read()
        assert b"TOKEN-SECRET" in body
        assert b'filename="sample.wav"' in body
        assert b"private-source-path" not in body
        return httpx.Response(
            200,
            json={
                "status": "success",
                "result": {
                    "artist": "Artist",
                    "title": "Title",
                    "album": "Album",
                    "release_date": "2020",
                    "song_link": "https://lis.tn/example",
                    "timecode": "02:30",
                },
            },
        )

    budget = AudDBudget(1)
    result = AudD(transport_factory(handler), "TOKEN-SECRET", budget).recognize(b"synthetic WAV")
    assert result.status == Status.OK
    assert result.candidates[0].artist == "Artist"
    assert result.candidates[0].duration is None  # timecode is an offset, not track length.
    assert result.candidates[0].score is None
    assert result.releases[0].title == "Album"
    assert budget.used == 1
    assert "TOKEN-SECRET" not in json.dumps(result.summary())


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"status": "success", "result": None}, Status.NOT_FOUND),
        ({"status": "error", "error": {"error_code": 900, "error_message": "SECRET"}}, Status.AUTH),
        ({"status": "error", "error": {"error_code": 901}}, Status.AUTH),
        ({"status": "error", "error": {"error_code": 500}}, Status.AUDIO),
        ({"status": "success", "result": {"title": "missing artist"}}, Status.INVALID),
        ([], Status.INVALID),
    ],
)
def test_audd_categories(transport_factory, payload, status):
    result = AudD(
        transport_factory(lambda _: httpx.Response(200, json=payload)), "SECRET", AudDBudget(1)
    ).recognize(b"sample")
    assert result.status == status
    assert "SECRET" not in result.message


@pytest.mark.parametrize("failure", ["network", "server"])
def test_paid_requests_never_retry_and_uncertain_delivery_keeps_reservation(
    transport_factory, failure
):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ReadTimeout("SECRET", request=request)
        return httpx.Response(503)

    budget = AudDBudget(3)
    result = AudD(transport_factory(handler, attempts=3), "SECRET", budget).recognize(b"sample")
    assert result.status in (Status.NETWORK, Status.UNAVAILABLE)
    assert len(calls) == 1
    assert budget.used == 1


def test_zero_budget_sends_nothing(transport_factory):
    result = AudD(
        transport_factory(lambda _: pytest.fail("Paid HTTP without budget")), "token", AudDBudget(0)
    ).recognize(b"sample")
    assert result.status == Status.BLOCKED
    assert result.attempts == 0


def test_concurrent_requests_cannot_exceed_budget():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "success", "result": None})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = Transport(Settings(), client)
        budget = AudDBudget(2)
        adapter = AudD(transport, "token", budget)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(adapter.recognize, [b"sample"] * 8))
        assert budget.used == 2
        assert len(calls) == 2
        assert sum(result.status == Status.BLOCKED for result in results) == 6


def test_cached_audd_needs_no_token_or_paid_budget(transport_factory):
    path = Path(__file__).parent / "fixtures" / "tone.mp3"
    record = read_track(path)
    cache = ProviderCache()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache.put(
        cache_key("audd", "standard-12s-v1", digest),
        ProviderResult(
            "audd", Status.OK, "cached", (RecordingCandidate("audd", None, "Title", "Artist"),)
        ),
    )
    budget = AudDBudget(0)
    service = IdentificationService(
        Settings(), transport_factory(lambda _: pytest.fail("HTTP")), cache, audd_budget=budget
    )
    result = service.identify(record, RecognitionOptions(acoustid=False, audd=True))
    assert result.results[0].cached
    assert result.decision.status == DecisionStatus.INCOMPLETE
    assert result.decision.title == "Title"
    assert budget.used == 0


def test_audd_secret_redaction():
    record = logging.LogRecord(
        "afinario", logging.INFO, "", 0, "api_token=TOKEN-SECRET TOKEN-SECRET", (), None
    )
    RedactSecrets(("TOKEN-SECRET",)).filter(record)
    assert "TOKEN-SECRET" not in record.getMessage()
    assert "TOKEN-SECRET" not in repr(Settings(audd_token="TOKEN-SECRET"))
