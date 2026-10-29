from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from afinario.ui.operations_panel import table

LABELS = {
    "scan": "Varredura",
    "recognition": "Identificação",
    "lyrics": "Letras",
    "apply": "Aplicação",
    "running": "Em execução/interrompido",
    "paused": "Pausado",
    "completed": "Concluído",
    "failed": "Falhou",
    "cancelled": "Cancelado",
}


class BatchesPanel(QWidget):
    resume_requested = Signal(object)
    export_requested = Signal(bool)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.busy = False
        layout = QVBoxLayout(self)
        note = QLabel(
            "Pausar aguarda as músicas em andamento e salva o lote. "
            "Retome aqui, inclusive após reabrir o aplicativo."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.resume = QPushButton("Retomar lote selecionado")
        self.refresh = QPushButton("Atualizar lotes")
        self.export_all = QPushButton("Exportar biblioteca…")
        self.export_selected = QPushButton("Exportar músicas selecionadas…")
        for button in (self.resume, self.refresh, self.export_all, self.export_selected):
            row.addWidget(button)
        layout.addLayout(row)
        self.table = table(("Início", "Tipo", "Situação", "Processados", "Uso AudD", "Motivo"))
        for column, width in enumerate((160, 110, 180, 100, 90, 220)):
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table)
        self.table.itemSelectionChanged.connect(self._actions)
        self.resume.clicked.connect(self._resume)
        self.refresh.clicked.connect(self.refresh_requested.emit)
        self.export_all.clicked.connect(lambda: self.export_requested.emit(False))
        self.export_selected.clicked.connect(lambda: self.export_requested.emit(True))
        self._actions()

    def show_batches(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            failed = row.get("failed") or 0
            processed = (row["completed"] or 0) + failed
            values = (
                row["created_at"],
                LABELS[row["kind"]],
                LABELS.get(row["state"], row["state"]),
                f"{processed}/{row['total']}" + (f" ({failed} com falha)" if failed else ""),
                str(row["audd_used"]),
                row["message"],
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(index, column, cell)
        self._actions()

    def set_busy(self, busy):
        self.busy = busy
        self._actions()

    def _actions(self):
        row = self.table.currentRow()
        self.resume.setEnabled(
            not self.busy
            and 0 <= row < len(self.rows)
            and self.rows[row]["state"] in ("paused", "running", "failed")
        )
        for button in (self.refresh, self.export_all, self.export_selected):
            button.setEnabled(not self.busy)

    def _resume(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.rows):
            self.resume_requested.emit(self.rows[row])
