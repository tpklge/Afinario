from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Slot
from PySide6.QtGui import QColor

from afinario.domain import Status
from afinario.identification import IdentificationReport
from afinario.inventory import InventoryRecord
from afinario.lyrics import LYRIC_LABELS
from afinario.resolver import DECISION_LABELS
from afinario.review import build_review, rebase_review

PROVIDER_LABELS = {
    "acoustid": "AcoustID",
    "shazamio": "ShazamIO",
    "musicbrainz": "MusicBrainz",
    "audd": "AudD",
    "previous": "Identificação anterior",
}
RESULT_LABELS = {
    "ok": "OK",
    "not_found": "sem resultado",
    "authentication_error": "acesso recusado",
    "rate_limited": "limite atingido",
    "unavailable": "indisponível",
    "network_error": "falha de rede",
    "invalid_response": "resposta inválida",
    "blocked": "consulta bloqueada",
    "audio_error": "falha no áudio",
}


def result_label(result):
    """Describe historical BLOCKED results as well as newly produced ones."""
    if result.status == Status.BLOCKED:
        if result.message.startswith("Executável auxiliar não encontrado"):
            return "ferramenta ausente"
        if result.provider == "audd" and result.message.startswith("Limite AudD"):
            return "limite da execução atingido"
        if result.message.startswith("Configure"):
            return "credencial ausente"
    return RESULT_LABELS.get(result.status.value, result.status.value)


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
        "Busca de letras",
        "Aprovação",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[InventoryRecord] = []
        self.identifications: dict[str, IdentificationReport] = {}
        self.analysis_states: dict[str, str] = {}
        self.lyrics = {}
        self.reviews = {}
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
            lines = [record.path, *record.messages]
            if outcome:
                lines.extend(outcome.decision.reasons)
                lines.extend(
                    f"{PROVIDER_LABELS.get(r.provider, r.provider)}: {r.message}"
                    for r in outcome.results
                )
            return "\n".join(lines)
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
                    + result_label(result)
                    + (" (cache)" if result.cached else "")
                    for result in outcome.results
                    if result.provider != "previous"
                )
                if outcome
                else "—",
                LYRIC_LABELS[self.lyrics[record.id].status]
                if record.id in self.lyrics
                else "Não consultada",
                (
                    f"{len(self.reviews[record.id].approved_fields)} campo(s) aprovado(s)"
                    if record.id in self.reviews and self.reviews[record.id].approved_fields
                    else "Revisar propostas"
                    if record.id in self.reviews
                    and any(f.changed for f in self.reviews[record.id].fields)
                    else "Sem alterações pendentes"
                ),
            )[index.column()]
        return None

    @Slot(list)
    def append_records(self, records: list[InventoryRecord]) -> None:
        if not records:
            return
        first = len(self.records)
        self.beginInsertRows(QModelIndex(), first, first + len(records) - 1)
        self.records.extend(records)
        self.reviews.update((record.id, build_review(record)) for record in records)
        self._rows.update((record.id, first + offset) for offset, record in enumerate(records))
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.records.clear()
        self.identifications.clear()
        self.analysis_states.clear()
        self.lyrics.clear()
        self.reviews.clear()
        self._rows.clear()
        self.endResetModel()

    def restore_context(self, context):
        for record in context["records"]:
            if record.id not in self._rows:
                self.append_records([record])
            else:
                self.records[self._rows[record.id]] = record
                self.identifications.pop(record.id, None)
                self.lyrics.pop(record.id, None)
                self.reviews[record.id] = build_review(record)
                row = self._rows[record.id]
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.HEADERS) - 1))
        for report in context["identifications"]:
            self.update_identification(report)
        for report in context["lyrics"]:
            self.update_lyrics(report)
        for draft in context["reviews"]:
            self.update_review(draft)

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
            old = self.reviews.get(outcome.file_id)
            self.lyrics.pop(outcome.file_id, None)
            self.reviews[outcome.file_id] = rebase_review(
                old,
                self.records[self._rows[outcome.file_id]],
                outcome,
                revision=old.revision if old else 0,
            )
            self.analysis_states.pop(outcome.file_id, None)
            row = self._rows[outcome.file_id]
            self.dataChanged.emit(self.index(row, 9), self.index(row, 14))

    @Slot(object)
    def update_lyrics(self, report):
        if report.file_id in self._rows:
            self.lyrics[report.file_id] = report
            old = self.reviews[report.file_id]
            self.reviews[report.file_id] = rebase_review(
                old,
                self.records[self._rows[report.file_id]],
                self.identifications.get(report.file_id),
                report,
                revision=old.revision,
            )
            row = self._rows[report.file_id]
            self.dataChanged.emit(self.index(row, 13), self.index(row, 14))

    @Slot(object)
    def update_review(self, draft):
        if draft.file_id in self._rows:
            self.reviews[draft.file_id] = draft
            row = self._rows[draft.file_id]
            self.dataChanged.emit(self.index(row, 14), self.index(row, 14))
