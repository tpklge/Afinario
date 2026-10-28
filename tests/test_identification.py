import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from afinario.cancellation import AnalysisCancelled, run_cancellable
from afinario.config import Settings
from afinario.domain import ProviderResult, RecordingCandidate, Status
from afinario.identification import IdentificationService, RecognitionOptions
from afinario.inventory import read_track
from afinario.provider_cache import ProviderCache
from afinario.resolver import DecisionStatus

FIXTURE = Path(__file__).parent / "fixtures" / "tone.mp3"
MBID = "4efa6991-a931-4212-95a7-8aee506ae491"


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "wrong name.mp3"
    shutil.copyfile(FIXTURE, path)
    return path


@pytest.fixture
def services(monkeypatch):
    calls = {"fingerprint": 0, "acoustid": 0, "shazam": 0, "musicbrainz": 0}

    def fingerprint(*_, **__):
        calls["fingerprint"] += 1
        return "fingerprint never stored", 0.4

    def lookup(*_):
        calls["acoustid"] += 1
        return ProviderResult(
            "acoustid",
            Status.OK,
            "test",
            (
                RecordingCandidate(
                    "acoustid",
                    "id",
                    "True title",
                    "True artist",
                    0.4,
                    score=0.95,
                    recording_id=MBID,
                ),
            ),
        )

    def shazam(*_):
        calls["shazam"] += 1
        return ProviderResult(
            "shazamio",
            Status.OK,
            "test",
            (RecordingCandidate("shazamio", "id", "True title", "True artist"),),
        )

    def metadata(*_):
        calls["musicbrainz"] += 1
        return ProviderResult(
            "musicbrainz",
            Status.OK,
            "test",
            (
                RecordingCandidate(
                    "musicbrainz", MBID, "True title", "True artist", recording_id=MBID
                ),
            ),
        )

    monkeypatch.setattr("afinario.identification.fingerprint", fingerprint)
    monkeypatch.setattr("afinario.identification.AcoustID.lookup", lookup)
    monkeypatch.setattr("afinario.identification.IdentificationService._shazam", shazam)
    monkeypatch.setattr("afinario.identification.MusicBrainz.recording", metadata)
    return calls


def test_service_identifies_by_audio_and_reuses_cache(source, transport_factory, services):
    record = read_track(source)
    before = source.read_bytes()
    transport = transport_factory(lambda _: pytest.fail("Unexpected network"))
    cache = ProviderCache()
    service = IdentificationService(Settings(acoustid_key="SECRET"), transport, cache)
    options = RecognitionOptions(shazamio=True)
    first = service.identify(record, options)
    assert first.decision.status == DecisionStatus.AGREEMENT
    assert first.decision.artist == "True artist"
    assert first.decision.title != record.tags.title[0]
    second = service.identify(record, options)
    assert second.decision.status == DecisionStatus.AGREEMENT
    assert all(result.cached for result in second.results)
    assert services == {"fingerprint": 1, "acoustid": 1, "shazam": 1, "musicbrainz": 1}
    assert source.read_bytes() == before
    assert "SECRET" not in str(first.summary())
    assert "fingerprint never stored" not in str(first.summary())


def test_external_change_invalidates_before_query(source, transport_factory, services):
    record = read_track(source)
    with source.open("ab") as stream:
        stream.write(b"changed")
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), ProviderCache()
    )
    assert service.identify(record, RecognitionOptions()).decision.status == DecisionStatus.CHANGED
    assert services["acoustid"] == 0


def test_external_change_during_query_discards_proposal(
    source, transport_factory, services, monkeypatch
):
    record = read_track(source)

    def change(*_):
        with source.open("ab") as stream:
            stream.write(b"changed")
        return ProviderResult("shazamio", Status.NOT_FOUND, "test")

    monkeypatch.setattr("afinario.identification.IdentificationService._shazam", change)
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), ProviderCache()
    )
    result = service.identify(record, RecognitionOptions(shazamio=True))
    assert result.decision.status == DecisionStatus.CHANGED
    assert result.decision.proposed_fields == ()


def test_missing_key_can_still_use_authorized_shazam(source, transport_factory, services):
    service = IdentificationService(Settings(), transport_factory(lambda _: None), ProviderCache())
    result = service.identify(read_track(source), RecognitionOptions(shazamio=True))
    assert result.results[0].status == Status.BLOCKED
    assert result.decision.status == DecisionStatus.INCOMPLETE
    assert result.decision.artist == "True artist"


def test_disabled_shazam_is_never_called(source, transport_factory, services):
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), ProviderCache()
    )
    service.identify(read_track(source), RecognitionOptions())
    assert services["shazam"] == 0


def test_refresh_requeries_successful_providers(source, transport_factory, services):
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), ProviderCache()
    )
    record = read_track(source)
    service.identify(record, RecognitionOptions(shazamio=True))
    service.identify(record, RecognitionOptions(shazamio=True, refresh=True))
    assert services == {"fingerprint": 2, "acoustid": 2, "shazam": 2, "musicbrainz": 2}


def test_cached_results_remain_available_without_credentials(source, transport_factory, services):
    transport = transport_factory(lambda _: pytest.fail("Unexpected network"))
    cache = ProviderCache()
    record = read_track(source)
    IdentificationService(Settings(acoustid_key="key"), transport, cache).identify(
        record, RecognitionOptions(shazamio=True)
    )
    outcome = IdentificationService(Settings(), transport, cache).identify(
        record, RecognitionOptions(shazamio=True)
    )
    assert outcome.decision.status == DecisionStatus.AGREEMENT
    assert all(result.cached for result in outcome.results)
    assert services["acoustid"] == 1


def test_cancel_between_providers_preserves_no_false_success(
    source, transport_factory, services, monkeypatch
):
    stop = threading.Event()

    def cancel(*_):
        stop.set()
        return ProviderResult("acoustid", Status.NOT_FOUND, "test")

    monkeypatch.setattr("afinario.identification.AcoustID.lookup", cancel)
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), ProviderCache(), stop
    )
    with pytest.raises(AnalysisCancelled):
        service.identify(read_track(source), RecognitionOptions(shazamio=True))
    # A call already started in parallel may complete before cancellation.
    assert stop.is_set()


def test_cancellation_kills_local_subprocess():
    stop = threading.Event()
    timer = threading.Timer(0.2, stop.set)
    timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(AnalysisCancelled):
            run_cancellable(
                [sys.executable, "-c", "import time; time.sleep(30)"], timeout=10, cancelled=stop
            )
    finally:
        timer.cancel()
    assert time.monotonic() - start < 5


def test_subprocess_timeout_is_bounded():
    with pytest.raises(subprocess.TimeoutExpired):
        run_cancellable(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1,
            cancelled=threading.Event(),
        )


def test_recognizers_run_concurrently(source, transport_factory, services, monkeypatch):
    from afinario.identification import AcoustID

    rendezvous = threading.Barrier(2)
    original_lookup = AcoustID.lookup
    original_shazam = IdentificationService._shazam

    def lookup(*args):
        rendezvous.wait(timeout=2)
        return original_lookup(*args)

    def shazam(*args):
        rendezvous.wait(timeout=2)
        return original_shazam(*args)

    monkeypatch.setattr(AcoustID, "lookup", lookup)
    monkeypatch.setattr(IdentificationService, "_shazam", shazam)
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), ProviderCache()
    )
    assert service.identify(
        read_track(source), RecognitionOptions(shazamio=True)
    ).decision.status == (DecisionStatus.AGREEMENT)


def test_parallel_duplicates_share_cached_queries_and_sqlite(
    source, tmp_path, transport_factory, services
):
    from concurrent.futures import ThreadPoolExecutor

    cache = ProviderCache(tmp_path / "cache.sqlite3")
    service = IdentificationService(
        Settings(acoustid_key="key"), transport_factory(lambda _: None), cache
    )
    records = [read_track(source), read_track(source)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda record: service.identify(record, RecognitionOptions(shazamio=True)), records
            )
        )
    assert all(result.decision.status == DecisionStatus.AGREEMENT for result in results)
    assert services["acoustid"] == services["musicbrainz"] == services["shazam"] == 1
    cache.close()
