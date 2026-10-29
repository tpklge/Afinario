from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from afinario.config import Settings
from afinario.library import LibraryPreferences, default_library_path
from afinario.ui.library_worker import SaveConfigurationWorker


class RecognitionSettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None, *, library_path=None, preferences=None):
        super().__init__(parent)
        self.settings = settings
        self.library_path = library_path or default_library_path()
        self.preferences = preferences or LibraryPreferences()
        self.worker = None
        self._saved = None
        self.setWindowTitle("Serviços e ferramentas de reconhecimento")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        note = QLabel(
            "As credenciais serão salvas no cofre do sistema deste usuário, fora do projeto. "
            "Deixe um campo vazio e salve para remover a chave desse serviço."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.key = QLineEdit(settings.acoustid_key or "")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Chave de aplicação AcoustID")
        form.addRow("Chave AcoustID", self.key)
        key_help = QLabel(
            "Use a chave de aplicação (client). "
            '<a href="https://acoustid.org/webservice#api-keys">'
            "Ver como obter a chave AcoustID</a>."
        )
        key_help.setOpenExternalLinks(True)
        key_help.setWordWrap(True)
        form.addRow(key_help)
        self.audd_token = QLineEdit(settings.audd_token or "")
        self.audd_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.audd_token.setPlaceholderText("Token do plano AudD")
        form.addRow("Token AudD", self.audd_token)
        self.audd_limit = QSpinBox()
        self.audd_limit.setRange(0, 100000)
        self.audd_limit.setValue(settings.audd_max_requests)
        self.audd_limit.setToolTip("0 bloqueia novas consultas ao AudD, mesmo com token salvo.")
        form.addRow("Limite AudD por execução (0 bloqueia)", self.audd_limit)
        self.tools = {}
        for name in ("fpcalc", "ffmpeg", "ffprobe"):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            value = QLineEdit(getattr(settings, name))
            browse = QPushButton("Escolher…")
            browse.clicked.connect(lambda _, field=value: self._browse(field))
            row.addWidget(value, 1)
            row.addWidget(browse)
            self.tools[name] = value
            form.addRow(name, container)
        self.workers = QSpinBox()
        self.workers.setRange(1, 4)
        self.workers.setValue(settings.analysis_workers)
        self.workers.setToolTip("As cotas de cada provedor continuam compartilhadas pelo lote.")
        form.addRow("Músicas em paralelo", self.workers)
        self.shazam_interval = QDoubleSpinBox()
        self.shazam_interval.setRange(1, 300)
        self.shazam_interval.setSuffix(" s")
        self.shazam_interval.setValue(settings.shazam_interval_seconds)
        self.shazam_interval.setToolTip(
            "Intervalo local conservador; não é uma cota oficial do Shazam."
        )
        form.addRow("Intervalo mínimo ShazamIO", self.shazam_interval)
        layout.addLayout(form)
        self.save_status = QLabel()
        self.save_status.setWordWrap(True)
        layout.addWidget(self.save_status)
        buttons = self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar configurações")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar executável")
        if path:
            field.setText(path)

    def accept(self):
        if self.worker is not None:
            return
        settings = self.selected_settings()
        self.worker = SaveConfigurationWorker(
            self.library_path,
            self.preferences,
            settings,
            self,
        )
        self.worker.saved.connect(self._on_saved)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._finished)
        self.buttons.setEnabled(False)
        self._enable_fields(False)
        self.save_status.setText("Salvando no cofre do sistema…")
        self.worker.start()

    def _on_saved(self, settings):
        self._saved = settings

    def _on_failed(self, message):
        self.save_status.setText(message)

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.buttons.setEnabled(True)
        self._enable_fields(True)
        if self._saved is not None:
            super().accept()

    def reject(self):
        if self.worker is None:
            super().reject()

    def _enable_fields(self, enabled):
        for widget in (
            self.key,
            self.audd_token,
            self.audd_limit,
            self.workers,
            self.shazam_interval,
            *self.tools.values(),
        ):
            widget.setEnabled(enabled)

    def selected_settings(self) -> Settings:
        if self._saved is not None:
            return self._saved
        return replace(
            self.settings,
            acoustid_key=self.key.text().strip() or None,
            audd_token=self.audd_token.text().strip() or None,
            audd_max_requests=self.audd_limit.value(),
            analysis_workers=self.workers.value(),
            shazam_interval_seconds=self.shazam_interval.value(),
            **{name: field.text().strip() or name for name, field in self.tools.items()},
        )
