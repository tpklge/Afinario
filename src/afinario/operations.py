"""Recoverable per-file commits. Originals are never edited in place."""

import json
import os
import shutil
import threading
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from afinario.cancellation import AnalysisCancelled, check_cancelled
from afinario.change_plan import agreement_allows_rename, make_plan, name_key, plan_from_json
from afinario.file_safety import (
    copy_exclusive,
    directory_identity,
    identity,
    move_exclusive,
    operation_lock,
    regular_file,
    sync_directory,
    sync_file,
)
from afinario.identification import file_digest
from afinario.inventory import read_track
from afinario.library import LibraryError, _json
from afinario.lyrics import digest, embedded_lyrics, recognition_key, record_key
from afinario.review import validate_filename
from afinario.tag_writer import WriteError, write_verified


class OperationError(ValueError):
    pass


def now():
    return datetime.now(UTC).isoformat()


def message_for(exc):
    if isinstance(exc, (OperationError, WriteError, LibraryError)):
        return str(exc)
    if isinstance(exc, AnalysisCancelled):
        return "Cancelado antes de alterar o original."
    if isinstance(exc, FileExistsError):
        return "O destino foi ocupado por outro arquivo; nenhuma sobrescrita foi permitida."
    return "Falha de acesso, ferramenta, permissão ou espaço. Confira o arquivo e os backups."


class OperationService:
    def __init__(self, library, settings, *, stop=None, on_event=None, hook=None):
        self.library, self.settings = library, settings
        self.stop = stop or threading.Event()
        self.on_event = on_event or (lambda *a: None)
        self.hook = hook or (lambda *a: None)
        self.lock_path = library.path.with_suffix(".operations.lock")
        self.batch_id = None

    def _save_plan(self, plan):
        with self.library._transaction() as db:
            db.execute(
                "INSERT INTO change_plans VALUES (?, ?, ?)", (plan.id, now(), _json(asdict(plan)))
            )
        return plan

    def plan(
        self,
        records,
        *,
        consensus_names=True,
        automatic_only=False,
        auto_tags=False,
        auto_lyrics=False,
    ):
        return self._save_plan(
            make_plan(
                self.library,
                records,
                consensus_names=consensus_names,
                automatic_only=automatic_only,
                auto_tags=auto_tags,
                auto_lyrics=auto_lyrics,
                stop=self.stop,
            )
        )

    def history(self):
        return [
            dict(row)
            for row in self.library.connection.execute(
                "SELECT * FROM file_operations ORDER BY rowid DESC"
            )
        ]

    def _phase(self, manifest, state, message="", *, release=False):
        with self.library._transaction() as db:
            db.execute(
                "UPDATE file_operations SET state=?,updated_at=?,payload_json=?,message=? "
                "WHERE id=?",
                (state, now(), _json(manifest), message, manifest["id"]),
            )
            db.execute(
                "INSERT INTO operation_events (operation_id,created_at,state,message) "
                "VALUES (?, ?, ?, ?)",
                (manifest["id"], now(), state, message),
            )
            if release:
                db.execute(
                    "DELETE FROM active_file_operations WHERE operation_id=?", (manifest["id"],)
                )
        self.on_event(manifest["item"]["record"]["id"], state, message)
        self.hook(state, manifest)

    def _current_check(self, item, *, restoring=False):
        _, current = self.library._current_record(item.record.id)
        if current != item.record:
            raise OperationError("O inventário mudou; gere a prévia novamente.")
        review = self.library.load_reviews([current])[0]
        reports = self.library.load_identifications([current])
        report = reports[0] if reports else None
        lyrics = next(iter(self.library.load_lyrics([current])), None)
        if digest(asdict(review)) != item.review_signature or (
            recognition_key(report) != item.recognition_signature
        ):
            raise OperationError("A aprovação ou as evidências mudaram; gere outra prévia.")
        if not restoring:
            from afinario.automation import automatic_fields

            permitted = automatic_fields(
                current, report, review, lyrics, tags=True, apply_lyrics=True
            )
            for name, values in item.changes.items():
                if name in item.automatic_fields:
                    if permitted.get(name) != tuple(values):
                        raise OperationError("A evidência da alteração automática mudou.")
                    continue
                field = review.field(name)
                if not field.approved or not field.changed or tuple(values) != field.proposed:
                    raise OperationError("O plano inclui um campo sem aprovação válida.")
            validate_filename((Path(item.destination).name,), (Path(item.source).name,))
            if Path(item.destination).name != Path(item.source).name:
                if item.automatic_name:
                    if not agreement_allows_rename(report, review):
                        raise OperationError(
                            "A concordância necessária para renomear não está disponível."
                        )
                elif not review.field("filename").approved or review.field("filename").proposed != (
                    Path(item.destination).name,
                ):
                    raise OperationError("O nome do plano não tem aprovação válida.")
        source = Path(item.source)
        if directory_identity(source.parent) != tuple(item.directory_id):
            raise OperationError("A pasta mudou desde o planejamento.")
        info = regular_file(source)
        if (
            (info.st_dev, info.st_ino) != tuple(item.file_identity)
            or (info.st_size, info.st_mtime_ns) != (current.size, current.mtime_ns)
            or file_digest(source, self.stop) != item.source_sha256
        ):
            raise OperationError("O arquivo mudou desde o planejamento.")
        destination = Path(item.destination)
        if source.parent != destination.parent:
            raise OperationError("O destino precisa permanecer na pasta original.")
        for path in source.parent.iterdir():
            if name_key(path.name) == name_key(destination.name) and path.name != source.name:
                raise OperationError("O destino foi ocupado; gere uma nova prévia.")
        return report, lyrics

    def _begin(self, item, backup_root, *, restore_of=None, restore_from=None):
        operation_id = str(uuid4())
        parent = Path(item.source).parent
        backup_root = backup_root.absolute()
        backup_root.mkdir(parents=True, exist_ok=True)
        directory_identity(backup_root.resolve(strict=True))
        backup = backup_root / f".afinario-backup-{operation_id}.original"
        manifest = {
            "id": operation_id,
            "item": asdict(item),
            "backup": str(backup),
            "temporary": str(parent / f".afinario-{operation_id}.tmp{Path(item.source).suffix}"),
            "staged": str(parent / f".afinario-{operation_id}.original"),
            "output_hash": "",
            "output_identity": [],
            "audio_digest": "",
            "restore_of": restore_of,
            "restore_from": restore_from,
        }
        with self.library._transaction() as db:
            self.library.ensure_file_unlocked(item.record.id)
            evidence, _ = self._current_check(item, restoring=bool(restore_of))
            manifest["evidence"] = evidence.summary() if evidence else None
            db.execute(
                "INSERT INTO file_operations VALUES (?, ?, ?, 'preparing', ?, ?, ?, '')",
                (
                    operation_id,
                    item.record.id,
                    "restore" if restore_of else "apply",
                    now(),
                    now(),
                    _json(manifest),
                ),
            )
            db.execute(
                "INSERT INTO active_file_operations VALUES (?, ?)", (item.record.id, operation_id)
            )
        self.hook("preparing", manifest)
        return manifest

    def apply(self, plan_id, *, backup_root=None, batch=None, pause=None):
        row = self.library.connection.execute(
            "SELECT payload_json FROM change_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
        if not row:
            raise OperationError("Plano não encontrado.")
        plan = plan_from_json(row[0])
        results = []
        checkpoints = {r["item_key"]: r for r in batch.items()} if batch else {}
        self.batch_id = batch.id if batch else None
        with operation_lock(self.lock_path):
            self._recover_locked()
            root = Path(backup_root) if backup_root else self.library.path.parent / "backups"
            for item in plan.ready:
                if self.stop.is_set() or (pause and pause.requested.is_set()):
                    break
                if checkpoints.get(item.record.id, {}).get("state") == "completed":
                    results.append(
                        {
                            "file_id": item.record.id,
                            "state": "completed",
                            "message": "Já concluído neste lote.",
                        }
                    )
                    continue
                if batch:
                    batch.mark(item.record.id, "running")
                try:
                    result = self._execute(item, root)
                    results.append(result)
                    if batch and result["state"] != "completed":
                        batch.mark(item.record.id, "failed", result["message"])
                except Exception as exc:
                    results.append(
                        {"file_id": item.record.id, "state": "blocked", "message": message_for(exc)}
                    )
                    if batch:
                        batch.mark(item.record.id, "failed", message_for(exc))
        return results

    def _execute(self, item, backup_root, *, restore_of=None, restore_from=None):
        manifest = None
        try:
            check_cancelled(self.stop)
            report, lyrics = self._current_check(item, restoring=bool(restore_of))
            # Space for backup and a full working copy, with a small metadata margin.
            backup_root.mkdir(parents=True, exist_ok=True)
            sync_directory(backup_root.parent)
            same_volume = backup_root.stat().st_dev == Path(item.source).parent.stat().st_dev
            if (
                same_volume
                and shutil.disk_usage(backup_root).free < 2 * item.record.size + 8_388_608
            ):
                raise OperationError(
                    "Espaço insuficiente para backup e cópia de trabalho no volume."
                )
            if shutil.disk_usage(backup_root).free < item.record.size + 4_194_304 or (
                shutil.disk_usage(Path(item.source).parent).free < item.record.size + 4_194_304
            ):
                raise OperationError("Espaço insuficiente para backup e cópia de trabalho.")
            manifest = self._begin(
                item, backup_root, restore_of=restore_of, restore_from=restore_from
            )
            source, destination = Path(item.source), Path(item.destination)
            backup, temporary, staged = (
                Path(manifest[k]) for k in ("backup", "temporary", "staged")
            )
            copy_exclusive(source, backup)
            if file_digest(backup, self.stop) != item.source_sha256:
                raise OperationError("O backup não corresponde ao original; aplicação bloqueada.")
            self._phase(manifest, "backup_ready", "Backup original verificado.")
            check_cancelled(self.stop)
            if restore_from:
                original_backup = Path(restore_from["path"])
                if file_digest(original_backup, self.stop) != restore_from["sha256"]:
                    raise OperationError("O backup solicitado está ausente ou foi alterado.")
                copy_exclusive(original_backup, temporary)
            else:
                copy_exclusive(source, temporary)
                if item.changes:
                    manifest["audio_digest"] = write_verified(
                        source, temporary, item.changes, self.settings.ffmpeg, self.stop
                    )
            sync_file(temporary)
            manifest["output_hash"] = file_digest(temporary, self.stop)
            manifest["output_identity"] = list(identity(temporary))
            if restore_from and manifest["output_hash"] != restore_from["sha256"]:
                raise OperationError("A cópia de restauração não passou na verificação.")
            if (
                not restore_from
                and not item.changes
                and manifest["output_hash"] != item.source_sha256
            ):
                raise OperationError("A cópia para renomeação ficou diferente do original.")
            self._phase(manifest, "prepared", "Cópia e campos aprovados verificados.")
            check_cancelled(self.stop)
            self._current_check(item, restoring=bool(restore_of))
            if file_digest(backup, self.stop) != item.source_sha256:
                raise OperationError("O backup mudou; o original será preservado.")
            self._phase(manifest, "staging", "Preparando origem para troca recuperável.")
            # From here to the durable commit cancellation waits for a recoverable point.
            move_exclusive(source, staged)
            self.hook("moved_source", manifest)
            self._phase(manifest, "staged")
            if identity(staged) != tuple(item.file_identity) or (
                file_digest(staged, threading.Event()) != item.source_sha256
            ):
                raise OperationError("O original mudou antes da troca; recuperação necessária.")
            self._phase(manifest, "installing")
            if directory_identity(destination.parent) != tuple(item.directory_id):
                raise OperationError("A pasta mudou antes de finalizar a operação.")
            move_exclusive(temporary, destination)
            self.hook("moved_destination", manifest)
            self._phase(manifest, "installed")
            if not self._owned(destination, manifest["output_identity"], manifest["output_hash"]):
                raise OperationError("O destino mudou durante a finalização.")
            if file_digest(backup, threading.Event()) != item.source_sha256:
                raise OperationError(
                    "O backup mudou antes de concluir; restauração do original necessária."
                )
            current = read_track(destination)
            if current is None or current.status == "error":
                raise OperationError("O destino não pôde ser relido; recuperação necessária.")
            current = replace(current, id=item.record.id)
            if report:
                report = replace(report, path=current.path, source_sha256=manifest["output_hash"])
            if lyrics:
                lyrics = replace(
                    lyrics,
                    id=str(uuid4()),
                    path=current.path,
                    snapshot_key=record_key(current),
                    recording_key=recognition_key(report),
                    source_sha256=manifest["output_hash"],
                    existing=embedded_lyrics(destination),
                )
            self.library.commit_file_operation(
                manifest["id"], item.record, current, report, lyrics, batch_id=self.batch_id
            )
            self.hook("database_committed", manifest)
            if restore_of:
                self._mark_restored(restore_of, manifest["id"])
            cleaned = self._cleanup(manifest)
            message = (
                ""
                if cleaned
                else (
                    "Alteração concluída; original intermediário preservado para conferir o backup."
                )
            )
            if message:
                self._phase(manifest, "completed", message)
            self.on_event(
                item.record.id, "completed", message or "Alteração concluída; backup disponível."
            )
            return {
                "id": manifest["id"],
                "file_id": item.record.id,
                "state": "completed",
                "message": message,
            }
        except Exception as exc:
            if manifest:
                # If SQLite already committed, never roll back the filesystem behind it.
                row = self.library.connection.execute(
                    "SELECT state FROM file_operations WHERE id=?",
                    (manifest["id"],),
                ).fetchone()
                if row and row[0] == "completed":
                    return {
                        "id": manifest["id"],
                        "file_id": item.record.id,
                        "state": "completed",
                        "message": "Concluído; limpeza será retomada ao abrir.",
                    }
                self._phase(manifest, "needs_recovery", message_for(exc))
                try:
                    self._rollback(manifest)
                except Exception:
                    self._phase(
                        manifest,
                        "needs_recovery",
                        "Recuperação pendente. Originais e backups foram preservados.",
                    )
                return {
                    "id": manifest["id"],
                    "file_id": item.record.id,
                    "state": "failed",
                    "message": message_for(exc),
                }
            raise

    @staticmethod
    def _owned(path, expected_identity, sha256):
        try:
            return identity(path) == tuple(expected_identity) and (
                file_digest(path, threading.Event()) == sha256
            )
        except OSError:
            return False

    def _cleanup(self, manifest):
        item = manifest["item"]
        cleaned = True
        for path, expected_id, expected_hash in (
            (Path(manifest["staged"]), item["file_identity"], item["source_sha256"]),
            (Path(manifest["temporary"]), manifest["output_identity"], manifest["output_hash"]),
        ):
            if not path.exists():
                continue
            if path == Path(manifest["staged"]):
                try:
                    if (
                        file_digest(Path(manifest["backup"]), threading.Event())
                        != item["source_sha256"]
                    ):
                        cleaned = False
                        continue
                except OSError:
                    cleaned = False
                    continue
            if self._owned(path, expected_id, expected_hash):
                path.unlink()
                sync_directory(path.parent)
            else:
                cleaned = False
        return cleaned

    def _rollback(self, manifest):
        item = manifest["item"]
        source, destination = Path(item["source"]), Path(item["destination"])
        if directory_identity(source.parent) != tuple(item["directory_id"]):
            raise OperationError("Pasta indisponível para recuperação.")
        staged = Path(manifest["staged"])
        original_ok = self._owned(source, item["file_identity"], item["source_sha256"])
        staged_ok = self._owned(staged, item["file_identity"], item["source_sha256"])
        output_ok = self._owned(destination, manifest["output_identity"], manifest["output_hash"])
        if not original_ok:
            if not staged_ok:
                raise OperationError("O original intermediário precisa de verificação manual.")
            if output_ok:
                destination.unlink()
                sync_directory(destination.parent)
            elif source.exists():
                raise OperationError("O nome original está ocupado por outro arquivo.")
            move_exclusive(staged, source)
        self._cleanup(manifest)
        self._phase(
            manifest,
            "rolled_back",
            "Original preservado ou restaurado após interrupção.",
            release=True,
        )

    def _mark_restored(self, original_id, restore_id):
        with self.library._transaction() as db:
            db.execute(
                "UPDATE file_operations SET state='restored',updated_at=?,message=? "
                "WHERE id=? AND state='completed'",
                (now(), f"Restaurado pela operação {restore_id}.", original_id),
            )

    def _recover_locked(self):
        for row in reversed(self.history()):
            manifest = json.loads(row["payload_json"])
            if row["state"] == "completed":
                if manifest.get("restore_of"):
                    self._mark_restored(manifest["restore_of"], manifest["id"])
                self._cleanup(manifest)
            elif row["state"] not in ("rolled_back", "restored"):
                try:
                    self._rollback(manifest)
                except Exception:
                    self._phase(
                        manifest,
                        "needs_recovery",
                        "Recuperação pendente; os arquivos e backups foram preservados.",
                    )

    def recover(self):
        with operation_lock(self.lock_path):
            self._recover_locked()
        return self.history()

    def restore(self, operation_id, *, backup_root=None):
        with operation_lock(self.lock_path):
            self._recover_locked()
            row = self.library.connection.execute(
                "SELECT * FROM file_operations WHERE id=?",
                (operation_id,),
            ).fetchone()
            if not row or row["state"] != "completed":
                raise OperationError("Esta operação não está disponível para restauração.")
            manifest = json.loads(row["payload_json"])
            old_item = manifest["item"]
            _, record = self.library._current_record(row["file_id"])
            if Path(record.path) != Path(old_item["destination"]):
                raise OperationError("Restaure primeiro as alterações mais recentes desta música.")
            source, destination = Path(record.path), Path(old_item["source"])
            if file_digest(source, self.stop) != manifest["output_hash"]:
                raise OperationError(
                    "O arquivo foi alterado externamente; restauração automática bloqueada."
                )
            if source != destination and destination.exists():
                try:
                    same = os.path.samefile(source, destination)
                except OSError:
                    same = False
                if not same:
                    raise OperationError(
                        "O nome original está ocupado; os dois arquivos serão preservados."
                    )
            draft = self.library.load_reviews([record])[0]
            report = next(iter(self.library.load_identifications([record])), None)
            from afinario.change_plan import PlanItem

            item = PlanItem(
                record,
                str(source),
                str(destination),
                manifest["output_hash"],
                directory_identity(source.parent),
                identity(source),
                {},
                digest(asdict(draft)),
                recognition_key(report),
            )
            root = Path(backup_root) if backup_root else self.library.path.parent / "backups"
            return self._execute(
                item,
                root,
                restore_of=operation_id,
                restore_from={
                    "path": manifest["backup"],
                    "sha256": old_item["source_sha256"],
                },
            )
