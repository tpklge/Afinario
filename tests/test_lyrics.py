import shutil
import threading
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from afinario.cancellation import AnalysisCancelled
from afinario.domain import LyricCandidate, ProviderResult, Status
from afinario.inventory import read_track
from afinario.lyrics import (
    LyricOptions,
    LyricsService,
    LyricStatus,
    embedded_lyrics,
    import_lyric,
    local_lyric,
    plain_from_lrc,
    resolve_lyrics,
)
from afinario.provider_cache import ProviderCache

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "áudio.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", path)
    return read_track(path)


def response(provider, **kwargs):
    return ProviderResult(
        provider,
        Status.OK,
        "test",
        (
            LyricCandidate(
                provider,
                "id",
                plain_text="Texto sintético\nSegunda linha",
                **kwargs,
            ),
        ),
    )


def test_full_mode_queries_both_sources_preserves_audio_and_reuses_disk_cache(
    audio,
    tmp_path,
    transport_factory,
):
    calls = []
    original = Path(audio.path).read_bytes()

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "lrclib.net":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "trackName": "Title",
                        "artistName": "Artist",
                        "duration": audio.duration,
                        "plainLyrics": "Texto sintético\nSegunda linha",
                    }
                ],
            )
        return httpx.Response(200, json={"lyrics": "Texto sintético\nSegunda linha"})

    path = tmp_path / "lyrics.sqlite3"
    cache = ProviderCache(path)
    report = LyricsService(transport_factory(handler), cache).query(audio, "Artist", "Title")
    cache.close()
    assert report.status == LyricStatus.FOUND
    assert calls == ["lrclib.net", "api.lyrics.ovh"]
    assert any("compartilhar" in reason for reason in report.reasons)
    assert report.existing
    assert report.recommended_key
    assert "Texto sintético" not in str(report.summary())
    cache = ProviderCache(path)

    def offline(_):
        pytest.fail("A valid cached query must not use HTTP")

    reused = LyricsService(transport_factory(offline), cache).query(audio, "Artist", "Title")
    cache.close()
    assert all(result.cached for result in reused.results)
    assert Path(audio.path).read_bytes() == original


@pytest.mark.parametrize("first_found, expected_calls", [(True, 1), (False, 2)])
def test_quick_mode_falls_back_only_when_needed(
    audio, transport_factory, first_found, expected_calls
):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "lrclib.net":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "trackName": "Title",
                        "artistName": "Artist",
                        "plainLyrics": "Synthetic",
                    }
                ]
                if first_found
                else [],
            )
        return httpx.Response(200, json={"lyrics": "Synthetic"})

    cache = ProviderCache()
    report = LyricsService(transport_factory(handler), cache).query(
        audio,
        "Artist",
        "Title",
        options=LyricOptions(mode="quick"),
    )
    assert report.status == LyricStatus.FOUND
    assert len(calls) == expected_calls


@pytest.mark.parametrize(
    "statuses, expected",
    [
        ((Status.NOT_FOUND, Status.NOT_FOUND), LyricStatus.ABSENT),
        ((Status.NOT_FOUND, Status.NETWORK), LyricStatus.UNAVAILABLE),
        ((Status.NETWORK, Status.AUTH), LyricStatus.UNAVAILABLE),
    ],
)
def test_absence_and_provider_failures_are_distinct(statuses, expected):
    results = [ProviderResult(str(i), status, "test") for i, status in enumerate(statuses)]
    assert resolve_lyrics(results, "A", "T", 100)[0] == expected


def test_conflicting_texts_instrumental_and_duration_mismatch_require_review():
    first = response("lrclib", artist="A", title="T", duration=100)
    different = ProviderResult(
        "lyrics.ovh",
        Status.OK,
        "ok",
        (
            LyricCandidate(
                "lyrics.ovh",
                None,
                plain_text="Uma tradução diferente",
            ),
        ),
    )
    instrumental = ProviderResult(
        "lrclib",
        Status.OK,
        "ok",
        (
            LyricCandidate(
                "lrclib",
                "instrumental",
                instrumental=True,
            ),
        ),
    )
    assert resolve_lyrics([first, different], "A", "T", 100)[0] == LyricStatus.CONFLICT
    assert resolve_lyrics([first, instrumental], "A", "T", 100)[0] == LyricStatus.CONFLICT
    assert resolve_lyrics([instrumental], "A", "T", 100)[0] == LyricStatus.INSTRUMENTAL
    assert resolve_lyrics([first], "A", "T", 200)[0] == LyricStatus.CONFLICT
    assert resolve_lyrics([first], "A", "T (live)", 100)[0] == LyricStatus.CONFLICT


def test_incompatible_search_results_are_kept_but_not_suggested():
    bad = LyricCandidate("lrclib", "bad", plain_text="Wrong", title="Other", artist="A")
    good = LyricCandidate("lrclib", "good", plain_text="Right", title="T", artist="A")
    result = ProviderResult("lrclib", Status.OK, "ok", (bad, good))
    status, assessments, reasons, selected = resolve_lyrics([result], "A", "T", 100)
    assert status == LyricStatus.FOUND
    assert [a.eligible for a in assessments] == [False, True]
    assert selected == assessments[1].key


@pytest.mark.parametrize("extension", ["mp3", "m4a", "flac", "ogg", "opus"])
def test_read_embedded_lyrics_per_format_without_changing_bytes(tmp_path, extension):
    path = tmp_path / f"audio.{extension}"
    shutil.copyfile(FIXTURES / f"tone.{extension}", path)
    original = path.read_bytes()
    assert embedded_lyrics(path)
    assert path.read_bytes() == original


def test_offline_embedded_and_local_imports_do_not_require_identification(audio, transport_factory):
    def fail(_):
        pytest.fail("Unexpected network")

    service = LyricsService(transport_factory(fail), ProviderCache())
    embedded = service.query(audio, "", "", read_only=True)
    assert embedded.existing and embedded.status == LyricStatus.FOUND
    pasted = service.query(audio, "", "", local=local_lyric("Texto local de teste"))
    assert pasted.results[0].candidates[0].provider == "local"


def test_import_utf8_utf16_lrc_and_validation(tmp_path):
    path = tmp_path / "日本語.lrc"
    path.write_text("[00:01.20]Texto sintético\n[00:02.40]続き", encoding="utf-8-sig")
    candidate = import_lyric(path)
    assert candidate.plain_text is None
    assert "[00:01.20]" in candidate.synced_text
    assert plain_from_lrc(candidate.synced_text) == "Texto sintético\n続き"
    path = tmp_path / "windows.txt"
    path.write_text("Letra de teste\r\nOutra linha", encoding="utf-16")
    assert "Letra de teste" in import_lyric(path).plain_text
    with pytest.raises(ValueError):
        local_lyric("sem tempo", synced=True)
    with pytest.raises(ValueError):
        local_lyric("\x00")
    with pytest.raises(ValueError):
        local_lyric("a" * 2_000_001)


def test_changed_source_is_rejected_and_cancellation_stops_before_http(audio, transport_factory):
    def fail(_):
        pytest.fail("Unexpected network")

    transport = transport_factory(fail)
    service = LyricsService(transport, ProviderCache())
    with pytest.raises(ValueError, match="mudou"):
        service.query(replace(audio, size=0), "A", "T")
    stop = threading.Event()
    stop.set()
    with pytest.raises(AnalysisCancelled):
        LyricsService(transport, ProviderCache(), stop).query(audio, "A", "T")


def test_disabling_public_sources_still_allows_offline_embedded_read(audio, transport_factory):
    def fail(_):
        pytest.fail("Unexpected HTTP")

    service = LyricsService(transport_factory(fail), ProviderCache())
    options = LyricOptions(lrclib=False, lyrics_ovh=False)
    with pytest.raises(ValueError, match="fonte"):
        service.query(audio, "A", "T", options=options)
    assert service.query(audio, "", "", options=options, read_only=True).existing
