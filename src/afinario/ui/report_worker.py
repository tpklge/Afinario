from PySide6.QtCore import QThread, Signal

from afinario.batches import batches
from afinario.library import LibraryStore
from afinario.reports import export_report


class ReportWorker(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(
        self, path, parent=None, *, destination=None, file_ids=None, secrets=(), batch_id=None
    ):
        super().__init__(parent)
        self.path, self.destination, self.file_ids, self.secrets = (
            path,
            destination,
            file_ids,
            secrets,
        )
        self.batch_id = batch_id

    def run(self):
        try:
            with LibraryStore(self.path) as library:
                if self.batch_id:
                    batch = dict(
                        library.connection.execute(
                            "SELECT * FROM task_batches WHERE id=?", (self.batch_id,)
                        ).fetchone()
                    )
                    items = [
                        dict(r)
                        for r in library.connection.execute(
                            "SELECT * FROM task_items WHERE batch_id=? ORDER BY ordinal",
                            (self.batch_id,),
                        )
                    ]
                    records = [library._current_record(item["item_key"])[1] for item in items]
                    self.ready.emit(
                        {
                            "resume_batch": batch,
                            "items": items,
                            "context": {
                                "records": records,
                                "identifications": library.load_identifications(records),
                                "lyrics": library.load_lyrics(records),
                                "reviews": library.load_reviews(records),
                            },
                        }
                    )
                    return
                count = (
                    export_report(
                        library, self.destination, file_ids=self.file_ids, secrets=self.secrets
                    )
                    if self.destination
                    else None
                )
                self.ready.emit(
                    {"count": count, "destination": self.destination, "batches": batches(library)}
                )
        except FileExistsError:
            self.failed.emit(
                "O relatório já existe. Escolha outro nome para preservar o arquivo existente."
            )
        except Exception:
            self.failed.emit(
                "Não foi possível gerar o relatório. Confira o formato, espaço e permissões."
            )
