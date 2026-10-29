import shutil
from dataclasses import replace
from pathlib import Path

import mutagen
import pytest
from mutagen.id3 import TIT2, TPE1
from test_operations import add_track, identify

from afinario.automation import automatic_fields
from afinario.config import Settings
from afinario.domain import LyricCandidate, ProviderResult, Status
from afinario.inventory import read_track
from afinario.library import LibraryPreferences, LibraryStore
from afinario.lyrics import (
    LyricReport,
    LyricStatus,
    candidate_key,
    embedded_lyrics,
    recognition_key,
    record_key,
)
from afinario.operations import OperationService


@pytest.fixture
def library(tmp_path):
    with LibraryStore(tmp_path / "data" / "library.sqlite3") as library:
        yield library


def correct_identity(library, tmp_path):
    record = add_track(library, tmp_path)
    audio = mutagen.File(record.path)
    audio.tags.delall("USLT")
    audio.tags.delall("SYLT")
    audio.tags.add(TIT2(encoding=3, text=["Song"]))
    audio.tags.add(TPE1(encoding=3, text=["Artist"]))
    audio.save()
    run = library.start_scan(LibraryPreferences())
    record = library.save_scan_records(run, [read_track(Path(record.path))])[0]
    library.finish_run(run, "completed", {})
    report = identify(library, record)
    return record, report


def lyric_report(record, report):
    candidate = LyricCandidate(
        "lrclib",
        "id",
        plain_text="Verified lyric text",
        synced_text="[00:00.00]Verified lyric text",
        title="Song",
        artist="Artist",
        duration=record.duration,
    )
    return LyricReport(
        record.id,
        record.path,
        record_key(record),
        recognition_key(report),
        "Artist",
        "Song",
        LyricStatus.FOUND,
        (ProviderResult("lrclib", Status.OK, "test", (candidate,)),),
        recommended_key=candidate_key(candidate),
        source_sha256=report.source_sha256,
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_consensus_tags_are_written_without_fake_manual_approvals(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    service = OperationService(library, Settings())
    plan = service.plan([record], consensus_names=False, automatic_only=True, auto_tags=True)
    assert set(plan.ready[0].automatic_fields) == {"artist", "title"}
    assert not library.load_reviews([record])[0].approved_fields
    assert service.apply(plan.id)[0]["state"] == "completed"
    current = library.load().records[0]
    assert current.tags.artist == ("Artist",) and current.tags.title == ("Song",)
    assert current.tags.album == record.tags.album
    assert not library.load_reviews([current])[0].approved_fields


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_verified_lyrics_apply_automatically_and_restore_exactly(library, tmp_path):
    record, report = correct_identity(library, tmp_path)
    before = Path(record.path).read_bytes()
    library.save_lyrics(lyric_report(record, report))
    service = OperationService(library, Settings())
    plan = service.plan([record], consensus_names=False, automatic_only=True, auto_lyrics=True)
    assert set(plan.ready[0].automatic_fields) == {"lyrics", "synced_lyrics"}
    result = service.apply(plan.id)[0]
    assert result["state"] == "completed", result
    assert any(c.plain_text == "Verified lyric text" for c in embedded_lyrics(Path(record.path)))
    assert service.restore(result["id"])["state"] == "completed"
    assert Path(record.path).read_bytes() == before


def test_lyrics_require_verified_current_tags_and_unambiguous_matching_candidate(library, tmp_path):
    record, report = correct_identity(library, tmp_path)
    lyrics = lyric_report(record, report)
    draft = library.load_reviews([record])[0]
    assert automatic_fields(record, report, draft, lyrics, apply_lyrics=True)
    assert not automatic_fields(
        replace(record, tags=replace(record.tags, title=("Wrong",))),
        report,
        draft,
        lyrics,
        apply_lyrics=True,
    )
    assert not automatic_fields(
        replace(record, tags=replace(record.tags, has_lyrics=True)),
        report,
        draft,
        lyrics,
        apply_lyrics=True,
    )
    assert not automatic_fields(
        record, replace(report, results=report.results[:1]), draft, lyrics, apply_lyrics=True
    )
    assert not automatic_fields(
        record, report, draft, replace(lyrics, status=LyricStatus.CONFLICT), apply_lyrics=True
    )
    candidate = replace(lyrics.results[0].candidates[0], title="Other version")
    mismatch = replace(lyrics, results=(replace(lyrics.results[0], candidates=(candidate,)),))
    assert not automatic_fields(record, report, draft, mismatch, apply_lyrics=True)
    assert not automatic_fields(
        record, report, draft.edit("lyrics", ("Manual lyric",)), lyrics, apply_lyrics=True
    )
