import threading
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.batches import BatchSession, PauseRequest, fail_batch
from afinario.cancellation import AnalysisCancelled
from afinario.config import app_paths
from afinario.library import LibraryError, LibraryStore
from afinario.lyrics import LyricsService, import_lyric, local_lyric, resolve_lyrics
from afinario.provider_cache import ProviderCache
from afinario.transport import Transport
from afinario.ui.library_worker import library_error


class LyricsWorker(QThread):
    batch_ready = Signal(str, str)
    result_ready = Signal(object)
    review_ready = Signal(object)
    failed = Signal(str)
    progress_ready = Signal(int, int)
    completed = Signal(int, int, bool)

    def __init__(
        self,
        requests,
        settings,
        options,
        path,
        parent=None,
        *,
        import_path=None,
        pasted=None,
        read_only=False,
        batch_id=None,
    ):
        super().__init__(parent)
        self.requests, self.settings, self.options, self.path = requests, settings, options, path
        self.import_path, self.pasted, self.read_only = import_path, pasted, read_only
        self.stop = threading.Event()
        self.pause_request = PauseRequest()
        self.batch_id = batch_id

    def pause(self):
        self.pause_request.pause()

    def cancel(self):
        self.stop.set()

    def run(self):
        completed = 0
        cache = transport = None
        session = None
        lock = ExitStack()
        owner = False
        try:
            cache = ProviderCache(Path(app_paths()["cache"]) / "lyrics-v1.sqlite3")
            transport = Transport(self.settings, cancelled=self.stop)
            service = LyricsService(transport, cache, self.stop)
            local = None
            if self.import_path:
                local = import_lyric(Path(self.import_path))
            elif self.pasted is not None:
                local = local_lyric(self.pasted)
            with LibraryStore(self.path) as library:
                payload = {
                    "options": asdict(self.options),
                    "import_path": self.import_path,
                    "pasted": self.pasted,
                    "read_only": self.read_only,
                }
                session = BatchSession(
                    library,
                    "lyrics",
                    payload,
                    [
                        (r.id, {"record": asdict(r), "artist": a, "title": t, "context": c})
                        for r, a, t, c in self.requests
                    ],
                    batch_id=self.batch_id,
                )
                self.batch_id = session.id
                lock.enter_context(session.running())
                owner = True
                self.batch_ready.emit(session.id, "running")
                rows = {row["item_key"]: row for row in session.items()}
                completed = sum(row["state"] == "completed" for row in rows.values())
                for report in library.load_lyrics(
                    [r for r, a, t, c in self.requests if rows[r.id]["state"] == "completed"]
                ):
                    self.result_ready.emit(report)
                for record, artist, title, context in self.requests:
                    if rows[record.id]["state"] == "completed":
                        continue
                    if self.stop.is_set() or self.pause_request.requested.is_set():
                        break
                    session.mark(record.id, "running")
                    try:
                        report = service.query(
                            record,
                            artist,
                            title,
                            context,
                            replace(self.options, refresh=False)
                            if rows[record.id]["state"] == "running"
                            else self.options,
                            local,
                            read_only=self.read_only,
                        )
                        previous = next(iter(library.load_lyrics([record])), None)
                        if (
                            previous is not None
                            and (local is not None or self.read_only)
                            and ((previous.artist, previous.title) == (report.artist, report.title))
                        ):
                            results = (*previous.results, *report.results)
                            status, assessments, reasons, recommended = resolve_lyrics(
                                results,
                                report.artist,
                                report.title,
                                record.duration,
                            )
                            report = replace(
                                report,
                                results=results,
                                status=status,
                                assessments=assessments,
                                reasons=reasons,
                                recommended_key=recommended,
                            )
                        library.save_lyrics(report, batch_id=session.id)
                        self.result_ready.emit(report)
                        self.review_ready.emit(library.load_reviews([record])[0])
                    except AnalysisCancelled:
                        break
                    except (OSError, ValueError, LibraryError) as exc:
                        # Local validation errors contain no provider credentials.
                        message = (
                            str(exc) if isinstance(exc, ValueError) else "Falha ao ler o arquivo."
                        )
                        self.failed.emit(f"{Path(record.path).name}: {message}")
                        session.mark(record.id, "failed", message)
                    completed += 1
                    self.progress_ready.emit(completed, len(self.requests))
                state = (
                    "cancelled"
                    if self.stop.is_set()
                    else ("paused" if self.pause_request.requested.is_set() else "completed")
                )
                session.finish(state)
                self.batch_ready.emit(session.id, state)
        except ValueError as exc:
            if owner:
                fail_batch(self.path, session.id, str(exc))
                self.batch_ready.emit(session.id, "failed")
            self.failed.emit(str(exc))
        except Exception as exc:
            if owner:
                fail_batch(self.path, session.id, library_error(exc))
                self.batch_ready.emit(session.id, "failed")
            self.failed.emit(library_error(exc))
        finally:
            lock.close()
            for resource in (cache, transport):
                if resource is not None:
                    resource.close()
            self.completed.emit(completed, len(self.requests), self.stop.is_set())
