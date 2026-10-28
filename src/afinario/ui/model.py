from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Slot
from PySide6.QtGui import QColor

from afinario.identification import IdentificationReport
from afinario.inventory import InventoryRecord
from afinario.resolver import DECISION_LABELS

PROVIDER_LABELS = {
    "acoustid": "AcoustID",
    "shazamio": "ShazamIO",
    "musicbrainz": "MusicBrainz",
    "audd": "AudD",
}
RESULT_LABELS = {
    "ok": "OK",
    "not_found": "sem resultado",
    "authentication_error": "acesso recusado",
    "rate_limited": "limite atingido",
    "unavailable": "indisponível",
    "network_error": "falha de rede",
    "invalid_response": "resposta inválida",
    "blocked": "não configurado",
    "audio_error": "falha no áudio",
}


class LibraryModel(QAbstractTableModel):
    HEADERS = (
        "Arquivo",
        "Artista atual",
        "Título atual",
        "Álbum atual",
        "Formato",
        "Duração",
        "Letra",
        "Situação",
        "Pasta",
        "Artista proposto",
        "Título proposto",
        "Identificação",
        "Fontes",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[InventoryRecord] = []
        self.identifications: dict[str, IdentificationReport] = {}
        self.analysis_states: dict[str, str] = {}
        self._rows: dict[str, int] = {}

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.records)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.records):
            return None
        record = self.records[index.row()]
        outcome = self.identifications.get(record.id)
        if role == Qt.ItemDataRole.UserRole:
            return record
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(
                (record.path, *record.messages, *(outcome.decision.reasons if outcome else ()))
            )
        if role == Qt.ItemDataRole.ForegroundRole and record.status == "error":
            return QColor("#e58b79")
        if role == Qt.ItemDataRole.DisplayRole:
            duration = (
                "—"
                if record.duration is None
                else (f"{int(record.duration) // 60}:{int(record.duration) % 60:02d}")
            )
            return (
                Path(record.path).name,
                "; ".join(record.tags.artist) or "—",
                "; ".join(record.tags.title) or "—",
                "; ".join(record.tags.album) or "—",
                record.format or "Desconhecido",
                duration,
                "Não lida"
                if record.status == "error"
                else ("Presente" if record.tags.has_lyrics else "Ausente"),
                {"ok": "Lido", "warning": "Atenção", "error": "Erro"}[record.status],
                str(Path(record.path).parent),
                outcome.decision.artist if outcome and outcome.decision.artist else "—",
                outcome.decision.title if outcome and outcome.decision.title else "—",
                self.analysis_states.get(record.id)
                or (DECISION_LABELS[outcome.decision.status] if outcome else "Não analisada"),
                " · ".join(
                    PROVIDER_LABELS.get(result.provider, result.provider)
                    + ": "
                    + RESULT_LABELS.get(result.status.value, result.status.value)
                    + (" (cache)" if result.cached else "")
                    for result in outcome.results
                )
                if outcome
                else "—",
            )[index.column()]
        return None

    @Slot(list)
    def append_records(self, records: list[InventoryRecord]) -> None:
        if not records:
            return
        first = len(self.records)
        self.beginInsertRows(QModelIndex(), first, first + len(records) - 1)
        self.records.extend(records)
        self._rows.update((record.id, first + offset) for offset, record in enumerate(records))
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.records.clear()
        self.identifications.clear()
        self.analysis_states.clear()
        self._rows.clear()
        self.endResetModel()

    @Slot(str, str)
    def set_analysis_state(self, file_id: str, stage: str) -> None:
        if file_id in self._rows:
            self.analysis_states[file_id] = stage
            row = self._rows[file_id]
            self.dataChanged.emit(self.index(row, 9), self.index(row, 12))

    @Slot(object)
    def update_identification(self, outcome: IdentificationReport) -> None:
        if outcome.file_id in self._rows:
            self.identifications[outcome.file_id] = outcome
            self.analysis_states.pop(outcome.file_id, None)
            row = self._rows[outcome.file_id]
            self.dataChanged.emit(self.index(row, 9), self.index(row, 12))
