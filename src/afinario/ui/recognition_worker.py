import threading
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.audd import AudDBudget
from afinario.batches import BatchSession, PauseRequest
from afinario.cancellation import AnalysisCancelled
from afinario.config import Settings, app_paths
from afinario.identification import (
    IdentificationReport,
    IdentificationService,
    RecognitionOptions,
    compare_history,
)
from afinario.inventory import InventoryRecord
from afinario.library import LibraryPreferences, LibraryStore, _record
from afinario.provider_cache import ProviderCache
from afinario.resolver import Decision, DecisionStatus
from afinario.transport import Transport
from afinario.ui.library_worker import library_error


class IdentificationWorker(QThread):
    batch_ready = Signal(str, str)
    stage_ready = Signal(str, str)
    result_ready = Signal(object)
    item_cancelled = Signal(str)
    progress_ready = Signal(int, int)
    analysis_complete = Signal(int, int, bool)
    warning_ready = Signal(str)
    analysis_failed = Signal(str)
    budget_ready = Signal(int, int)

    def __init__(
        self,
        records: list[InventoryRecord],
        settings: Settings,
        options: RecognitionOptions,
        parent=None,
        *,
        library_path: Path | None = None,
        preferences: LibraryPreferences | None = None,
        batch_id=None,
    ):
        super().__init__(parent)
        self.records, self.settings, self.options = records, settings, options
        self.stop = threading.Event()
        self.library_path = library_path
        self.preferences = preferences or LibraryPreferences(settings=settings.public_data())
        self.batch_id = batch_id
        self.pause_request = PauseRequest()

    def pause(self):
        self.pause_request.pause()

    def cancel(self) -> None:
        self.stop.set()

    def run(self) -> None:
        cache = None
        transport = None
        library = None
        run_id = None
        completed = 0
        session = None
        owner = False
        batch_lock = ExitStack()
        budget = AudDBudget(self.settings.audd_max_requests)
        try:
            library = LibraryStore(self.library_path)
            if self.batch_id:
                session = BatchSession(library, "recognition", batch_id=self.batch_id)
                self.options = RecognitionOptions(**session.payload["options"])
                restored = Settings.from_data(session.payload["settings"])
                self.settings = replace(
                    self.settings,
                    audd_max_requests=restored.audd_max_requests,
                )
                self.records = [_record(row["payload_json"]) for row in session.items()]
            else:
                run_id = library.start_recognition(self.records, self.options, self.preferences)
                session = BatchSession(
                    library,
                    "recognition",
                    {
                        "run_id": run_id,
                        "options": asdict(self.options),
                        "settings": self.settings.public_data(),
                    },
                    [(r.id, asdict(r)) for r in self.records],
                )
            self.batch_id = session.id
            run_id = session.payload["run_id"]
            budget = AudDBudget(
                self.settings.audd_max_requests,
                used=session.row["audd_used"],
                on_reserve=session.reserve_audd,
            )
            batch_lock.enter_context(session.running())
            owner = True
            self.batch_ready.emit(session.id, "running")
            cache = ProviderCache(Path(app_paths()["cache"]) / "recognition-v1.sqlite3")
            transport = Transport(self.settings, cancelled=self.stop)
            if not cache.persistent_available:
                self.warning_ready.emit("Cache em disco indisponível; usando cache desta sessão.")
            service = IdentificationService(self.settings, transport, cache, self.stop, budget)
            checkpoints = {r["item_key"]: r for r in session.items()}
            completed = sum(r["state"] == "completed" for r in checkpoints.values())
            for report in library.load_identifications(
                [r for r in self.records if checkpoints[r.id]["state"] == "completed"]
            ):
                self.result_ready.emit(report)
            remaining = iter(r for r in self.records if checkpoints[r.id]["state"] != "completed")
            with ThreadPoolExecutor(
                max_workers=self.settings.analysis_workers, thread_name_prefix="afinario-track"
            ) as pool:
                pending = {}

                def submit_next():
                    if self.stop.is_set() or self.pause_request.requested.is_set():
                        return
                    record = next(remaining, None)
                    if record is not None:
                        session.mark(record.id, "running")
                        options = (
                            replace(self.options, refresh=False)
                            if checkpoints[record.id]["state"] == "running"
                            else self.options
                        )
                        future = pool.submit(
                            service.identify,
                            record,
                            options,
                            lambda stage, file_id=record.id: self.stage_ready.emit(file_id, stage),
                        )
                        pending[future] = record

                for _ in range(self.settings.analysis_workers):
                    submit_next()
                while pending:
                    if self.stop.is_set():
                        for future in pending:
                            future.cancel()
                    done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    for future in done:
                        record = pending.pop(future)
                        try:
                            result = future.result()
                        except (AnalysisCancelled, CancelledError):
                            self.item_cancelled.emit(record.id)
                            continue
                        except Exception:
                            result = IdentificationReport(
                                record.id,
                                record.path,
                                Decision(
                                    DecisionStatus.PENDING,
                                    reasons=(
                                        "Falha nesta análise. Confira as ferramentas "
                                        "e tente novamente.",
                                    ),
                                ),
                            )
                        # Publish only after commit. All DB work stays on this QThread,
                        # while provider threads deal exclusively with audio and HTTP.
                        if result.source_sha256:
                            result = compare_history(
                                result, library.identification_history(record, result.source_sha256)
                            )
                        library.save_identification(
                            run_id,
                            result,
                            secrets=(
                                self.settings.acoustid_key or "",
                                self.settings.audd_token or "",
                            ),
                            batch_id=session.id,
                        )
                        self.result_ready.emit(result)
                        completed += 1
                        self.progress_ready.emit(completed, len(self.records))
                        self.budget_ready.emit(budget.used, budget.limit)
                        submit_next()
            state = (
                "cancelled"
                if self.stop.is_set()
                else ("paused" if self.pause_request.requested.is_set() else "completed")
            )
            session.finish(state)
            self.batch_ready.emit(session.id, state)
            if state != "paused":
                library.finish_run(
                    run_id,
                    "cancelled" if state == "cancelled" else "completed",
                    {
                        "completed": completed,
                        "total": len(self.records),
                        "audd_reserved": budget.used,
                    },
                )
        except Exception as exc:
            if session is not None and owner:
                try:
                    session.finish("failed", library_error(exc))
                    self.batch_ready.emit(session.id, "failed")
                except Exception:
                    pass
            self.analysis_failed.emit(library_error(exc))
        finally:
            batch_lock.close()
            self.budget_ready.emit(budget.used, budget.limit)
            for resource in (transport, cache, library):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        self.warning_ready.emit("Falha ao encerrar um recurso do reconhecimento.")
            self.analysis_complete.emit(completed, len(self.records), self.stop.is_set())
