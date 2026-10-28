import json
import time

import httpx
import pytest

from afinario.domain import ProviderResult, RecordingCandidate, Status
from afinario.metadata import MusicBrainz
from afinario.provider_cache import ProviderCache, cache_key

MBID = "4efa6991-a931-4212-95a7-8aee506ae491"


def test_musicbrainz_normalizes_aliases_duration_isrc_and_releases(transport_factory):
    def handler(request):
        assert str(request.url.path).endswith(MBID)
        assert request.url.params["inc"] == "artists+aliases+isrcs+releases"
        return httpx.Response(
            200,
            json={
                "id": MBID,
                "title": "Title",
                "length": 191493,
                "artist-credit": [
                    {"name": "Artist", "artist": {"name": "Artist", "aliases": [{"name": "Alias"}]}}
                ],
                "aliases": [{"name": "Other title"}],
                "isrcs": ["CODE"],
                "releases": [{"id": "release", "title": "Compilation", "date": "2020-01-01"}],
            },
        )

    result = MusicBrainz(transport_factory(handler)).recording(MBID)
    assert result.status == Status.OK
    assert result.candidates[0].duration == 191.493
    assert result.candidates[0].title_aliases == ("Other title",)
    assert result.candidates[0].artist_aliases == ("Alias",)
    assert result.candidates[0].isrcs == ("CODE",)
    assert result.releases[0].title == "Compilation"


@pytest.mark.parametrize(
    "response,status",
    [
        (httpx.Response(404), Status.NOT_FOUND),
        (httpx.Response(503), Status.UNAVAILABLE),
        (httpx.Response(200, json={"id": "wrong"}), Status.INVALID),
    ],
)
def test_musicbrainz_errors_do_not_become_matches(transport_factory, response, status):
    result = MusicBrainz(transport_factory(lambda _: response)).recording(MBID)
    assert result.status == status


def test_bad_mbid_never_leaves_computer(transport_factory):
    def fail(_):
        pytest.fail("Unexpected HTTP request")

    assert MusicBrainz(transport_factory(fail)).recording("../../other").status == Status.INVALID


def test_cache_survives_restart_without_secrets_or_fingerprint(tmp_path):
    path = tmp_path / "cache.sqlite3"
    key = cache_key("acoustid", "PRIVATE-FINGERPRINT")
    result = ProviderResult(
        "acoustid",
        Status.OK,
        "not persisted secret message",
        (RecordingCandidate("acoustid", "id", "Title", "Artist", title_aliases=("Alias",)),),
    )
    cache = ProviderCache(path)
    cache.put(key, result)
    cache.close()
    reopened = ProviderCache(path)
    try:
        value = reopened.get(key, "acoustid")
        assert value.cached
        assert value.attempts == 0
        assert value.candidates[0].title_aliases == ("Alias",)
        payload = reopened.connection.execute("SELECT payload FROM provider_cache").fetchone()[0]
        assert "PRIVATE-FINGERPRINT" not in payload
        assert "secret message" not in payload
        assert reopened.get(key, "shazamio") is None
    finally:
        reopened.close()


def test_cache_expires_and_separates_negative_and_network_failures(tmp_path, monkeypatch):
    cache = ProviderCache(tmp_path / "cache.sqlite3")
    now = time.time()
    monkeypatch.setattr("afinario.provider_cache.time.time", lambda: now)
    cache.put("negative", ProviderResult("acoustid", Status.NOT_FOUND, "none"))
    cache.put("failed", ProviderResult("acoustid", Status.NETWORK, "offline"))
    assert cache.get("failed", "acoustid") is None
    assert cache.get("negative", "acoustid").status == Status.NOT_FOUND
    monkeypatch.setattr("afinario.provider_cache.time.time", lambda: now + 86401)
    assert cache.get("negative", "acoustid") is None
    cache.close()


def test_corrupt_cache_entry_is_ignored(tmp_path):
    cache = ProviderCache(tmp_path / "cache.sqlite3")
    cache.connection.execute(
        "INSERT INTO provider_cache VALUES (?, ?, ?)",
        ("key", time.time() + 100, json.dumps({"wrong": "schema"})),
    )
    cache.connection.commit()
    assert cache.get("key", "acoustid") is None
    cache.close()


def test_unwritable_cache_uses_memory(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("existing")
    cache = ProviderCache(parent_file / "cache.sqlite3")
    assert not cache.persistent_available
    cache.put("key", ProviderResult("acoustid", Status.NOT_FOUND, "none"))
    assert cache.get("key", "acoustid").cached
