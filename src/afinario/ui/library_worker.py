from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from afinario.batches import batches
from afinario.credentials import CredentialError, CredentialStore
from afinario.library import LibraryError, LibraryPreferences, LibraryStore
from afinario.operations import OperationService, message_for


def library_error(exc: Exception) -> str:
    detail = (
        str(exc) if isinstance(exc, LibraryError) else "Falha ao acessar os dados da biblioteca."
    )
    return detail + " Os dados existentes foram preservados. Confira o local do banco."


class LoadLibraryWorker(QThread):
    loaded = Signal(object)
    failed = Signal(str)
    credentials_ready = Signal(object)
    credentials_failed = Signal(str)
    history_ready = Signal(object)
    batches_ready = Signal(object)

    def __init__(self, path: Path, parent=None, *, settings=None):
        super().__init__(parent)
        self.path = path
        self.settings = settings

    def run(self):
        try:
            with LibraryStore(self.path) as library:
                service = OperationService(library, self.settings)
                try:
                    self.history_ready.emit(service.recover())
                except OSError as exc:
                    self.credentials_failed.emit(message_for(exc))
                    self.history_ready.emit(service.history())
                if self.settings is not None:
                    try:
                        self.credentials_ready.emit(CredentialStore().apply(self.settings))
                    except CredentialError as exc:
                        self.credentials_failed.emit(str(exc))
                self.loaded.emit(library.load())
                self.batches_ready.emit(batches(library))
        except Exception as exc:
            self.failed.emit(library_error(exc))


class SavePreferencesWorker(QThread):
    failed = Signal(str)

    def __init__(self, path: Path, preferences: LibraryPreferences, parent=None):
        super().__init__(parent)
        self.path, self.preferences = path, preferences

    def run(self):
        try:
            with LibraryStore(self.path) as library:
                library.save_preferences(self.preferences)
        except Exception as exc:
            self.failed.emit(library_error(exc))


class SaveConfigurationWorker(QThread):
    saved = Signal(object)
    failed = Signal(str)

    def __init__(self, path, preferences, settings, parent=None):
        super().__init__(parent)
        self.path, self.preferences, self.settings = path, preferences, settings

    def run(self):
        credentials_saved = False
        try:
            CredentialStore().save(self.settings)
            credentials_saved = True
            with LibraryStore(self.path) as library:
                library.save_preferences(
                    replace(
                        self.preferences,
                        settings=self.settings.public_data(),
                    )
                )
            self.saved.emit(self.settings)
        except CredentialError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            message = library_error(exc)
            if credentials_saved:
                message += (
                    " As credenciais foram salvas no cofre; tente salvar os parâmetros novamente."
                )
            self.failed.emit(message)
