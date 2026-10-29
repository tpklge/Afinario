"""Biblioteca local versionada. Cada worker abre e fecha sua própria conexão."""

import json
import logging
import ntpath
import os
import sqlite3
import sys
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from afinario import config
from afinario.domain import (
    LyricCandidate,
    ProviderResult,
    RecordingCandidate,
    ReleaseCandidate,
    Status,
)
from afinario.identification import IdentificationReport, RecognitionOptions, report_from_data
from afinario.inventory import ALL_FORMATS, InventoryRecord, ScanIssue, TrackTags
from afinario.logging_config import RedactSecrets
from afinario.lyrics import (
    LyricOptions,
    LyricReport,
    lyric_report_from_data,
    recognition_key,
    record_key,
)
from afinario.resolver import Decision, DecisionStatus
from afinario.review import ReviewDraft, rebase_review, review_context, review_from_data

SCHEMA_VERSION = 5
APPLICATION_ID = 0x4146494E  # AFIN

# Deliberately separate migrations so an existing v1 database can be upgraded.
MIGRATIONS = (
    (
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
        """CREATE TABLE files (
            id TEXT PRIMARY KEY, path_key TEXT NOT NULL UNIQUE,
            original_path TEXT NOT NULL, current_path TEXT NOT NULL,
            original_directory TEXT NOT NULL, created_at TEXT NOT NULL,
            current_snapshot_id TEXT REFERENCES file_snapshots(id))""",
        """CREATE TABLE file_snapshots (
            id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id),
            created_at TEXT NOT NULL, record_json TEXT NOT NULL)""",
        "CREATE INDEX snapshots_file ON file_snapshots(file_id)",
        """CREATE TABLE runs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('scan', 'recognition')),
            state TEXT NOT NULL CHECK(state IN
                ('running', 'completed', 'cancelled', 'failed')),
            started_at TEXT NOT NULL, finished_at TEXT, roots_json TEXT NOT NULL,
            options_json TEXT NOT NULL, summary_json TEXT)""",
        """CREATE TABLE run_files (
            run_id TEXT NOT NULL REFERENCES runs(id),
            file_id TEXT NOT NULL REFERENCES files(id),
            snapshot_id TEXT NOT NULL REFERENCES file_snapshots(id),
            ordinal INTEGER NOT NULL, PRIMARY KEY(run_id, file_id))""",
        "CREATE INDEX run_files_order ON run_files(run_id, ordinal)",
        "CREATE INDEX runs_kind ON runs(kind, started_at)",
        """CREATE TABLE run_issues (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            path TEXT NOT NULL, message TEXT NOT NULL)""",
        "CREATE INDEX issues_run ON run_issues(run_id)",
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)",
    ),
    (
        """CREATE TABLE identifications (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, file_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL REFERENCES file_snapshots(id),
            source_sha256 TEXT, duration REAL, created_at TEXT NOT NULL,
            UNIQUE(run_id, file_id),
            FOREIGN KEY(run_id, file_id) REFERENCES run_files(run_id, file_id))""",
        "CREATE INDEX identifications_file ON identifications(file_id, snapshot_id)",
        """CREATE TABLE decisions (
            id TEXT PRIMARY KEY,
            identification_id TEXT NOT NULL UNIQUE REFERENCES identifications(id),
            policy_version TEXT NOT NULL, payload_json TEXT NOT NULL)""",
        """CREATE TABLE provider_results (
            id TEXT PRIMARY KEY, identification_id TEXT NOT NULL REFERENCES identifications(id),
            ordinal INTEGER NOT NULL, provider TEXT NOT NULL, payload_json TEXT NOT NULL)""",
        """CREATE TABLE candidates (
            id TEXT PRIMARY KEY, result_id TEXT NOT NULL REFERENCES provider_results(id),
            ordinal INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('recording', 'lyric')),
            payload_json TEXT NOT NULL)""",
        "CREATE INDEX results_identification ON provider_results(identification_id, ordinal)",
        "CREATE INDEX candidates_result ON candidates(result_id, ordinal)",
    ),
    (
        """CREATE TABLE lyric_analyses (
            id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id),
            snapshot_id TEXT NOT NULL REFERENCES file_snapshots(id),
            recording_key TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL)""",
        "CREATE INDEX lyrics_file ON lyric_analyses(file_id, snapshot_id)",
        """CREATE TABLE review_revisions (
            file_id TEXT NOT NULL REFERENCES files(id), revision INTEGER NOT NULL,
            snapshot_id TEXT NOT NULL REFERENCES file_snapshots(id),
            created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(file_id, revision))""",
    ),
    (
        """CREATE TABLE change_plans (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload_json TEXT NOT NULL)""",
        """CREATE TABLE file_operations (
            id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id),
            kind TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, payload_json TEXT NOT NULL, message TEXT NOT NULL)""",
        "CREATE INDEX operations_file ON file_operations(file_id, created_at)",
        """CREATE TABLE operation_events (
            id INTEGER PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES file_operations(id),
            created_at TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL)""",
        """CREATE TABLE active_file_operations (
            file_id TEXT PRIMARY KEY REFERENCES files(id),
            operation_id TEXT NOT NULL UNIQUE REFERENCES file_operations(id))""",
        """CREATE TABLE operation_evidence (
            file_id TEXT NOT NULL REFERENCES files(id),
            snapshot_id TEXT PRIMARY KEY REFERENCES file_snapshots(id),
            identification_json TEXT, lyrics_json TEXT)""",
    ),
    (
        """CREATE TABLE task_batches (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL, audd_used INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '')""",
        """CREATE TABLE task_items (
            batch_id TEXT NOT NULL REFERENCES task_batches(id), item_key TEXT NOT NULL,
            ordinal INTEGER NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '', PRIMARY KEY(batch_id,item_key))""",
        "CREATE INDEX task_items_order ON task_items(batch_id,ordinal)",
    ),
)


class LibraryError(RuntimeError):
    """Falha local que não deve ser confundida com uma biblioteca vazia."""


def default_library_path() -> Path:
    return Path(config.app_paths()["data"]) / "library.sqlite3"


def path_key(path: str, *, windows: bool | None = None) -> str:
    """Preserve spelling in stored paths; compare Windows paths using its own rules.

    macOS keeps case and Unicode spelling, including on case-sensitive APFS.
    This database belongs to the local machine, not to a portable path namespace.
    """
    use_windows_rules = os.name == "nt" if windows is None else windows
    if use_windows_rules:
        return ntpath.normcase(ntpath.abspath(path))
    return os.path.abspath(path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _record(payload: str) -> InventoryRecord:
    value = json.loads(payload)
    tags = value.pop("tags")
    for name in ("title", "artist", "album", "album_artist", "track", "disc", "date", "genre"):
        tags[name] = tuple(tags[name])
    value["tags"] = TrackTags(**tags)
    value["messages"] = tuple(value["messages"])
    return InventoryRecord(**value)


@dataclass(frozen=True)
class LibraryPreferences:
    roots: tuple[str, ...] = ()
    recursive: bool = True
    formats: tuple[str, ...] = tuple(sorted(ALL_FORMATS))
    search: str = ""
    settings: dict = field(default_factory=dict)
    platform: str = field(default_factory=lambda: sys.platform)
    lyrics_options: dict = field(default_factory=dict)
    recognition_options: dict = field(default_factory=dict)
    auto_rename_agreement: bool = True
    auto_tags_agreement: bool = True
    auto_lyrics: bool = True
    backup_directory: str = ""

    def __post_init__(self):
        if (
            not isinstance(self.roots, tuple)
            or any(not isinstance(root, str) for root in self.roots)
            or type(self.recursive) is not bool
            or not isinstance(self.formats, tuple)
            or any(not isinstance(item, str) for item in self.formats)
            or set(self.formats) - ALL_FORMATS
            or not isinstance(self.search, str)
            or not isinstance(self.platform, str)
            or type(self.auto_rename_agreement) is not bool
            or type(self.auto_tags_agreement) is not bool
            or type(self.auto_lyrics) is not bool
            or not isinstance(self.backup_directory, str)
        ):
            raise ValueError("Preferências da biblioteca inválidas.")
        # Validate the allowlist on read AND write. A token cannot be smuggled in.
        config.Settings.from_data(self.settings)
        LyricOptions(**self.lyrics_options)
        options = RecognitionOptions(**self.recognition_options)
        if any(type(value) is not bool for value in asdict(options).values()):
            raise ValueError("Preferências de reconhecimento inválidas.")

    @classmethod
    def from_json(cls, payload: str) -> "LibraryPreferences":
        value = json.loads(payload)
        value["roots"] = tuple(value["roots"])
        value["formats"] = tuple(value["formats"])
        return cls(**value)


@dataclass(frozen=True)
class LibraryState:
    records: tuple[InventoryRecord, ...] = ()
    identifications: tuple[IdentificationReport, ...] = ()
    preferences: LibraryPreferences = field(default_factory=LibraryPreferences)
    run_id: str | None = None
    run_state: str | None = None
    summary: dict | None = None
    issues: tuple[ScanIssue, ...] = ()
    lyrics: tuple[LyricReport, ...] = ()
    reviews: tuple[ReviewDraft, ...] = ()


class LibraryStore:
    def __init__(self, path: Path | None = None):
        self.path = default_library_path() if path is None else Path(path)
        self.connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path, timeout=10)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self._migrate()
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            if sys.platform == "darwin":
                self.connection.execute("PRAGMA fullfsync=ON")
        except (sqlite3.Error, OSError, LibraryError) as exc:
            self.close()
            if isinstance(exc, LibraryError):
                raise
            raise LibraryError("Não foi possível abrir a biblioteca local.") from exc

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _backup_before_migration(self, version: int):
        backup = self.path.with_name(f"{self.path.stem}.pre-v{version}-{uuid4().hex}.sqlite3")
        # Exclusive creation; all handles are closed before returning (Windows).
        with backup.open("xb"):
            pass
        try:
            with (
                closing(sqlite3.connect(self.path)) as source,
                closing(sqlite3.connect(backup)) as destination,
            ):
                source.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise LibraryError("A cópia da biblioteca não passou na verificação.")
        except Exception:
            backup.unlink(missing_ok=True)
            raise

    def _migrate(self):
        db = self.connection
        # The lock also serializes startup migrations in different processes.
        db.execute("BEGIN IMMEDIATE")
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            application_id = db.execute("PRAGMA application_id").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise LibraryError("Biblioteca criada por versão mais nova. Atualize o Afinário.")
            if application_id not in (0, APPLICATION_ID):
                raise LibraryError("Este arquivo não é uma biblioteca do Afinário.")
            if version and application_id != APPLICATION_ID:
                raise LibraryError("Identificação da biblioteca inválida.")
            if (
                version == 0
                and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                ).fetchone()
            ):
                raise LibraryError("Banco sem versão reconhecida; nenhum dado foi alterado.")
            if version < SCHEMA_VERSION and version:
                # Read via a second connection while holding the write reservation.
                # SQLite backup includes committed WAL pages, unlike a file copy.
                self._backup_before_migration(version)
            for index in range(version, SCHEMA_VERSION):
                for statement in MIGRATIONS[index]:
                    db.execute(statement)
                db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (index + 1, _now()))
                db.execute(f"PRAGMA user_version={index + 1}")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise LibraryError("Referências inconsistentes na biblioteca.")
            db.commit()
        except Exception:
            db.rollback()
            raise

    @contextmanager
    def _transaction(self):
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _save_preferences(self, db, preferences: LibraryPreferences):
        # Revalidate even if a caller mutated the settings dictionary.
        payload = _json(asdict(preferences))
        LibraryPreferences.from_json(payload)
        db.execute(
            "INSERT INTO settings VALUES ('library', ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (payload,),
        )

    def save_preferences(self, preferences: LibraryPreferences):
        with self._transaction() as db:
            self._save_preferences(db, preferences)

    def start_scan(self, preferences: LibraryPreferences) -> str:
        run_id = str(uuid4())
        with self._transaction() as db:
            self.ensure_no_file_mutations()
            self._save_preferences(db, preferences)
            db.execute(
                "INSERT INTO runs VALUES (?, 'scan', 'running', ?, NULL, ?, ?, NULL)",
                (
                    run_id,
                    _now(),
                    _json(preferences.roots),
                    _json({"recursive": preferences.recursive, "formats": preferences.formats}),
                ),
            )
        return run_id

    def save_scan_records(
        self, run_id: str, records: list[InventoryRecord], *, batch_id=None
    ) -> list[InventoryRecord]:
        saved = []
        with self._transaction() as db:
            self._require_running(db, run_id, "scan")
            self.ensure_no_file_mutations()
            ordinal = db.execute(
                "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM run_files WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            for record in records:
                key = path_key(record.path)
                existing = db.execute(
                    "SELECT id, current_snapshot_id FROM files WHERE path_key=?", (key,)
                ).fetchone()
                if existing is None:
                    record = replace(record, id=str(uuid4()))
                    snapshot_id = None
                    db.execute(
                        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, NULL)",
                        (
                            record.id,
                            key,
                            record.path,
                            record.path,
                            str(Path(record.path).parent),
                            _now(),
                        ),
                    )
                else:
                    record = replace(record, id=existing["id"])
                    self.ensure_file_unlocked(record.id)
                    snapshot_id = existing["current_snapshot_id"]
                payload = _json(asdict(record))
                previous = db.execute(
                    "SELECT record_json FROM file_snapshots WHERE id=?", (snapshot_id,)
                ).fetchone()
                if previous is None or previous[0] != payload:
                    snapshot_id = str(uuid4())
                    db.execute(
                        "INSERT INTO file_snapshots VALUES (?, ?, ?, ?)",
                        (snapshot_id, record.id, _now(), payload),
                    )
                db.execute(
                    "UPDATE files SET current_path=?, current_snapshot_id=? WHERE id=?",
                    (record.path, snapshot_id, record.id),
                )
                db.execute(
                    "INSERT INTO run_files VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(run_id, file_id) DO UPDATE SET snapshot_id=excluded.snapshot_id",
                    (run_id, record.id, snapshot_id, ordinal),
                )
                saved.append(record)
                if batch_id:
                    db.execute(
                        "INSERT INTO task_items VALUES (?, ?, ?, 'completed', ?, '') "
                        "ON CONFLICT(batch_id,item_key) DO UPDATE SET "
                        "payload_json=excluded.payload_json, "
                        "state='completed'",
                        (batch_id, record.id, ordinal, _json(asdict(record))),
                    )
                ordinal += 1
        return saved

    def save_scan_issue(self, run_id: str, issue: ScanIssue):
        with self._transaction() as db:
            self._require_running(db, run_id, "scan")
            db.execute(
                "INSERT INTO run_issues (run_id, path, message) VALUES (?, ?, ?)",
                (run_id, issue.path, issue.message),
            )

    @staticmethod
    def _require_running(db, run_id: str, kind: str):
        row = db.execute("SELECT kind, state FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or tuple(row) != (kind, "running"):
            raise LibraryError("Execução inexistente ou já finalizada.")

    def start_recognition(
        self,
        records: list[InventoryRecord],
        options: RecognitionOptions,
        preferences: LibraryPreferences,
    ) -> str:
        run_id = str(uuid4())
        with self._transaction() as db:
            self._save_preferences(db, preferences)
            db.execute(
                "INSERT INTO runs VALUES (?, 'recognition', 'running', ?, NULL, ?, ?, NULL)",
                (
                    run_id,
                    _now(),
                    _json(preferences.roots),
                    _json(
                        {
                            "recognition": asdict(options),
                            "settings": preferences.settings,
                        }
                    ),
                ),
            )
            for ordinal, record in enumerate(records):
                self.ensure_file_unlocked(record.id)
                row = db.execute(
                    "SELECT s.id, s.record_json FROM files f JOIN file_snapshots s "
                    "ON s.id=f.current_snapshot_id WHERE f.id=?",
                    (record.id,),
                ).fetchone()
                if row is None or row["record_json"] != _json(asdict(record)):
                    raise LibraryError("Inventário desatualizado; faça uma nova varredura.")
                db.execute(
                    "INSERT INTO run_files VALUES (?, ?, ?, ?)",
                    (run_id, record.id, row["id"], ordinal),
                )
        return run_id

    def finish_run(self, run_id: str, state: str, summary: dict):
        if state not in ("completed", "cancelled", "failed"):
            raise ValueError("Estado final inválido.")
        with self._transaction() as db:
            updated = db.execute(
                "UPDATE runs SET state=?, finished_at=?, summary_json=? "
                "WHERE id=? AND state='running'",
                (state, _now(), _json(summary), run_id),
            )
            if updated.rowcount != 1:
                raise LibraryError("Execução inexistente ou já finalizada.")

    def save_identification(
        self,
        run_id: str,
        report: IdentificationReport,
        *,
        secrets: tuple[str, ...] = (),
        batch_id=None,
    ):
        redactor = RedactSecrets(secrets)

        def redact(value: str) -> str:
            record = logging.LogRecord("afinario", 20, "", 0, value, (), None)
            redactor.filter(record)
            return record.getMessage()

        with self._transaction() as db:
            self.ensure_file_unlocked(report.file_id)
            self._require_running(db, run_id, "recognition")
            row = db.execute(
                "SELECT rf.snapshot_id, f.current_snapshot_id, f.current_path "
                "FROM run_files rf JOIN files f ON f.id=rf.file_id "
                "WHERE rf.run_id=? AND rf.file_id=?",
                (run_id, report.file_id),
            ).fetchone()
            if (
                row is None
                or row["snapshot_id"] != row["current_snapshot_id"]
                or row["current_path"] != report.path
            ):
                raise LibraryError("O inventário mudou durante o reconhecimento.")
            identification_id = str(uuid4())
            db.execute(
                "INSERT INTO identifications VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    identification_id,
                    run_id,
                    report.file_id,
                    row["snapshot_id"],
                    report.source_sha256,
                    report.duration,
                    _now(),
                ),
            )
            decision = asdict(report.decision)
            decision["reasons"] = [redact(reason) for reason in report.decision.reasons]
            db.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?)",
                (str(uuid4()), identification_id, report.decision.policy_version, _json(decision)),
            )
            for ordinal, result in enumerate(report.results):
                result_id = str(uuid4())
                payload = asdict(result)
                payload.pop("candidates")
                payload["message"] = redact(result.message)
                db.execute(
                    "INSERT INTO provider_results VALUES (?, ?, ?, ?, ?)",
                    (result_id, identification_id, ordinal, result.provider, _json(payload)),
                )
                for index, candidate in enumerate(result.candidates):
                    kind = "lyric" if isinstance(candidate, LyricCandidate) else "recording"
                    db.execute(
                        "INSERT INTO candidates VALUES (?, ?, ?, ?, ?)",
                        (str(uuid4()), result_id, index, kind, _json(asdict(candidate))),
                    )
            if batch_id:
                db.execute(
                    "UPDATE task_items SET state='completed',message='' "
                    "WHERE batch_id=? AND item_key=?",
                    (batch_id, report.file_id),
                )

    def _load_identification(self, row) -> IdentificationReport:
        db = self.connection
        payload = db.execute(
            "SELECT payload_json FROM decisions WHERE identification_id=?", (row["id"],)
        ).fetchone()[0]
        decision = json.loads(payload)
        decision["status"] = DecisionStatus(decision["status"])
        for name in ("reasons", "proposed_fields"):
            decision[name] = tuple(decision[name])
        results = []
        for item in db.execute(
            "SELECT id, payload_json FROM provider_results "
            "WHERE identification_id=? ORDER BY ordinal",
            (row["id"],),
        ).fetchall():
            value = json.loads(item["payload_json"])
            value["status"] = Status(value["status"])
            value["releases"] = tuple(ReleaseCandidate(**entry) for entry in value["releases"])
            candidates = []
            for candidate in db.execute(
                "SELECT kind, payload_json FROM candidates WHERE result_id=? ORDER BY ordinal",
                (item["id"],),
            ):
                fields = json.loads(candidate["payload_json"])
                if candidate["kind"] == "recording":
                    for name in ("title_aliases", "artist_aliases", "isrcs"):
                        fields[name] = tuple(fields[name])
                    candidates.append(RecordingCandidate(**fields))
                else:
                    candidates.append(LyricCandidate(**fields))
            value["candidates"] = tuple(candidates)
            results.append(ProviderResult(**value))
        return IdentificationReport(
            row["file_id"],
            row["current_path"],
            Decision(**decision),
            tuple(results),
            row["source_sha256"],
            row["duration"],
        )

    def load_identifications(self, records: list[InventoryRecord]) -> list[IdentificationReport]:
        reports = []
        for record in records:
            row = self.connection.execute(
                "SELECT i.*, f.current_path FROM identifications i JOIN files f ON f.id=i.file_id "
                "JOIN file_snapshots s ON s.id=f.current_snapshot_id "
                "WHERE i.file_id=? AND i.snapshot_id=f.current_snapshot_id AND s.record_json=? "
                "ORDER BY i.rowid DESC LIMIT 1",
                (record.id, _json(asdict(record))),
            ).fetchone()
            if row is not None:
                reports.append(self._load_identification(row))
            else:
                evidence = self.connection.execute(
                    "SELECT e.identification_json FROM operation_evidence e JOIN files f "
                    "ON f.current_snapshot_id=e.snapshot_id "
                    "JOIN file_snapshots s ON s.id=e.snapshot_id "
                    "WHERE e.file_id=? AND s.record_json=?",
                    (record.id, _json(asdict(record))),
                ).fetchone()
                if evidence and evidence[0]:
                    reports.append(report_from_data(json.loads(evidence[0])))
        return reports

    def identification_history(self, record: InventoryRecord, source_sha256: str):
        """Only compare the same audio and inventory snapshot, including past conflicts."""
        rows = self.connection.execute(
            "SELECT i.*, f.current_path FROM identifications i JOIN files f ON f.id=i.file_id "
            "WHERE i.file_id=? AND i.snapshot_id=f.current_snapshot_id "
            "AND i.source_sha256=? ORDER BY i.rowid",
            (record.id, source_sha256),
        ).fetchall()
        history = [self._load_identification(row) for row in rows]
        evidence = self.connection.execute(
            "SELECT e.identification_json FROM operation_evidence e JOIN files f "
            "ON f.current_snapshot_id=e.snapshot_id WHERE e.file_id=?",
            (record.id,),
        ).fetchone()
        if evidence and evidence[0]:
            report = report_from_data(json.loads(evidence[0]))
            if report.source_sha256 == source_sha256:
                history.append(report)
        return history

    def _current_record(self, file_id):
        row = self.connection.execute(
            "SELECT s.id, s.record_json FROM files f JOIN file_snapshots s "
            "ON s.id=f.current_snapshot_id WHERE f.id=?",
            (file_id,),
        ).fetchone()
        if row is None:
            raise LibraryError("Arquivo ausente da biblioteca.")
        return row["id"], _record(row["record_json"])

    def save_lyrics(self, report: LyricReport, *, batch_id=None):
        with self._transaction() as db:
            self.ensure_file_unlocked(report.file_id)
            snapshot_id, record = self._current_record(report.file_id)
            identification = next(iter(self.load_identifications([record])), None)
            if report.snapshot_key != record_key(record) or (
                report.recording_key != recognition_key(identification)
            ):
                raise LibraryError(
                    "A identificação ou o arquivo mudou. Atualize a busca de letras."
                )
            db.execute(
                "INSERT INTO lyric_analyses VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report.id,
                    report.file_id,
                    snapshot_id,
                    report.recording_key,
                    _now(),
                    _json(asdict(report)),
                ),
            )
            if batch_id:
                db.execute(
                    "UPDATE task_items SET state='completed',message='' "
                    "WHERE batch_id=? AND item_key=?",
                    (batch_id, report.file_id),
                )

    def load_lyrics(self, records) -> list[LyricReport]:
        identifications = {r.file_id: r for r in self.load_identifications(records)}
        reports = []
        for record in records:
            row = self.connection.execute(
                "SELECT l.payload_json FROM lyric_analyses l JOIN files f ON f.id=l.file_id "
                "JOIN file_snapshots s ON s.id=f.current_snapshot_id "
                "WHERE l.file_id=? AND l.snapshot_id=f.current_snapshot_id "
                "AND s.record_json=? AND l.recording_key=? ORDER BY l.rowid DESC LIMIT 1",
                (record.id, _json(asdict(record)), recognition_key(identifications.get(record.id))),
            ).fetchone()
            if row is not None:
                reports.append(lyric_report_from_data(json.loads(row[0])))
            else:
                evidence = self.connection.execute(
                    "SELECT e.lyrics_json FROM operation_evidence e JOIN files f "
                    "ON f.current_snapshot_id=e.snapshot_id "
                    "JOIN file_snapshots s ON s.id=e.snapshot_id "
                    "WHERE e.file_id=? AND s.record_json=?",
                    (record.id, _json(asdict(record))),
                ).fetchone()
                if evidence and evidence[0]:
                    report = lyric_report_from_data(json.loads(evidence[0]))
                    if report.recording_key == recognition_key(identifications.get(record.id)):
                        reports.append(report)
        return reports

    def load_reviews(self, records) -> list[ReviewDraft]:
        identifications = {r.file_id: r for r in self.load_identifications(records)}
        lyrics = {r.file_id: r for r in self.load_lyrics(records)}
        drafts = []
        for record in records:
            row = self.connection.execute(
                "SELECT revision, payload_json FROM review_revisions "
                "WHERE file_id=? ORDER BY revision DESC LIMIT 1",
                (record.id,),
            ).fetchone()
            context = review_context(record, identifications.get(record.id), lyrics.get(record.id))
            draft = None
            if row is not None:
                draft = review_from_data(json.loads(row["payload_json"]))
                if draft.context_key == context and draft.snapshot_key == record_key(record):
                    drafts.append(draft)
                    continue
            drafts.append(
                rebase_review(
                    draft,
                    record,
                    identifications.get(record.id),
                    lyrics.get(record.id),
                    revision=row["revision"] if row is not None else 0,
                )
            )
        return drafts

    def save_review(self, draft: ReviewDraft) -> ReviewDraft:
        with self._transaction() as db:
            self.ensure_file_unlocked(draft.file_id)
            snapshot_id, record = self._current_record(draft.file_id)
            expected = self.load_reviews([record])[0]
            if draft.revision != expected.revision:
                raise LibraryError("A revisão foi alterada por outra janela. Reabra a biblioteca.")
            if (
                draft.context_key != expected.context_key
                or draft.snapshot_key != expected.snapshot_key
            ):
                raise LibraryError("A proposta mudou. Revise os campos novamente.")
            if (
                tuple((f.name, f.current) for f in draft.fields)
                != tuple((f.name, f.current) for f in expected.fields)
                or draft.has_existing_lyrics != expected.has_existing_lyrics
                or draft.blocked_reason != expected.blocked_reason
                or (draft.lyric_query_artist, draft.lyric_query_title)
                != (expected.lyric_query_artist, expected.lyric_query_title)
            ):
                raise LibraryError("Os dados atuais da revisão não correspondem ao inventário.")
            draft = replace(draft.approve(draft.approved_fields), revision=expected.revision + 1)
            db.execute(
                "INSERT INTO review_revisions VALUES (?, ?, ?, ?, ?)",
                (draft.file_id, draft.revision, snapshot_id, _now(), _json(asdict(draft))),
            )
        return draft

    def ensure_file_unlocked(self, file_id):
        if SCHEMA_VERSION < 4:  # Migration fixtures can exercise an older schema writer.
            return
        if self.connection.execute(
            "SELECT 1 FROM active_file_operations WHERE file_id=?",
            (file_id,),
        ).fetchone():
            raise LibraryError("Há uma alteração ou recuperação pendente para este arquivo.")

    def ensure_no_file_mutations(self):
        if (
            SCHEMA_VERSION >= 4
            and self.connection.execute("SELECT 1 FROM active_file_operations LIMIT 1").fetchone()
        ):
            raise LibraryError(
                "Conclua ou recupere as alterações pendentes antes de varrer novamente."
            )

    def commit_file_operation(
        self, operation_id, expected, record, identification, lyrics, *, batch_id=None
    ):
        """The new snapshot and completion journal commit in one SQLite transaction."""
        with self._transaction() as db:
            _, current = self._current_record(expected.id)
            if current != expected:
                raise LibraryError("O inventário mudou durante a aplicação.")
            active = db.execute(
                "SELECT operation_id FROM active_file_operations WHERE file_id=?",
                (expected.id,),
            ).fetchone()
            if not active or active[0] != operation_id:
                raise LibraryError("A operação perdeu a reserva do arquivo.")
            snapshot_id = str(uuid4())
            db.execute(
                "INSERT INTO file_snapshots VALUES (?, ?, ?, ?)",
                (snapshot_id, record.id, _now(), _json(asdict(record))),
            )
            db.execute(
                "UPDATE files SET current_path=?, path_key=?, current_snapshot_id=? WHERE id=?",
                (record.path, path_key(record.path), snapshot_id, record.id),
            )
            db.execute(
                "INSERT INTO operation_evidence VALUES (?, ?, ?, ?)",
                (
                    record.id,
                    snapshot_id,
                    _json(asdict(identification)) if identification else None,
                    _json(asdict(lyrics)) if lyrics else None,
                ),
            )
            db.execute(
                "UPDATE file_operations SET state='completed',updated_at=? WHERE id=?",
                (_now(), operation_id),
            )
            db.execute(
                "INSERT INTO operation_events (operation_id,created_at,state,message) "
                "VALUES (?, ?, 'completed', 'Arquivo validado e biblioteca atualizada.')",
                (operation_id, _now()),
            )
            db.execute("DELETE FROM active_file_operations WHERE operation_id=?", (operation_id,))
            if batch_id:
                db.execute(
                    "UPDATE task_items SET state='completed',message='' "
                    "WHERE batch_id=? AND item_key=?",
                    (batch_id, record.id),
                )

    def load(self) -> LibraryState:
        # A coherent read transaction even when another window is scanning.
        with self.connection:
            self.connection.execute("BEGIN")
            preferences = self.connection.execute(
                "SELECT value_json FROM settings WHERE key='library'"
            ).fetchone()
            preferences = (
                LibraryPreferences.from_json(preferences[0])
                if preferences
                else LibraryPreferences()
            )
            run = self.connection.execute(
                "SELECT * FROM runs WHERE kind='scan' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if run is None:
                return LibraryState(preferences=preferences)
            records = tuple(
                _record(row[0])
                for row in self.connection.execute(
                    "SELECT s.record_json FROM run_files rf "
                    "JOIN files f ON f.id=rf.file_id "
                    "JOIN file_snapshots s ON s.id=f.current_snapshot_id "
                    "WHERE rf.run_id=? ORDER BY ordinal",
                    (run["id"],),
                )
            )
            return LibraryState(
                records,
                tuple(self.load_identifications(list(records))),
                preferences,
                run["id"],
                run["state"],
                json.loads(run["summary_json"]) if run["summary_json"] else None,
                tuple(
                    ScanIssue(row[0], row[1])
                    for row in self.connection.execute(
                        "SELECT path, message FROM run_issues WHERE run_id=? ORDER BY id",
                        (run["id"],),
                    )
                ),
                tuple(self.load_lyrics(list(records))),
                tuple(self.load_reviews(list(records))),
            )
