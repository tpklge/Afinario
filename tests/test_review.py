import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from afinario.domain import (
    LyricCandidate,
    ProviderResult,
    RecordingCandidate,
    ReleaseCandidate,
    Status,
)
from afinario.identification import IdentificationReport, RecognitionOptions
from afinario.inventory import read_track
from afinario.library import LibraryError, LibraryPreferences, LibraryStore
from afinario.lyrics import LyricReport, LyricStatus, candidate_key, recognition_key, record_key
from afinario.resolver import Decision, DecisionStatus
from afinario.review import build_review, review_from_data


def prepare(tmp_path):
    path = tmp_path / "track.mp3"
    shutil.copyfile(Path(__file__).parent / "fixtures/tone.mp3", path)
    db_path = tmp_path / "library.sqlite3"
    with LibraryStore(db_path) as db:
        run = db.start_scan(LibraryPreferences(roots=(str(tmp_path),)))
        record = db.save_scan_records(run, [read_track(path)])[0]
        db.finish_run(run, "completed", {})
    return db_path, record


def recognition(record, title="Recognized title"):
    return IdentificationReport(
        record.id,
        record.path,
        Decision(
            DecisionStatus.AGREEMENT,
            "Recognized artist",
            title,
            proposed_fields=("artist", "title"),
        ),
        (
            ProviderResult(
                "musicbrainz",
                Status.OK,
                "test",
                (RecordingCandidate("musicbrainz", "id", title, "Recognized artist"),),
                releases=(ReleaseCandidate("release", "Possible album", "2025"),),
            ),
        ),
    )


def store_recognition(db, record, report):
    run = db.start_recognition([record], RecognitionOptions(), LibraryPreferences())
    db.save_identification(run, report)
    db.finish_run(run, "completed", {})


def lyric_report(record, identification=None):
    candidate = LyricCandidate("lrclib", "test", plain_text="Letra de teste nova")
    return LyricReport(
        record.id,
        record.path,
        record_key(record),
        recognition_key(identification),
        "Recognized artist",
        "Recognized title",
        LyricStatus.FOUND,
        results=(ProviderResult("lrclib", Status.OK, "test", (candidate,)),),
        existing=(LyricCandidate("embedded", "USLT", plain_text="Letra anterior"),),
        recommended_key=candidate_key(candidate),
    )


def test_fields_are_independent_release_is_not_inferred_and_edits_invalidate_approval(tmp_path):
    _, record = prepare(tmp_path)
    draft = build_review(record, recognition(record))
    assert not draft.approved_fields
    assert draft.field("album").proposed == record.tags.album
    approved = draft.approve(["title"])
    assert approved.approved_fields == ("title",)
    assert not approved.field("artist").approved
    assert not approved.field("album").approved
    edited = approved.edit("genre", ("Rock",))
    assert not edited.approved_fields
    assert edited.approved_at is None
    assert review_from_data(json.loads(json.dumps(asdict(approved)))) == approved


def test_existing_lyrics_preserved_and_replacement_requires_explicit_choice(tmp_path):
    _, record = prepare(tmp_path)
    identification = recognition(record)
    lyrics = lyric_report(record, identification)
    draft = build_review(record, identification, lyrics)
    assert draft.field("lyrics").proposed == ("Letra anterior",)
    selected = draft.select_lyrics(lyrics.results[0].candidates[0])
    with pytest.raises(ValueError, match="explicitamente"):
        selected.approve(["lyrics"])
    approved = selected.allow_replacement(True).approve(["title", "lyrics"])
    assert approved.approved_fields == ("title", "lyrics")
    assert not approved.field("album").approved
    assert not approved.allow_replacement(False).approved_fields


def test_identity_edits_clear_lyric_proposal_and_old_lyric_queries_cannot_be_approved(tmp_path):
    _, record = prepare(tmp_path)
    lyrics = lyric_report(record, recognition(record))
    draft = build_review(record, recognition(record), lyrics).allow_replacement(True)
    draft = draft.select_lyrics(lyrics.results[0].candidates[0]).approve(["lyrics"])
    changed = draft.edit("title", ("Another version",))
    assert changed.field("lyrics").proposed == changed.field("lyrics").current
    assert not changed.approved_fields
    changed = changed.select_lyrics(lyrics.results[0].candidates[0])
    with pytest.raises(ValueError, match="Atualize a busca"):
        changed.approve(["lyrics"])


def test_no_lyrics_does_not_prevent_metadata_approval_and_synced_text_needs_timestamps(tmp_path):
    _, record = prepare(tmp_path)
    draft = build_review(record, recognition(record))
    assert draft.approve(["title"]).approved_fields == ("title",)
    invalid = draft.edit("synced_lyrics", ("Not LRC",)).allow_replacement(True)
    with pytest.raises(ValueError, match="timestamps"):
        invalid.approve(["synced_lyrics"])
    with pytest.raises(ValueError):
        draft.approve(["unknown"])


def test_changed_file_blocks_even_manually_edited_approvals(tmp_path):
    _, record = prepare(tmp_path)
    report = IdentificationReport(record.id, record.path, Decision(DecisionStatus.CHANGED))
    draft = build_review(record, report).edit("title", ("Manual title",))
    with pytest.raises(ValueError, match="mudou"):
        draft.approve(["title"])


def test_lyrics_and_approved_fields_persist_with_revision_and_provenance(tmp_path):
    path, record = prepare(tmp_path)
    original = Path(record.path).read_bytes()
    with LibraryStore(path) as db:
        report = recognition(record)
        store_recognition(db, record, report)
        lyrics = lyric_report(record, report)
        db.save_lyrics(lyrics)
        draft = db.load_reviews([record])[0]
        draft = draft.select_lyrics(lyrics.results[0].candidates[0]).allow_replacement(True)
        approved = db.save_review(draft.approve(["title", "lyrics"]))
        assert approved.revision == 1
    with LibraryStore(path) as db:
        state = db.load()
        assert state.lyrics == (lyrics,)
        assert state.reviews == (approved,)
        assert state.reviews[0].field("lyrics").source == "letra:" + candidate_key(
            lyrics.results[0].candidates[0]
        )
    assert Path(record.path).read_bytes() == original


def test_concurrent_revision_and_new_recognition_invalidate_old_approval(tmp_path):
    path, record = prepare(tmp_path)
    with LibraryStore(path) as db:
        report = recognition(record)
        store_recognition(db, record, report)
        first = db.load_reviews([record])[0]
        approved = db.save_review(first.approve(["title"]))
        with pytest.raises(LibraryError, match="outra janela"):
            db.save_review(first)
        store_recognition(db, record, recognition(record, title="New version"))
        current = db.load_reviews([record])[0]
        assert current.revision == approved.revision
        assert not current.approved_fields
        assert current.field("title").proposed == ("New version",)
        with pytest.raises(LibraryError, match="proposta mudou"):
            db.save_review(approved)
        assert db.connection.execute("SELECT COUNT(*) FROM review_revisions").fetchone()[0] == 1


def test_rescan_changed_snapshot_invalidates_reviews_and_keeps_history(tmp_path):
    path, record = prepare(tmp_path)
    with LibraryStore(path) as db:
        store_recognition(db, record, recognition(record))
        draft = db.save_review(db.load_reviews([record])[0].approve(["title"]))
        run = db.start_scan(LibraryPreferences())
        changed = db.save_scan_records(run, [replace(record, size=record.size + 1)])[0]
        db.finish_run(run, "completed", {})
        assert not db.load_reviews([changed])[0].approved_fields
        with pytest.raises(LibraryError):
            db.save_review(draft)
        assert db.connection.execute("SELECT COUNT(*) FROM review_revisions").fetchone()[0] == 1


def test_stale_lyrics_cannot_attach_to_new_recognition(tmp_path):
    path, record = prepare(tmp_path)
    with LibraryStore(path) as db:
        first = recognition(record)
        store_recognition(db, record, first)
        lyrics = lyric_report(record, first)
        store_recognition(db, record, recognition(record, "New identification"))
        with pytest.raises(LibraryError):
            db.save_lyrics(lyrics)
        assert db.load_lyrics([record]) == []


def test_falsifying_current_values_or_replacement_guard_cannot_bypass_storage_validation(tmp_path):
    path, record = prepare(tmp_path)
    with LibraryStore(path) as db:
        draft = db.load_reviews([record])[0].edit("lyrics", ("New local text",))
        falsified = replace(draft, has_existing_lyrics=False).approve(["lyrics"])
        with pytest.raises(LibraryError, match="inventário"):
            db.save_review(falsified)


def test_manual_identity_survives_lyric_query_with_previous_approval_invalidated(tmp_path):
    path, record = prepare(tmp_path)
    with LibraryStore(path) as db:
        draft = db.load_reviews([record])[0]
        draft = draft.edit("artist", ("Manual artist",)).edit("title", ("Manual title",))
        db.save_review(draft.approve(["title"]))
        lyrics = replace(lyric_report(record), artist="Manual artist", title="Manual title")
        db.save_lyrics(lyrics)
        refreshed = db.load_reviews([record])[0]
        assert refreshed.field("title").proposed == ("Manual title",)
        assert refreshed.field("artist").proposed == ("Manual artist",)
        assert not refreshed.approved_fields
        assert refreshed.lyric_query_matches
        selected = refreshed.select_lyrics(lyrics.results[0].candidates[0]).allow_replacement(True)
        assert db.save_review(selected.approve(["lyrics"])).approved_fields == ("lyrics",)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.mp3",
        "other/track.mp3",
        "CON.mp3",
        "new.flac",
        "bad?.mp3",
        "track.mp3 ",
        "C:\\other.mp3",
    ],
)
def test_filename_approval_cannot_move_files_or_change_audio_extension(tmp_path, name):
    _, record = prepare(tmp_path)
    draft = build_review(record).edit("filename", (name,))
    with pytest.raises(ValueError):
        draft.approve(["filename"])


def test_filename_can_be_approved_independently_without_renaming_audio(tmp_path):
    path, record = prepare(tmp_path)
    with LibraryStore(path) as db:
        draft = db.load_reviews([record])[0].edit("filename", ("Artista - Título.mp3",))
        saved = db.save_review(draft.approve(["filename"]))
        assert saved.approved_fields == ("filename",)
        assert Path(record.path).exists()
        assert not Path(record.path).with_name("Artista - Título.mp3").exists()


def test_upgrade_from_v2_preserves_existing_inventory_and_recognition(tmp_path, monkeypatch):
    import afinario.library as library_module

    with monkeypatch.context() as patch:
        patch.setattr(library_module, "SCHEMA_VERSION", 2)
        path, record = prepare(tmp_path)
        with LibraryStore(path) as db:
            report = recognition(record)
            store_recognition(db, record, report)
    with LibraryStore(path) as db:
        state = db.load()
        assert state.records == (record,)
        assert state.identifications == (report,)
        assert not state.lyrics
        assert not state.reviews[0].approved_fields
        assert (
            db.connection.execute("PRAGMA user_version").fetchone()[0]
            == library_module.SCHEMA_VERSION
        )
    assert len(list(tmp_path.glob("library.pre-v2-*.sqlite3"))) == 1
