import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from afinario.review import FIELD_LABELS

STATE_LABELS = {
    "ready": "Pronto",
    "blocked": "Bloqueado",
    "noop": "Sem alteração",
    "completed": "Concluído",
    "restored": "Restaurado",
    "rolled_back": "Original recuperado",
    "needs_recovery": "Recuperação pendente",
    "preparing": "Preparando",
    "backup_ready": "Backup verificado",
    "prepared": "Cópia validada",
    "staging": "Preparando troca",
    "staged": "Origem preservada",
    "installing": "Finalizando",
    "installed": "Validando destino",
}


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.verticalHeader().hide()
    return widget


class OperationsPanel(QWidget):
    plan_requested = Signal(bool)
    apply_requested = Signal(str)
    restore_requested = Signal(str)
    recovery_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan = None
        self.history = []
        self._busy = False
        layout = QVBoxLayout(self)
        self.auto_rename = QCheckBox(
            "Renomear após identificar quando 2 ou mais fontes concordarem"
        )
        self.auto_rename.setChecked(True)
        self.auto_rename.setToolTip(
            "Renomear com backup após concordância de reconhecedores independentes."
        )
        layout.addWidget(self.auto_rename)
        self.auto_tags = QCheckBox("Preencher artista e título quando as fontes concordarem")
        self.auto_tags.setChecked(True)
        self.auto_lyrics = QCheckBox(
            "Buscar e aplicar letras compatíveis após validar artista e título"
        )
        self.auto_lyrics.setChecked(True)
        layout.addWidget(self.auto_tags)
        layout.addWidget(self.auto_lyrics)
        backup_row = QHBoxLayout()
        backup_row.addWidget(QLabel("Pasta de backups"))
        self.backup_directory = QLineEdit()
        self.backup_directory.setPlaceholderText("Padrão: backups junto ao banco da biblioteca")
        self.backup_browse = QPushButton("Escolher…")
        self.backup_browse.clicked.connect(self._choose_backup)
        backup_row.addWidget(self.backup_directory, 1)
        backup_row.addWidget(self.backup_browse)
        layout.addLayout(backup_row)
        self.pages = QTabWidget()
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        actions = QHBoxLayout()
        self.preview_selected = QPushButton("Prévia das selecionadas")
        self.preview_all = QPushButton("Prévia da biblioteca")
        self.apply_button = QPushButton("Aplicar itens prontos com backup")
        self.apply_button.setEnabled(False)
        self.preview_selected.clicked.connect(lambda: self.plan_requested.emit(True))
        self.preview_all.clicked.connect(lambda: self.plan_requested.emit(False))
        self.apply_button.clicked.connect(self._apply)
        for button in (self.preview_selected, self.preview_all, self.apply_button):
            actions.addWidget(button)
        preview_layout.addLayout(actions)
        note = QLabel(
            "A prévia inclui campos aprovados e alterações automáticas habilitadas com evidências. "
            "Colisões recebem sufixo ou ficam bloqueadas. Os arquivos permanecem na mesma pasta."
        )
        note.setWordWrap(True)
        preview_layout.addWidget(note)
        self.preview = table(("Origem", "Destino", "Campos", "Situação / motivo"))
        for column, width in enumerate((220, 260, 150, 230)):
            self.preview.setColumnWidth(column, width)
        self.preview.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.preview.setAccessibleName("Prévia das alterações")
        preview_layout.addWidget(self.preview)
        self.pages.addTab(preview, "Prévia e aplicação")
        backups = QWidget()
        backup_layout = QVBoxLayout(backups)
        actions = QHBoxLayout()
        self.restore_button = QPushButton("Restaurar operação selecionada")
        self.recover_button = QPushButton("Verificar recuperação")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self._restore)
        self.recover_button.clicked.connect(self.recovery_requested.emit)
        actions.addWidget(self.restore_button)
        actions.addWidget(self.recover_button)
        backup_layout.addLayout(actions)
        note = QLabel(
            "Restaurar recupera nome e bytes originais. "
            "Alterações externas e nomes ocupados bloqueiam a restauração."
        )
        note.setWordWrap(True)
        backup_layout.addWidget(note)
        self.backups = table(("Data", "Ação", "Situação", "Origem → destino", "Backup / motivo"))
        for column, width in enumerate((145, 85, 150, 300, 300)):
            self.backups.setColumnWidth(column, width)
        self.backups.setAccessibleName("Histórico de alterações e backups")
        self.backups.itemSelectionChanged.connect(self._update_restore)
        backup_layout.addWidget(self.backups)
        self.pages.addTab(backups, "Backups e restauração")
        layout.addWidget(self.pages)
        self.message = QLabel("Gere uma prévia para conferir as alterações antes de aplicar.")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def _choose_backup(self):
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta de backups")
        if path:
            self.backup_directory.setText(path)

    def show_plan(self, plan):
        self.plan = plan
        self.preview.setRowCount(len(plan.items))
        for row, item in enumerate(plan.items):
            names = [
                FIELD_LABELS[k] + (" (automático)" if k in item.automatic_fields else "")
                for k in item.changes
            ]
            if item.source != item.destination:
                names.append("Nome automático" if item.automatic_name else "Nome aprovado")
            values = (
                Path(item.source).name,
                Path(item.destination).name,
                ", ".join(names),
                STATE_LABELS[item.status] + (": " + item.message if item.message else ""),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(item.source + "\n→ " + item.destination + "\n" + item.message)
                self.preview.setItem(row, column, cell)
        self.message.setText(
            f"Prévia salva: {len(plan.ready)} item(ns) pronto(s) de {len(plan.items)}."
        )
        self.apply_button.setEnabled(bool(plan.ready) and not self._busy)

    def show_history(self, rows):
        self.history = rows
        self.backups.setRowCount(len(rows))
        for index, row in enumerate(rows):
            payload = json.loads(row["payload_json"])
            item = payload["item"]
            values = (
                row["created_at"],
                "Restaurar" if row["kind"] == "restore" else "Aplicar",
                STATE_LABELS.get(row["state"], row["state"]),
                Path(item["source"]).name + " → " + Path(item["destination"]).name,
                payload["backup"] + ("\n" + row["message"] if row["message"] else ""),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.backups.setItem(index, column, cell)
        self._update_restore()

    def set_busy(self, busy):
        self._busy = busy
        for widget in (
            self.auto_rename,
            self.auto_tags,
            self.auto_lyrics,
            self.backup_directory,
            self.backup_browse,
            self.preview_selected,
            self.preview_all,
            self.recover_button,
        ):
            widget.setEnabled(not busy)
        self.apply_button.setEnabled(not busy and self.plan is not None and bool(self.plan.ready))
        self._update_restore()

    def invalidate_plan(self):
        self.plan = None
        self.apply_button.setEnabled(False)

    def _update_restore(self):
        row = self.backups.currentRow()
        self.restore_button.setEnabled(
            not self._busy
            and 0 <= row < len(self.history)
            and self.history[row]["state"] == "completed"
        )

    def _apply(self):
        if self.plan:
            self.apply_requested.emit(self.plan.id)

    def _restore(self):
        row = self.backups.currentRow()
        if 0 <= row < len(self.history):
            self.restore_requested.emit(self.history[row]["id"])
