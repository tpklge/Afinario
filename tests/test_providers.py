import json
from urllib.parse import parse_qs

import httpx
import pytest

from afinario.domain import LyricCandidate, ProviderResult, Status
from afinario.providers import AcoustID, LRCLib, LyricsOVH


def test_acoustid_http_400_key_rejection_is_reported_and_suspends_provider(transport_factory):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            400, json={"status": "error", "error": {"code": 4, "message": "PRIVATE-TOKEN"}}
        )

    provider = AcoustID(transport_factory(handler), "PRIVATE-TOKEN")
    first = provider.lookup("fingerprint", 100)
    second = provider.lookup("fingerprint", 100)
    assert first.status == second.status == Status.AUTH
    assert first.attempts == 1
    assert second.attempts == 0
    assert len(calls) == 1
    assert "chave de aplicação" in first.message
    assert "PRIVATE-TOKEN" not in str(first.summary())


def test_lrclib_normalizes_instrumental_and_synced(transport_factory):
    response = [
        {
            "id": 1,
            "trackName": "Original",
            "artistName": "Artist",
            "duration": 123,
            "plainLyrics": "Texto de teste",
            "syncedLyrics": "[00:01]Texto de teste",
            "instrumental": False,
        },
        {"id": 2, "instrumental": True},
    ]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    result = LRCLib(transport_factory(handler)).search("Artista Á", "Título")
    assert result.status == Status.OK
    assert len(result.candidates) == 2
    assert result.candidates[1].instrumental is True
    assert requests[0].url.params["artist_name"] == "Artista Á"
    assert "Texto de teste" not in json.dumps(result.summary())


def test_ovh_encodes_path_without_inventing_evidence(transport_factory):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"lyrics": "Letra de teste"})

    result = LyricsOVH(transport_factory(handler)).search("A/B", "C?D")
    assert result.status == Status.OK
    assert b"A%2FB/C%3FD" in requests[0].url.raw_path
    assert result.candidates[0].artist is None
    assert result.candidates[0].title is None
    assert result.candidates[0].duration is None


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"lyrics": ""}, Status.NOT_FOUND),
        ({"lyrics": "<html>erro</html>"}, Status.INVALID),
        ({"error": "not found"}, Status.INVALID),
        ([], Status.INVALID),
    ],
)
def test_ovh_rejects_bad_content(transport_factory, payload, status):
    result = LyricsOVH(transport_factory(lambda _: httpx.Response(200, json=payload))).search(
        "A", "B"
    )
    assert result.status == status


@pytest.mark.parametrize("payload", [{}, [{"id": "1"}], [{"id": 1, "instrumental": "yes"}]])
def test_lrclib_schema_validation(transport_factory, payload):
    result = LRCLib(transport_factory(lambda _: httpx.Response(200, json=payload))).search("A", "B")
    assert result.status == Status.INVALID


def test_acoustid_post_keeps_secret_out_of_url_and_report(transport_factory):
    def handler(request):
        assert request.method == "POST"
        assert "SECRET" not in str(request.url)
        fields = parse_qs(request.content.decode())
        assert fields["client"] == ["SECRET"]
        assert fields["duration"] == ["241"]
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "results": [
                    {
                        "id": "match-id",
                        "score": 0.92,
                        "recordings": [
                            {
                                "id": "mbid",
                                "title": "Title",
                                "duration": 241,
                                "artists": [{"name": "Artist"}],
                            },
                        ],
                    },
                ],
            },
        )

    result = AcoustID(transport_factory(handler), "SECRET").lookup("fingerprint", 241.1)
    assert result.status == Status.OK
    assert result.candidates[0].recording_id == "mbid"
    assert result.candidates[0].score == 0.92
    assert "SECRET" not in json.dumps(result.summary())
    assert "fingerprint" not in json.dumps(result.summary())


@pytest.mark.parametrize(
    "code,status",
    [(4, Status.AUTH), (5, Status.AUTH), (13, Status.RATE_LIMIT), (2, Status.INVALID)],
)
def test_acoustid_application_errors(transport_factory, code, status):
    transport = transport_factory(
        lambda _: httpx.Response(
            200,
            json={"status": "error", "error": {"code": code, "message": "SECRET"}},
        )
    )
    result = AcoustID(transport, "SECRET").lookup("fp", 100)
    assert result.status == status
    assert "SECRET" not in result.message


def test_summary_and_repr_do_not_expose_lyrics():
    candidate = LyricCandidate("test", None, "private lyric", "private synced lyric")
    result = ProviderResult("test", Status.OK, "OK", (candidate,))
    assert "private lyric" not in repr(candidate)
    assert "private lyric" not in json.dumps(result.summary())
