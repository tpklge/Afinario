import threading
import time
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.batches import BatchSession, PauseRequest
from afinario.inventory import InventoryRecord, ScanIssue, ScanSummary, scan
from afinario.library import LibraryPreferences, LibraryStore, _record
from afinario.ui.library_worker import library_error


class ScanWorker(QThread):
    batch_ready = Signal(str, str)
    records_ready = Signal(list)
    progress_ready = Signal(object)
    issue_ready = Signal(object)
    scan_complete = Signal(object)
    scan_failed = Signal(str)
    identifications_ready = Signal(list)
    lyrics_ready = Signal(list)
    reviews_ready = Signal(list)

    def __init__(
        self,
        roots: list[Path],
        recursive: bool,
        formats: frozenset[str],
        parent=None,
        *,
        library_path: Path | None = None,
        preferences: LibraryPreferences | None = None,
        batch_id=None,
    ):
        super().__init__(parent)
        self.roots, self.recursive, self.formats = roots, recursive, formats
        self.stop = threading.Event()
        self._batch: list[InventoryRecord] = []
        self._last_flush = 0.0
        self.library_path = library_path
        self.preferences = preferences or LibraryPreferences(
            roots=tuple(str(root) for root in roots),
            recursive=recursive,
            formats=tuple(sorted(formats)),
        )
        self.library = None
        self.run_id = None
        self.batch_id = batch_id
        self.pause_request = PauseRequest()
        self._cancelled = False
        self.session = None

    def pause(self):
        self.pause_request.pause()
        self.stop.set()

    def cancel(self) -> None:
        self._cancelled = True
        self.stop.set()

    def _record(self, record: InventoryRecord) -> None:
        self._batch.append(record)

    def _issue(self, issue: ScanIssue) -> None:
        self.library.save_scan_issue(self.run_id, issue)
        self.issue_ready.emit(issue)

    def _progress(self, summary: ScanSummary) -> None:
        if time.monotonic() - self._last_flush >= 0.1 or len(self._batch) >= 50:
            self._flush()
            self.progress_ready.emit(replace(summary))

    def _flush(self) -> None:
        if self._batch:
            records = self.library.save_scan_records(
                self.run_id, self._batch, batch_id=self.batch_id
            )
            reports = self.library.load_identifications(records)
            self.records_ready.emit(records)
            self.identifications_ready.emit(reports)
            self.lyrics_ready.emit(self.library.load_lyrics(records))
            self.reviews_ready.emit(self.library.load_reviews(records))
            self._batch = []
        self._last_flush = time.monotonic()

    def run(self) -> None:
        lock = ExitStack()
        owner = False
        try:
            self.library = LibraryStore(self.library_path)
            if self.batch_id:
                self.session = BatchSession(self.library, "scan", batch_id=self.batch_id)
                self.run_id = self.session.payload["run_id"]
            else:
                self.run_id = self.library.start_scan(self.preferences)
                self.session = BatchSession(
                    self.library,
                    "scan",
                    {
                        "run_id": self.run_id,
                        "roots": [str(p) for p in self.roots],
                        "recursive": self.recursive,
                        "formats": sorted(self.formats),
                    },
                )
                self.batch_id = self.session.id
            lock.enter_context(self.session.running())
            owner = True
            self.batch_ready.emit(self.batch_id, "running")
            known = {r.path: r for r in (_record(i["payload_json"]) for i in self.session.items())}
            result = scan(
                self.roots,
                recursive=self.recursive,
                formats=self.formats,
                cancelled=self.stop,
                on_record=self._record,
                on_issue=self._issue,
                on_progress=self._progress,
                known_records=known,
            )
            self._flush()
            state = (
                "paused"
                if self.pause_request.requested.is_set() and not self._cancelled
                else ("cancelled" if result.cancelled else "completed")
            )
            self.session.finish(state)
            self.batch_ready.emit(self.batch_id, state)
            if state != "paused":
                self.library.finish_run(
                    self.run_id, "cancelled" if result.cancelled else "completed", asdict(result)
                )
            self.scan_complete.emit(result)
        except Exception as exc:
            if self.session is not None and owner:
                try:
                    self.session.finish("failed", library_error(exc))
                    self.batch_ready.emit(self.batch_id, "failed")
                except Exception:
                    pass
            self.scan_failed.emit(library_error(exc))
        finally:
            lock.close()
            if self.library is not None:
                self.library.close()
