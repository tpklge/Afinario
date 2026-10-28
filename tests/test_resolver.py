from dataclasses import replace

import pytest

from afinario.domain import ProviderResult, RecordingCandidate, Status
from afinario.resolver import DecisionStatus, normalize, resolve

MBID = "4efa6991-a931-4212-95a7-8aee506ae491"


def test_normalization_preserves_meaningful_marks_in_non_latin_scripts():
    assert normalize("ハート") != normalize("パート")
    assert normalize("Beyoncé") == normalize("Beyonce")
    assert normalize("ＡＲＴＩＳＴ") == normalize("artist")


def candidate(provider="acoustid", **kwargs):
    values = dict(
        provider=provider,
        external_id="external",
        title="Song",
        artist="Artist",
        duration=200 if provider == "acoustid" else None,
        score=0.95 if provider == "acoustid" else None,
        recording_id=MBID if provider == "acoustid" else None,
    )
    values.update(kwargs)
    return RecordingCandidate(**values)


def result(provider, *candidates, status=Status.OK):
    return ProviderResult(provider, status, "test", tuple(candidates))


def test_two_independent_sources_agree_but_never_propose_release_tags():
    decision = resolve(
        (result("acoustid", candidate()), result("shazamio", candidate("shazamio"))), 200
    )
    assert decision.status == DecisionStatus.AGREEMENT
    assert decision.artist == "Artist"
    assert decision.proposed_fields == ("artist", "title")
    assert decision.recording_id == MBID


def test_duplicate_fingerprints_for_same_recording_are_not_ambiguous():
    first = candidate()
    second = replace(first, external_id="another", score=0.94)
    decision = resolve(
        (result("acoustid", first, second), result("shazamio", candidate("shazamio"))), 200
    )
    assert decision.status == DecisionStatus.AGREEMENT


def test_known_alias_links_languages_without_arbitrary_substring_matching():
    primary = candidate(title="サムライハート(Some Like It Hot!!)", artist="SPYAIR")
    second = candidate("shazamio", title="Some Like It Hot!!", artist="SPYAIR")
    base = (result("acoustid", primary), result("shazamio", second))
    assert resolve(base, 200).status == DecisionStatus.CONFLICT
    metadata = candidate("musicbrainz", recording_id=MBID, title_aliases=("Some Like It Hot!!",))
    assert resolve((*base, result("musicbrainz", metadata)), 200).status == DecisionStatus.AGREEMENT


@pytest.mark.parametrize(
    "changes",
    [
        {"artist": "Other"},
        {"title": "Other song"},
        {"title": "Song (Live)"},
        {"title": "Song (Remix)"},
        {"title": "Song (Instrumental)"},
        {"recording_id": "another-recording"},
        {"duration": 250},
    ],
)
def test_disagreement_requires_review(changes):
    second = candidate("shazamio", **changes)
    decision = resolve((result("acoustid", candidate()), result("shazamio", second)), 200)
    assert decision.status == DecisionStatus.CONFLICT
    assert decision.proposed_fields == ()
    assert decision.title is None


def test_duration_mismatch_is_not_hidden_by_matching_names():
    decision = resolve(
        (result("acoustid", candidate(duration=220)), result("shazamio", candidate("shazamio"))),
        200,
    )
    assert decision.status == DecisionStatus.CONFLICT


def test_close_competing_recordings_and_low_score_require_review():
    other = candidate(recording_id="other", score=0.94)
    assert resolve((result("acoustid", candidate(), other),), 200).status == DecisionStatus.CONFLICT
    assert (
        resolve((result("acoustid", candidate(score=0.5)),), 200).status == DecisionStatus.CONFLICT
    )


@pytest.mark.parametrize("missing", [Status.NETWORK, Status.AUTH, Status.NOT_FOUND, Status.BLOCKED])
def test_single_success_remains_incomplete(missing):
    decision = resolve((result("acoustid", candidate()), result("shazamio", status=missing)), 200)
    assert decision.status == DecisionStatus.INCOMPLETE
    assert decision.title == "Song"


def test_musicbrainz_or_duplicate_endpoints_never_count_as_second_recognizer():
    first = result("acoustid", candidate())
    metadata = result("musicbrainz", candidate("musicbrainz", recording_id=MBID))
    assert resolve((first, metadata), 200).status == DecisionStatus.INCOMPLETE
    assert resolve((first, first), 200).status == DecisionStatus.INCOMPLETE


def test_not_found_and_failed_queries_are_distinct():
    absent = result("acoustid", status=Status.NOT_FOUND)
    assert resolve((absent,), 200).status == DecisionStatus.NO_MATCH
    assert resolve((absent, result("shazamio", status=Status.NETWORK)), 200).status == (
        DecisionStatus.PENDING
    )


def test_isrc_conflicts_are_not_ignored():
    first = candidate(isrcs=("ISRC1",))
    second = candidate("shazamio", isrcs=("ISRC2",))
    assert resolve((result("acoustid", first), result("shazamio", second)), 200).status == (
        DecisionStatus.CONFLICT
    )


def test_audd_is_independent_recognizer_and_third_source_cannot_be_ignored():
    first = result("acoustid", candidate())
    paid = result("audd", candidate("audd"))
    assert resolve((first, paid), 200).status == DecisionStatus.AGREEMENT
    third = result("audd", candidate("audd", title="Different song"))
    assert resolve((first, result("shazamio", candidate("shazamio")), third), 200).status == (
        DecisionStatus.CONFLICT
    )
