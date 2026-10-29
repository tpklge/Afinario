import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import afinario.library as storage
from afinario.config import Settings
from afinario.domain import ProviderResult, RecordingCandidate, ReleaseCandidate, Status
from afinario.identification import IdentificationReport, RecognitionOptions
from afinario.inventory import InventoryRecord, TrackTags
from afinario.library import LibraryError, LibraryPreferences, LibraryStore, path_key
from afinario.resolver import Decision, DecisionStatus


def track(tmp_path):
    path = tmp_path / "日本語 – Música 🎵.mp3"
    path.write_bytes(b"original bytes are never changed by persistence")
    info = path.stat()
    return InventoryRecord(
        str(path),
        "MP3",
        info.st_size,
        info.st_mtime_ns,
        tags=TrackTags(title=("Título", "別名"), artist=("Artista",), has_lyrics=True),
        messages=("Aviso de teste",),
    )


def scan_record(db, record):
    preferences = LibraryPreferences(roots=(str(storage.Path(record.path).parent),))
    run_id = db.start_scan(preferences)
    saved = db.save_scan_records(run_id, [record])[0]
    db.finish_run(run_id, "completed", {})
    return saved


def outcome(record):
    return IdentificationReport(
        record.id,
        record.path,
        Decision(
            DecisionStatus.AGREEMENT,
            "Artista",
            "Título",
            "mbid",
            ("Fontes concordam",),
            ("artist", "title"),
        ),
        (
            ProviderResult(
                "acoustid",
                Status.OK,
                "Mensagem",
                (
                    RecordingCandidate(
                        "acoustid",
                        "id",
                        "Título",
                        "Artista",
                        123,
                        0.95,
                        "mbid",
                        ("別名",),
                        ("Artist",),
                        ("ISRC",),
                        "studio",
                    ),
                ),
                1,
                0.2,
                (ReleaseCandidate("release", "Álbum", "2020", "BR"),),
            ),
            ProviderResult("audd", Status.RATE_LIMIT, "Aguardar", retry_after_seconds=70),
        ),
        "a" * 64,
        123,
    )


def identify(db, record, preferences=None):
    run_id = db.start_recognition(
        [record],
        RecognitionOptions(),
        preferences or LibraryPreferences(),
    )
    report = outcome(record)
    db.save_identification(run_id, report)
    db.finish_run(run_id, "completed", {"completed": 1})
    return report


def test_roundtrip_library_snapshots_reports_preferences_and_music_unchanged(tmp_path):
    record = track(tmp_path)
    original = storage.Path(record.path).read_bytes()
    path = tmp_path / "dados" / "library.sqlite3"
    preferences = LibraryPreferences(
        roots=(str(tmp_path),),
        recursive=False,
        formats=("MP3",),
        search="日本語",
        settings=Settings(analysis_workers=3, audd_token="SECRET").public_data(),
    )
    with LibraryStore(path) as db:
        record = scan_record(db, record)
        report = identify(db, record, preferences)
        assert db.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.connection.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    with LibraryStore(path) as db:
        state = db.load()
        assert state.records == (record,)
        assert state.identifications == (report,)
        assert state.preferences == preferences
        assert state.run_state == "completed"
        assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert len(db.connection.execute("SELECT * FROM candidates").fetchall()) == 1
    assert storage.Path(record.path).read_bytes() == original
    assert b"SECRET" not in path.read_bytes()


def test_rescan_reuses_uuid_snapshot_and_identification(tmp_path):
    with LibraryStore(tmp_path / "library.sqlite3") as db:
        record = scan_record(db, track(tmp_path))
        report = identify(db, record)
        reread = scan_record(db, replace(record, id="new-ephemeral-id"))
        assert reread.id == record.id
        assert db.load().identifications == (report,)
        assert db.connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        assert db.connection.execute("SELECT COUNT(*) FROM file_snapshots").fetchone()[0] == 1
        assert db.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3


def test_changed_file_invalidates_current_proposal_but_keeps_history(tmp_path):
    with LibraryStore(tmp_path / "library.sqlite3") as db:
        record = scan_record(db, track(tmp_path))
        identify(db, record)
        changed = scan_record(db, replace(record, size=record.size + 1))
        assert changed.id == record.id
        assert db.load().identifications == ()
        assert db.connection.execute("SELECT COUNT(*) FROM file_snapshots").fetchone()[0] == 2
        assert db.connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
        assert db.load_identifications([record]) == []


def test_partial_interrupted_scan_is_restored_and_not_silently_restarted(tmp_path):
    path = tmp_path / "library.sqlite3"
    with LibraryStore(path) as db:
        run_id = db.start_scan(LibraryPreferences(roots=(str(tmp_path),)))
        record = db.save_scan_records(run_id, [track(tmp_path)])[0]
    with LibraryStore(path) as db:
        state = db.load()
        assert state.run_id == run_id
        assert state.run_state == "running"
        assert state.records == (record,)
        # Another process may still own it; opening must not rewrite its state.
        assert db.connection.execute("SELECT state FROM runs").fetchone()[0] == "running"


def test_cancelled_scan_keeps_partial_records(tmp_path):
    path = tmp_path / "library.sqlite3"
    with LibraryStore(path) as db:
        run_id = db.start_scan(LibraryPreferences())
        record = db.save_scan_records(run_id, [track(tmp_path)])[0]
        db.finish_run(run_id, "cancelled", {"cancelled": True})
    with LibraryStore(path) as db:
        assert db.load().records == (record,)
        assert db.load().run_state == "cancelled"


def test_recognition_options_are_frozen_without_credentials(tmp_path):
    with LibraryStore(tmp_path / "library.sqlite3") as db:
        record = scan_record(db, track(tmp_path))
        settings = Settings(acoustid_key="KEY", audd_token="TOKEN", analysis_workers=4)
        options = RecognitionOptions(audd=True)
        run_id = db.start_recognition(
            [record],
            options,
            LibraryPreferences(settings=settings.public_data()),
        )
        payload = db.connection.execute(
            "SELECT options_json FROM runs WHERE id=?", (run_id,)
        ).fetchone()[0]
        assert json.loads(payload)["recognition"]["audd"]
        assert json.loads(payload)["settings"]["processing"]["analysis_workers"] == 4
        assert "KEY" not in payload and "TOKEN" not in payload


def test_tokens_are_rejected_in_preferences_and_redacted_in_events(tmp_path):
    with pytest.raises(ValueError):
        LibraryPreferences(settings={"processing": {"audd_token": "SECRET"}})
    with LibraryStore(tmp_path / "library.sqlite3") as db:
        record = scan_record(db, track(tmp_path))
        run_id = db.start_recognition([record], RecognitionOptions(), LibraryPreferences())
        report = outcome(record)
        report = replace(
            report,
            results=(ProviderResult("audd", Status.AUTH, "token=SECRET KEY"),),
            decision=Decision(DecisionStatus.PENDING, reasons=("Credential KEY",)),
        )
        db.save_identification(run_id, report, secrets=("KEY", "SECRET"))
        restored = db.load_identifications([record])[0]
        assert "SECRET" not in restored.results[0].message
        assert "KEY" not in restored.results[0].message
        assert "KEY" not in restored.decision.reasons[0]


def test_failure_mid_result_rolls_back_the_whole_report(tmp_path, monkeypatch):
    with LibraryStore(tmp_path / "library.sqlite3") as db:
        record = scan_record(db, track(tmp_path))
        run_id = db.start_recognition([record], RecognitionOptions(), LibraryPreferences())
        original = storage._json

        def fail_on_candidate(value):
            if isinstance(value, dict) and value.get("external_id") == "id":
                raise OSError("disk failure")
            return original(value)

        monkeypatch.setattr(storage, "_json", fail_on_candidate)
        with pytest.raises(OSError):
            db.save_identification(run_id, outcome(record))
        for table in ("identifications", "decisions", "provider_results", "candidates"):
            assert db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_stale_record_or_concurrent_rescan_cannot_store_wrong_proposal(tmp_path):
    with LibraryStore(tmp_path / "library.sqlite3") as db:
        record = scan_record(db, track(tmp_path))
        with pytest.raises(LibraryError, match="desatualizado"):
            db.start_recognition(
                [replace(record, size=0)], RecognitionOptions(), LibraryPreferences()
            )
        run_id = db.start_recognition([record], RecognitionOptions(), LibraryPreferences())
        scan_record(db, replace(record, size=1))
        with pytest.raises(LibraryError, match="mudou"):
            db.save_identification(run_id, outcome(record))
        assert db.connection.execute("SELECT COUNT(*) FROM identifications").fetchone()[0] == 0


def create_v1(path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(storage, "SCHEMA_VERSION", 1)
        with LibraryStore(path) as db:
            record = scan_record(db, track(path.parent))
    return record


def test_migration_backs_up_committed_wal_and_keeps_existing_records(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite3"
    record = create_v1(path, monkeypatch)
    # Keep a WAL connection alive during migration; copying only the .sqlite3 loses this value.
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO settings VALUES ('wal-proof', '{}')")
    writer.commit()
    try:
        with LibraryStore(path) as db:
            assert db.load().records == (record,)
            assert (
                db.connection.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
            )
            assert (
                len(db.connection.execute("SELECT * FROM schema_migrations").fetchall())
                == storage.SCHEMA_VERSION
            )
        backups = list(tmp_path.glob("library.pre-v1-*.sqlite3"))
        assert len(backups) == 1
        backup = sqlite3.connect(backups[0])
        try:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
            assert backup.execute(
                "SELECT value_json FROM settings WHERE key='wal-proof'"
            ).fetchone()
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            backup.close()
    finally:
        writer.close()


def test_failed_migration_is_atomic_and_original_version_remains(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite3"
    create_v1(path, monkeypatch)
    monkeypatch.setattr(
        storage,
        "MIGRATIONS",
        (storage.MIGRATIONS[0], ("CREATE TABLE partial (id)", "INVALID SQL")),
    )
    with pytest.raises(LibraryError):
        LibraryStore(path)
    db = sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='partial'").fetchone()
    finally:
        db.close()
    assert len(list(tmp_path.glob("library.pre-v1-*.sqlite3"))) == 1


def test_backup_failure_prevents_migration(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite3"
    create_v1(path, monkeypatch)

    def fail(*args):
        raise OSError("no space")

    monkeypatch.setattr(LibraryStore, "_backup_before_migration", fail)
    with pytest.raises(LibraryError):
        LibraryStore(path)
    db = sqlite3.connect(path)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["newer", "unrecognized", "corrupt"])
def test_unreadable_or_newer_database_is_not_reset_or_overwritten(tmp_path, kind):
    path = tmp_path / "library.sqlite3"
    if kind == "corrupt":
        path.write_bytes(b"not a SQLite database")
    elif kind == "newer":
        with LibraryStore(path) as db:
            scan_record(db, track(tmp_path))
            db.connection.execute("PRAGMA user_version=999")
    else:
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE unknown (id)")
        db.commit()
        db.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(LibraryError):
        LibraryStore(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_independent_connections_serialize_concurrent_scans_without_duplicate_ids(tmp_path):
    path = tmp_path / "library.sqlite3"
    record = track(tmp_path)

    def save(_):
        with LibraryStore(path) as db:
            return scan_record(db, record).id

    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(save, range(3)))
    assert len(set(ids)) == 1
    with LibraryStore(path) as db:
        assert db.connection.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1


def test_library_is_readable_from_another_process_offline(tmp_path):
    path = tmp_path / "library.sqlite3"
    with LibraryStore(path) as db:
        record = scan_record(db, track(tmp_path))
        identify(db, record)
    script = """
import json, sys
from afinario.library import LibraryStore
with LibraryStore(sys.argv[1]) as library:
    state = library.load()
    print(json.dumps([state.records[0].id, state.identifications[0].decision.title]))
"""
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=True,
    )
    assert json.loads(result.stdout) == [record.id, "Título"]


def test_corrupt_preferences_do_not_reset_existing_library(tmp_path):
    path = tmp_path / "library.sqlite3"
    with LibraryStore(path) as db:
        record = scan_record(db, track(tmp_path))
        db.connection.execute("UPDATE settings SET value_json='not json' WHERE key='library'")
        db.connection.commit()
    with LibraryStore(path) as db:
        with pytest.raises(ValueError):
            db.load()
        assert db.connection.execute("SELECT id FROM files").fetchone()[0] == record.id


def test_cancelled_recognition_keeps_completed_reports_and_run_options(tmp_path):
    path = tmp_path / "library.sqlite3"
    with LibraryStore(path) as db:
        record = scan_record(db, track(tmp_path))
        run_id = db.start_recognition([record], RecognitionOptions(), LibraryPreferences())
        report = outcome(record)
        db.save_identification(run_id, report)
        db.finish_run(run_id, "cancelled", {"completed": 1, "total": 2})
        with pytest.raises(LibraryError):
            db.save_identification(run_id, report)
    with LibraryStore(path) as db:
        assert db.load().identifications == (report,)
        assert (
            db.connection.execute(
                "SELECT state FROM runs WHERE id=?",
                (run_id,),
            ).fetchone()[0]
            == "cancelled"
        )


def test_windows_drive_unc_and_macos_case_sensitive_paths():
    assert path_key(r"C:\Músicas\Faixa.MP3", windows=True) == path_key(
        "c:/MÚSICAS/faixa.mp3",
        windows=True,
    )
    assert path_key(r"\\SERVER\Share\Música.mp3", windows=True) == path_key(
        "//server/share/MÚSICA.MP3",
        windows=True,
    )
    assert path_key("/Music/Track.mp3", windows=False) != path_key(
        "/Music/track.mp3",
        windows=False,
    )
