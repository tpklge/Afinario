from PySide6.QtCore import QThread, Signal

from afinario.library import LibraryStore
from afinario.ui.library_worker import library_error


class SaveReviewsWorker(QThread):
    saved = Signal(object)
    failed = Signal(str)

    def __init__(self, path, drafts, parent=None):
        super().__init__(parent)
        self.path, self.drafts = path, drafts

    def run(self):
        try:
            with LibraryStore(self.path) as library:
                for draft in self.drafts:
                    self.saved.emit(library.save_review(draft))
        except Exception as exc:
            self.failed.emit(library_error(exc))
