import threading
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.inventory import InventoryRecord, ScanIssue, ScanSummary, scan


class ScanWorker(QThread):
    records_ready = Signal(list)
    progress_ready = Signal(object)
    issue_ready = Signal(object)
    scan_complete = Signal(object)
    scan_failed = Signal(str)

    def __init__(self, roots: list[Path], recursive: bool, formats: frozenset[str], parent=None):
        super().__init__(parent)
        self.roots, self.recursive, self.formats = roots, recursive, formats
        self.stop = threading.Event()
        self._batch: list[InventoryRecord] = []
        self._last_flush = 0.0

    def cancel(self) -> None:
        self.stop.set()

    def _record(self, record: InventoryRecord) -> None:
        self._batch.append(record)

    def _issue(self, issue: ScanIssue) -> None:
        self.issue_ready.emit(issue)

    def _progress(self, summary: ScanSummary) -> None:
        if time.monotonic() - self._last_flush >= 0.1 or len(self._batch) >= 50:
            self._flush()
            self.progress_ready.emit(replace(summary))

    def _flush(self) -> None:
        if self._batch:
            self.records_ready.emit(self._batch)
            self._batch = []
        self._last_flush = time.monotonic()

    def run(self) -> None:
        try:
            result = scan(
                self.roots,
                recursive=self.recursive,
                formats=self.formats,
                cancelled=self.stop,
                on_record=self._record,
                on_issue=self._issue,
                on_progress=self._progress,
            )
            self._flush()
            self.scan_complete.emit(result)
        except Exception:
            self._flush()
            self.scan_failed.emit(
                "A varredura não pôde ser concluída. Os resultados lidos foram mantidos."
            )
