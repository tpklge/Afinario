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


class RecognitionSettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Serviços e ferramentas de reconhecimento")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        note = QLabel("As configurações e credenciais ajustadas aqui valem para esta sessão.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.key = QLineEdit(settings.acoustid_key or "")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Chave de aplicação AcoustID")
        form.addRow("Chave AcoustID", self.key)
        self.audd_token = QLineEdit(settings.audd_token or "")
        self.audd_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.audd_token.setPlaceholderText("Token do plano AudD")
        form.addRow("Token AudD", self.audd_token)
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
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Usar nesta sessão")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar executável")
        if path:
            field.setText(path)

    def selected_settings(self) -> Settings:
        return replace(
            self.settings,
            acoustid_key=self.key.text().strip() or None,
            audd_token=self.audd_token.text().strip() or None,
            analysis_workers=self.workers.value(),
            shazam_interval_seconds=self.shazam_interval.value(),
            **{name: field.text().strip() or name for name, field in self.tools.items()},
        )
