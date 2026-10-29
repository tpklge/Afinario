import threading
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.batches import BatchSession, PauseRequest, batches, fail_batch
from afinario.library import LibraryStore
from afinario.operations import OperationService, message_for


class OperationsWorker(QThread):
    batch_ready = Signal(str, str)
    ready = Signal(object)
    failed = Signal(str)
    stage_ready = Signal(str, str, str)

    def __init__(self, path, settings, preferences, task, parent=None, **arguments):
        super().__init__(parent)
        self.path, self.settings, self.preferences = path, settings, preferences
        self.task, self.arguments = task, arguments
        self.stop = threading.Event()
        self.pause_request = PauseRequest()

    def pause(self):
        self.pause_request.pause()

    def cancel(self):
        self.stop.set()

    def run(self):
        lock = ExitStack()
        owner = False
        try:
            with LibraryStore(self.path) as library:
                service = OperationService(
                    library,
                    self.settings,
                    stop=self.stop,
                    on_event=self.stage_ready.emit,
                )
                library.save_preferences(self.preferences)
                backup = (
                    Path(self.preferences.backup_directory)
                    if self.preferences.backup_directory
                    else None
                )
                plan, results = None, []
                session = None
                paused = False
                stage = self.arguments.get("stage", "identity")
                if self.task in ("plan", "auto"):
                    if not self.arguments.get("batch_id"):
                        plan = service.plan(
                            self.arguments["records"],
                            automatic_only=self.task == "auto",
                            consensus_names=self.preferences.auto_rename_agreement
                            if self.task == "auto"
                            else True,
                            auto_tags=self.preferences.auto_tags_agreement and stage != "lyrics",
                            auto_lyrics=self.preferences.auto_lyrics
                            and (self.task == "plan" or stage == "lyrics"),
                        )
                if self.task in ("auto", "apply"):
                    if self.arguments.get("batch_id"):
                        session = BatchSession(
                            library, "apply", batch_id=self.arguments["batch_id"]
                        )
                        stage = session.payload.get("stage", "identity")
                        self.task = session.payload["task"]
                    else:
                        plan_id = plan.id if plan else self.arguments["plan_id"]
                        from afinario.change_plan import plan_from_json

                        if plan is None:
                            plan = plan_from_json(
                                library.connection.execute(
                                    "SELECT payload_json FROM change_plans WHERE id=?", (plan_id,)
                                ).fetchone()[0]
                            )
                        session = BatchSession(
                            library,
                            "apply",
                            {"plan_id": plan_id, "task": self.task, "stage": stage},
                            [(i.record.id, asdict(i.record)) for i in plan.ready],
                        )
                    lock.enter_context(session.running())
                    owner = True
                    self.batch_ready.emit(session.id, "running")
                    results = service.apply(
                        session.payload["plan_id"],
                        backup_root=backup,
                        batch=session,
                        pause=self.pause_request,
                    )
                    paused = self.pause_request.requested.is_set() and not self.stop.is_set()
                    state = (
                        "cancelled" if self.stop.is_set() else ("paused" if paused else "completed")
                    )
                    session.finish(state)
                    self.batch_ready.emit(session.id, state)
                elif self.task == "restore":
                    results = [service.restore(self.arguments["operation_id"], backup_root=backup)]
                elif self.task == "recover":
                    service.recover()
                self.ready.emit(
                    {
                        "task": self.task,
                        "plan": plan,
                        "results": results,
                        "state": library.load(),
                        "history": service.history(),
                        "cancelled": self.stop.is_set(),
                        "paused": paused,
                        "stage": stage,
                        "batches": batches(library),
                    }
                )
        except Exception as exc:
            if owner:
                fail_batch(self.path, session.id, message_for(exc))
                self.batch_ready.emit(session.id, "failed")
            self.failed.emit(message_for(exc))
        finally:
            lock.close()
