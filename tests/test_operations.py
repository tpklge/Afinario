import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import mutagen
import pytest

from afinario.change_plan import agreement_allows_rename, name_key, portable_name
from afinario.config import Settings
from afinario.domain import ProviderResult, RecordingCandidate, Status
from afinario.identification import IdentificationReport, file_digest
from afinario.inventory import read_track
from afinario.library import LibraryPreferences, LibraryStore
from afinario.operations import OperationError, OperationService
from afinario.resolver import resolve
from afinario.tag_writer import pcm_digest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def library(tmp_path):
    with LibraryStore(tmp_path / "data" / "library.sqlite3") as db:
        yield db


def add_track(library, tmp_path, extension="mp3", name="wrong"):
    root = tmp_path / "music"
    root.mkdir(exist_ok=True)
    path = root / f"{name}.{extension}"
    shutil.copyfile(FIXTURES / f"tone.{extension}", path)
    run = library.start_scan(LibraryPreferences(roots=(str(root),), auto_rename_agreement=False))
    record = library.save_scan_records(run, [read_track(path)])[0]
    library.finish_run(run, "completed", {})
    return record


def identify(library, record, artist="Artist", title="Song"):
    from afinario.identification import RecognitionOptions

    results = tuple(
        ProviderResult(
            provider,
            Status.OK,
            "test",
            (
                RecordingCandidate(
                    provider,
                    "id",
                    title,
                    artist,
                    record.duration,
                    score=0.99 if provider == "acoustid" else None,
                ),
            ),
            attempts=1,
        )
        for provider in ("acoustid", "audd")
    )
    report = IdentificationReport(
        record.id,
        record.path,
        resolve(results, record.duration),
        results,
        file_digest(Path(record.path), threading.Event()),
        record.duration,
    )
    run = library.start_recognition([record], RecognitionOptions(audd=True), LibraryPreferences())
    library.save_identification(run, report)
    library.finish_run(run, "completed", {})
    return report


def approve(library, record, **changes):
    draft = library.load_reviews([record])[0]
    for name, value in changes.items():
        draft = draft.edit(name, (value,))
    if "lyrics" in changes or "synced_lyrics" in changes:
        draft = draft.allow_replacement(True)
    return library.save_review(draft.approve(changes))


def test_consensus_rename_backup_restore_exact_bytes_and_uuid(library, tmp_path):
    record = add_track(library, tmp_path)
    source = Path(record.path)
    original = source.read_bytes()
    report = identify(library, record, artist="Beyoncé / Artist", title="Song: 日本語?")
    service = OperationService(library, Settings())
    plan = service.plan([record])
    assert len(plan.ready) == 1
    destination = Path(plan.ready[0].destination)
    assert destination.parent == source.resolve().parent
    assert not any(char in destination.name for char in '/\\<>:"|?*')
    assert source.read_bytes() == original  # preview does not mutate music
    results = service.apply(plan.id)
    assert results[0]["state"] == "completed", results
    assert destination.read_bytes() == original
    assert not source.exists()
    state = library.load()
    assert state.records[0].id == record.id
    assert state.records[0].path == str(destination)
    assert state.identifications[0].decision == report.decision
    history = service.history()
    backup = Path(json.loads(history[0]["payload_json"])["backup"])
    assert backup.read_bytes() == original
    restored = service.restore(history[0]["id"])
    assert restored["state"] == "completed", restored
    assert source.read_bytes() == original
    assert not destination.exists()
    assert library.load().records[0].id == record.id
    assert service.history()[1]["state"] == "restored"
    assert backup.read_bytes() == original


@pytest.mark.parametrize("extension", ["mp3", "m4a", "flac", "ogg", "opus"])
@pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="FFmpeg required for decoded-audio validation"
)
def test_write_approved_tags_preserves_audio_cover_unknown_fields_and_restores(
    library, tmp_path, extension
):
    record = add_track(library, tmp_path, extension)
    source = Path(record.path)
    audio = mutagen.File(source)
    if extension == "mp3":
        from mutagen.id3 import TXXX

        audio.tags.add(TXXX(encoding=3, desc="unknown-test", text=["Preserve me"]))
    elif extension == "m4a":
        from mutagen.mp4 import MP4FreeForm

        audio.tags["----:com.example:unknown-test"] = [MP4FreeForm(b"Preserve me")]
    else:
        audio.tags["unknown-test"] = ["Preserve me"]
    audio.save()
    run = library.start_scan(LibraryPreferences())
    record = library.save_scan_records(run, [read_track(source)])[0]
    library.finish_run(run, "completed", {})
    before = source.read_bytes()
    before_pcm = pcm_digest(source, "ffmpeg")
    before_album = record.tags.album
    approve(library, record, title="New title 日本語", lyrics="New plain lyrics", genre="Rock")
    service = OperationService(library, Settings())
    plan = service.plan([record], consensus_names=False)
    result = service.apply(plan.id)
    assert result[0]["state"] == "completed", result
    current = library.load().records[0]
    assert current.tags.title == ("New title 日本語",)
    assert current.tags.album == before_album
    assert current.tags.cover_count == record.tags.cover_count
    assert pcm_digest(source, "ffmpeg") == before_pcm
    assert not library.load().reviews[0].approved_fields
    assert service.restore(result[0]["id"])["state"] == "completed"
    assert source.read_bytes() == before


def test_collision_suffixes_and_manual_cycle_are_visible_before_mutation(library, tmp_path):
    a = add_track(library, tmp_path, name="a")
    b = add_track(library, tmp_path, name="b")
    identify(library, a)
    identify(library, b)
    (Path(a.path).parent / "artist - song.MP3").write_bytes(b"foreign")
    service = OperationService(library, Settings())
    plan = service.plan([b, a])
    assert {Path(i.destination).name for i in plan.ready} == {
        "Artist - Song (2).mp3",
        "Artist - Song (3).mp3",
    }
    again = service.plan([a, b])
    assert [i.destination for i in again.items] == [i.destination for i in plan.items]
    approve(library, a, filename="b.mp3")
    approve(library, b, filename="a.mp3")
    blocked = service.plan([a, b])
    assert all(i.status == "blocked" and "colis" in i.message for i in blocked.items)


def test_changed_files_approvals_and_new_destinations_block_old_plan(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    service = OperationService(library, Settings())
    first = service.plan([record])
    approve(library, record, title="Manual title")
    result = service.apply(first.id)
    assert result[0]["state"] == "blocked"
    second = service.plan([record], consensus_names=False)
    source = Path(record.path)
    source.write_bytes(source.read_bytes() + b"external")
    assert service.apply(second.id)[0]["state"] == "blocked"
    assert not service.history()


class PowerLoss(BaseException):
    pass


@pytest.mark.parametrize(
    "phase",
    [
        "preparing",
        "backup_ready",
        "prepared",
        "staging",
        "moved_source",
        "staged",
        "installing",
        "moved_destination",
        "installed",
        "database_committed",
    ],
)
def test_interrupted_commit_recovers_without_repeating_mutation(library, tmp_path, phase):
    record = add_track(library, tmp_path)
    source = Path(record.path)
    original = source.read_bytes()
    identify(library, record)

    def crash(event, manifest):
        if event == phase:
            raise PowerLoss

    service = OperationService(library, Settings(), hook=crash)
    plan = service.plan([record])
    destination = Path(plan.ready[0].destination)
    with pytest.raises(PowerLoss):
        service.apply(plan.id)
    recovered = OperationService(library, Settings())
    recovered.recover()
    recovered.recover()  # recovery is idempotent
    if phase == "database_committed":
        assert destination.read_bytes() == original
        assert library.load().records[0].path == str(destination)
        assert recovered.history()[0]["state"] == "completed"
    else:
        assert source.read_bytes() == original
        assert not destination.exists()
        assert recovered.history()[0]["state"] == "rolled_back"
    assert (
        library.connection.execute("SELECT COUNT(*) FROM active_file_operations").fetchone()[0] == 0
    )


def test_restore_refuses_modified_current_file_occupied_name_and_corrupt_backup(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    service = OperationService(library, Settings())
    result = service.apply(service.plan([record]).id)[0]
    current = Path(library.load().records[0].path)
    original_name = Path(record.path)
    original_name.write_bytes(b"foreign")
    with pytest.raises(OperationError, match="ocupado"):
        service.restore(result["id"])
    assert original_name.read_bytes() == b"foreign"
    original_name.unlink()
    current.write_bytes(current.read_bytes() + b"external")
    with pytest.raises(OperationError, match="externamente"):
        service.restore(result["id"])


def test_two_sources_are_required_and_filename_is_portable(library, tmp_path):
    record = add_track(library, tmp_path)
    report = identify(library, record)
    draft = library.load_reviews([record])[0]
    assert agreement_allows_rename(report, draft)
    assert not agreement_allows_rename(replace(report, results=report.results[:1]), draft)
    assert not agreement_allows_rename(report, draft.edit("title", ("Manual",)))
    name = portable_name("é" * 250, "日本語 : / *", ".mp3")
    assert len(name.encode("utf-8")) <= 240
    assert name_key("Beyoncé.mp3") == name_key("BEYONCE\u0301.MP3")


def test_links_are_blocked(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    source = Path(record.path)
    os.link(source, source.with_name("hardlink.mp3"))
    assert OperationService(library, Settings()).plan([record]).items[0].status == "blocked"


@pytest.mark.parametrize("phase", ["moved_source", "moved_destination", "database_committed"])
def test_process_death_releases_lock_and_recovery_works_after_reopen(library, tmp_path, phase):
    record = add_track(library, tmp_path)
    original = Path(record.path).read_bytes()
    identify(library, record)
    plan = OperationService(library, Settings()).plan([record])
    script = """import os, sys
from afinario.config import Settings
from afinario.library import LibraryStore
from afinario.operations import OperationService
def crash(event, manifest):
    if event == sys.argv[3]:
        os._exit(77)
with LibraryStore(sys.argv[1]) as library:
    OperationService(library, Settings(), hook=crash).apply(sys.argv[2])
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.run(
        [sys.executable, "-c", script, str(library.path), plan.id, phase],
        env=environment,
        capture_output=True,
        timeout=15,
    )
    assert child.returncode == 77, child.stderr
    with LibraryStore(library.path) as reopened:
        service = OperationService(reopened, Settings())
        service.recover()
        current = reopened.load().records[0]
        assert Path(current.path).read_bytes() == original
        assert current.id == record.id
        assert service.history()[0]["state"] == (
            "completed" if phase == "database_committed" else "rolled_back"
        )


def test_destination_race_preserves_foreign_file_and_original(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    source = Path(record.path)
    before = source.read_bytes()

    def occupy(event, manifest):
        if event == "installing":
            Path(manifest["item"]["destination"]).write_bytes(b"foreign content")

    service = OperationService(library, Settings(), hook=occupy)
    plan = service.plan([record])
    result = service.apply(plan.id)
    assert result[0]["state"] == "failed"
    assert source.read_bytes() == before
    assert Path(plan.ready[0].destination).read_bytes() == b"foreign content"
    assert service.history()[0]["state"] == "rolled_back"


def test_recovery_conflict_keeps_backup_and_staged_original_until_name_is_free(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    source = Path(record.path)
    original = source.read_bytes()

    def crash(event, manifest):
        if event == "moved_source":
            source.write_bytes(b"foreign occupant")
            raise PowerLoss

    service = OperationService(library, Settings(), hook=crash)
    with pytest.raises(PowerLoss):
        service.apply(service.plan([record]).id)
    service = OperationService(library, Settings())
    service.recover()
    row = service.history()[0]
    assert row["state"] == "needs_recovery"
    manifest = json.loads(row["payload_json"])
    assert Path(manifest["backup"]).read_bytes() == original
    assert Path(manifest["staged"]).read_bytes() == original
    assert source.read_bytes() == b"foreign occupant"
    assert service.plan([record]).items[0].status == "blocked"
    from afinario.library import LibraryError

    with pytest.raises(LibraryError, match="pendentes"):
        library.start_scan(LibraryPreferences())
    source.unlink()
    service.recover()
    assert source.read_bytes() == original
    assert service.history()[0]["state"] == "rolled_back"


def test_cancel_before_commit_and_backup_failure_leave_original_untouched(
    library, tmp_path, monkeypatch
):
    record = add_track(library, tmp_path)
    identify(library, record)
    original = Path(record.path).read_bytes()
    stop = threading.Event()

    def cancel(event, manifest):
        if event == "prepared":
            stop.set()

    service = OperationService(library, Settings(), stop=stop, hook=cancel)
    assert service.apply(service.plan([record]).id)[0]["state"] == "failed"
    assert Path(record.path).read_bytes() == original
    assert service.history()[0]["state"] == "rolled_back"
    monkeypatch.setattr(
        "afinario.operations.copy_exclusive", lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    )
    service = OperationService(library, Settings())
    assert service.apply(service.plan([record]).id)[0]["state"] == "failed"
    assert Path(record.path).read_bytes() == original


@pytest.mark.parametrize("extension", ["mp3", "m4a", "flac", "ogg", "opus"])
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_plain_and_synced_lyrics_are_written_separately(library, tmp_path, extension):
    from afinario.lyrics import embedded_lyrics

    record = add_track(library, tmp_path, extension)
    text = "[00:00.00]First line\n[00:00.20]Second line"
    approve(library, record, synced_lyrics=text)
    service = OperationService(library, Settings())
    results = service.apply(service.plan([record], consensus_names=False).id)
    assert results[0]["state"] == "completed", results
    lyrics = embedded_lyrics(Path(record.path))
    assert any(c.plain_text == "Letra sintética de teste" for c in lyrics)
    assert any("Second line" in (c.synced_text or "") for c in lyrics)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_id3v23_and_existing_id3v1_are_preserved_without_conversion(library, tmp_path):
    from mutagen.id3 import ID3

    record = add_track(library, tmp_path)
    path = Path(record.path)
    tags = ID3(path)
    tags.update_to_v23()
    tags.save(path, v2_version=3, v1=2)
    original = path.read_bytes()
    id3v1 = original[-128:]
    assert id3v1.startswith(b"TAG")
    run = library.start_scan(LibraryPreferences())
    record = library.save_scan_records(run, [read_track(path)])[0]
    library.finish_run(run, "completed", {})
    approve(library, record, title="Changed")
    service = OperationService(library, Settings())
    results = service.apply(service.plan([record], consensus_names=False).id)
    assert results[0]["state"] == "completed", results
    assert ID3(path, translate=False).version[1] == 3
    assert path.read_bytes()[-128:] == id3v1


def test_replayed_plan_does_not_apply_twice_and_backup_is_not_inventoried(library, tmp_path):
    from afinario.inventory import scan

    record = add_track(library, tmp_path)
    identify(library, record)
    service = OperationService(library, Settings())
    plan = service.plan([record])
    backup_root = Path(record.path).parent / "backups"
    assert service.apply(plan.id, backup_root=backup_root)[0]["state"] == "completed"
    assert service.apply(plan.id, backup_root=backup_root)[0]["state"] == "blocked"
    seen = []
    scan([Path(record.path).parent], on_record=seen.append)
    assert len(seen) == 1
    assert len(service.history()) == 1


def test_case_only_name_change_roundtrip(library, tmp_path):
    record = add_track(library, tmp_path, name="Artist - Song")
    before = Path(record.path).read_bytes()
    approve(library, record, filename="artist - song.mp3")
    service = OperationService(library, Settings())
    result = service.apply(service.plan([record], consensus_names=False).id)[0]
    assert result["state"] == "completed", result
    assert Path(library.load().records[0].path).name == "artist - song.mp3"
    assert service.restore(result["id"])["state"] == "completed"
    assert Path(record.path).read_bytes() == before


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_m4a_alac_preserves_lossless_audio(library, tmp_path):
    record = add_track(library, tmp_path, extension="m4a")
    path = Path(record.path)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(FIXTURES / "tone.wav"),
            "-map",
            "0:a",
            "-vn",
            "-c:a",
            "alac",
            str(path),
        ],
        check=True,
    )
    run = library.start_scan(LibraryPreferences())
    record = library.save_scan_records(run, [read_track(path)])[0]
    library.finish_run(run, "completed", {})
    original = path.read_bytes()
    approve(library, record, artist="Approved artist", track="2/12", disc="1/2")
    service = OperationService(library, Settings())
    result = service.apply(service.plan([record], consensus_names=False).id)[0]
    assert result["state"] == "completed", result
    current = library.load().records[0]
    assert current.tags.artist == ("Approved artist",)
    assert current.tags.track == ("2/12",)
    assert current.tags.disc == ("1/2",)
    assert service.restore(result["id"])["state"] == "completed"
    assert path.read_bytes() == original


def test_corrupt_backup_blocks_restore_and_keeps_current_version(library, tmp_path):
    record = add_track(library, tmp_path)
    identify(library, record)
    service = OperationService(library, Settings())
    result = service.apply(service.plan([record]).id)[0]
    current = Path(library.load().records[0].path)
    content = current.read_bytes()
    backup = Path(json.loads(service.history()[0]["payload_json"])["backup"])
    backup.write_bytes(b"corrupted backup")
    restored = service.restore(result["id"])
    assert restored["state"] == "failed"
    assert current.read_bytes() == content
    assert not Path(record.path).exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_failed_audio_validation_never_replaces_the_original(library, tmp_path, monkeypatch):
    record = add_track(library, tmp_path)
    original = Path(record.path).read_bytes()
    approve(library, record, title="Changed title")
    monkeypatch.setattr("afinario.tag_writer.pcm_digest", lambda path, *a: str(path))
    service = OperationService(library, Settings())
    result = service.apply(service.plan([record], consensus_names=False).id)[0]
    assert result["state"] == "failed"
    assert "áudio" in result["message"]
    assert Path(record.path).read_bytes() == original
    assert service.history()[0]["state"] == "rolled_back"
