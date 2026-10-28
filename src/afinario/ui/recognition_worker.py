import threading
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.audd import AudDBudget
from afinario.cancellation import AnalysisCancelled
from afinario.config import Settings, app_paths
from afinario.identification import IdentificationReport, IdentificationService, RecognitionOptions
from afinario.inventory import InventoryRecord
from afinario.provider_cache import ProviderCache
from afinario.resolver import Decision, DecisionStatus
from afinario.transport import Transport


class IdentificationWorker(QThread):
    stage_ready = Signal(str, str)
    result_ready = Signal(object)
    item_cancelled = Signal(str)
    progress_ready = Signal(int, int)
    analysis_complete = Signal(int, int, bool)
    warning_ready = Signal(str)
    budget_ready = Signal(int, int)

    def __init__(
        self,
        records: list[InventoryRecord],
        settings: Settings,
        options: RecognitionOptions,
        parent=None,
    ):
        super().__init__(parent)
        self.records, self.settings, self.options = records, settings, options
        self.stop = threading.Event()

    def cancel(self) -> None:
        self.stop.set()

    def run(self) -> None:
        cache = None
        transport = None
        completed = 0
        budget = AudDBudget(self.settings.audd_max_requests)
        try:
            cache = ProviderCache(Path(app_paths()["cache"]) / "recognition-v1.sqlite3")
            transport = Transport(self.settings, cancelled=self.stop)
            if not cache.persistent_available:
                self.warning_ready.emit("Cache em disco indisponível; usando cache desta sessão.")
            service = IdentificationService(self.settings, transport, cache, self.stop, budget)
            remaining = iter(self.records)
            with ThreadPoolExecutor(
                max_workers=self.settings.analysis_workers, thread_name_prefix="afinario-track"
            ) as pool:
                pending = {}

                def submit_next():
                    if self.stop.is_set():
                        return
                    record = next(remaining, None)
                    if record is not None:
                        future = pool.submit(
                            service.identify,
                            record,
                            self.options,
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
                        self.result_ready.emit(result)
                        completed += 1
                        self.progress_ready.emit(completed, len(self.records))
                        self.budget_ready.emit(budget.used, budget.limit)
                        submit_next()
        except Exception:
            self.warning_ready.emit(
                "Não foi possível iniciar ou continuar o reconhecimento. "
                "Confira as configurações e tente novamente."
            )
        finally:
            self.budget_ready.emit(budget.used, budget.limit)
            for resource in (transport, cache):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        self.warning_ready.emit("Falha ao encerrar um recurso do reconhecimento.")
            self.analysis_complete.emit(completed, len(self.records), self.stop.is_set())
