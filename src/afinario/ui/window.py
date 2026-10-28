from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from afinario.config import Settings
from afinario.identification import IdentificationReport, RecognitionOptions
from afinario.inventory import ALL_FORMATS, ScanIssue, ScanSummary
from afinario.logging_config import configure_logging
from afinario.resolver import DECISION_LABELS, DecisionStatus
from afinario.ui.model import PROVIDER_LABELS, RESULT_LABELS, LibraryModel
from afinario.ui.recognition_settings import RecognitionSettingsDialog
from afinario.ui.recognition_worker import IdentificationWorker
from afinario.ui.worker import ScanWorker


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.setWindowTitle("Afinário • Biblioteca musical")
        self.resize(1280, 800)
        self.setMinimumSize(880, 560)
        self.settings = settings or Settings.load()
        self.worker: ScanWorker | IdentificationWorker | None = None
        self._closing = False
        self._summary: ScanSummary | None = None
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Afinário")
        title.setObjectName("brand")
        subtitle = QLabel("Sua biblioteca musical em harmonia")
        subtitle.setObjectName("subtitle")
        page.addWidget(title)
        page.addWidget(subtitle)
        notice = QLabel(
            "Varrer lê as tags atuais. Identificar consulta os serviços e prepara propostas."
        )
        notice.setWordWrap(True)
        page.addWidget(notice)

        split = QSplitter(Qt.Orientation.Horizontal)
        page.addWidget(split, 1)
        sources = QWidget()
        side = QVBoxLayout(sources)
        side.setContentsMargins(0, 12, 16, 0)
        side.addWidget(QLabel("Pastas de origem"))
        self.folders = QListWidget()
        self.folders.setAccessibleName("Pastas de origem")
        self.folders.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        side.addWidget(self.folders, 1)
        folder_actions = QHBoxLayout()
        self.add_button = QPushButton("Adicionar pasta…")
        self.remove_button = QPushButton("Remover")
        folder_actions.addWidget(self.add_button)
        folder_actions.addWidget(self.remove_button)
        side.addLayout(folder_actions)
        self.recursive = QCheckBox("Incluir subpastas")
        self.recursive.setChecked(True)
        side.addWidget(self.recursive)
        side.addWidget(QLabel("Formatos de áudio"))
        self.format_boxes = {}
        for group in (
            ("MP3", "M4A", "FLAC", "Vorbis", "Opus"),
            ("WAV", "AIFF", "WMA", "APE", "AAC"),
        ):
            row = QHBoxLayout()
            for name in group:
                box = QCheckBox(name)
                box.setChecked(True)
                box.toggled.connect(self._update_actions)
                self.format_boxes[name] = box
                row.addWidget(box)
            side.addLayout(row)
        self.scan_button = QPushButton("Varrer biblioteca")
        self.scan_button.setObjectName("primary")
        self.cancel_button = QPushButton("Cancelar varredura")
        self.cancel_button.setEnabled(False)
        side.addWidget(self.scan_button)
        recognition_panel = QWidget()
        recognition_layout = QVBoxLayout(recognition_panel)
        recognition_layout.addWidget(QLabel("Reconhecimento por áudio"))
        self.acoustid_box = QCheckBox("Consultar AcoustID")
        self.acoustid_box.setChecked(True)
        self.shazam_box = QCheckBox("Permitir ShazamIO (experimental)")
        self.audd_box = QCheckBox("Usar AudD (plano pago)")
        self.audd_limit = QSpinBox()
        self.audd_limit.setRange(0, 100000)
        self.audd_limit.setValue(self.settings.audd_max_requests)
        self.audd_limit.setPrefix("Limite AudD nesta execução: ")
        self.audd_limit.setToolTip(
            "0 bloqueia novas consultas pagas. Respostas em cache não consomem limite."
        )
        self.audd_usage = QLabel("AudD: nenhuma tentativa nesta execução.")
        self.audd_usage.setWordWrap(True)
        self.metadata_box = QCheckBox("Complementar com MusicBrainz")
        self.metadata_box.setChecked(True)
        self.refresh_box = QCheckBox("Atualizar consultas (ignorar cache)")
        self.settings_button = QPushButton("Serviços e ferramentas…")
        self.recognize_selected = QPushButton("Identificar selecionadas (online)")
        self.recognize_all = QPushButton("Identificar biblioteca (online)")
        for widget in (
            self.acoustid_box,
            self.shazam_box,
            self.audd_box,
            self.audd_limit,
            self.audd_usage,
            self.metadata_box,
            self.refresh_box,
            self.settings_button,
            self.recognize_selected,
            self.recognize_all,
        ):
            recognition_layout.addWidget(widget)
        privacy = QLabel(
            "AcoustID recebe fingerprint e duração. ShazamIO recebe a assinatura "
            "de um trecho; AudD recebe até 12 s de áudio. As músicas permanecem intactas."
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("subtitle")
        recognition_layout.addWidget(privacy)
        self.key_state = QLabel()
        self.key_state.setWordWrap(True)
        recognition_layout.addWidget(self.key_state)
        recognition_layout.addStretch(1)
        memory = QLabel(
            "Os resultados ficam nesta sessão.\nA persistência será adicionada em outra etapa."
        )
        memory.setWordWrap(True)
        memory.setObjectName("subtitle")
        side.addWidget(memory)
        self.source_tabs = QTabWidget()
        self.source_tabs.addTab(sources, "Pastas")
        recognition_scroll = QScrollArea()
        recognition_scroll.setWidgetResizable(True)
        recognition_scroll.setFrameShape(QFrame.Shape.NoFrame)
        recognition_scroll.setWidget(recognition_panel)
        self.source_tabs.addTab(recognition_scroll, "Reconhecer")
        split.addWidget(self.source_tabs)

        library = QWidget()
        content = QVBoxLayout(library)
        content.setContentsMargins(8, 12, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por arquivo, artista, título, álbum ou pasta…")
        self.search.setAccessibleName("Filtrar biblioteca")
        content.addWidget(self.search)
        self.model = LibraryModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setAccessibleName("Inventário musical")
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate(
            (220, 140, 220, 160, 85, 75, 85, 85, 280, 140, 230, 180, 180)
        ):
            self.table.setColumnWidth(column, width)
        result_split = QSplitter(Qt.Orientation.Vertical)
        result_split.addWidget(self.table)
        self.tabs = QTabWidget()
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Selecione uma música para ver os metadados atuais.")
        self.issues = QTextEdit()
        self.issues.setReadOnly(True)
        self.issues.setPlaceholderText("Problemas de acesso às pastas aparecerão aqui.")
        self.tabs.addTab(self.details, "Detalhes")
        self.tabs.addTab(self.issues, "Ocorrências")
        self.recognition_details = QTextEdit()
        self.recognition_details.setReadOnly(True)
        self.recognition_details.setPlaceholderText(
            "Após varrer, use Identificar para consultar os serviços."
        )
        self.tabs.addTab(self.recognition_details, "Reconhecimento")
        result_split.addWidget(self.tabs)
        result_split.setStretchFactor(0, 3)
        result_split.setStretchFactor(1, 2)
        result_split.setSizes([360, 240])
        content.addWidget(result_split, 1)
        split.addWidget(library)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([350, 850])

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        page.addWidget(self.progress)
        self.status = QLabel("Adicione pastas para começar. Nenhuma consulta externa será feita.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.cancel_button)
        page.addLayout(footer)
        self.add_button.clicked.connect(self._choose_folder)
        self.remove_button.clicked.connect(self._remove_folders)
        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.folders.itemSelectionChanged.connect(self._update_actions)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.table.selectionModel().selectionChanged.connect(self._show_details)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.recognize_selected.clicked.connect(lambda: self.start_identification(selected=True))
        self.recognize_all.clicked.connect(lambda: self.start_identification(selected=False))
        self.settings_button.clicked.connect(self._configure_recognition)
        self.acoustid_box.toggled.connect(self._update_actions)
        self.shazam_box.toggled.connect(self._update_actions)
        self.audd_box.toggled.connect(self._update_actions)
        self._update_actions()

    def add_folder(self, path: Path) -> None:
        text = str(path.absolute())
        if not self.folders.findItems(text, Qt.MatchFlag.MatchExactly):
            self.folders.addItem(text)
        self._update_actions()

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Adicionar pasta de músicas")
        if path:
            self.add_folder(Path(path))

    def _remove_folders(self):
        for item in self.folders.selectedItems():
            self.folders.takeItem(self.folders.row(item))
        self._update_actions()

    def _update_actions(self, *_):
        running = self.worker is not None
        self.scan_button.setEnabled(
            not running
            and self.folders.count() > 0
            and any(box.isChecked() for box in self.format_boxes.values())
        )
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running and bool(self.folders.selectedItems()))
        self.recursive.setEnabled(not running)
        for box in self.format_boxes.values():
            box.setEnabled(not running)
        options_valid = (
            self.acoustid_box.isChecked()
            or self.shazam_box.isChecked()
            or self.audd_box.isChecked()
        )
        self.recognize_all.setEnabled(
            not running
            and options_valid
            and any(item.status != "error" for item in self.model.records)
        )
        selected = self.table.selectionModel().selectedRows()
        self.recognize_selected.setEnabled(
            not running
            and options_valid
            and any(
                self.model.records[self.proxy.mapToSource(index).row()].status != "error"
                for index in selected
            )
        )
        for widget in (
            self.settings_button,
            self.acoustid_box,
            self.shazam_box,
            self.audd_box,
            self.metadata_box,
            self.refresh_box,
        ):
            widget.setEnabled(not running)
        self.audd_limit.setEnabled(not running and self.audd_box.isChecked())
        self.key_state.setText(
            "AcoustID: chave configurada."
            if self.settings.acoustid_key
            else "AcoustID: falta configurar a chave em Serviços e ferramentas."
        )
        self.key_state.setText(
            self.key_state.text()
            + "\nAudD: "
            + (
                "token configurado."
                if self.settings.audd_token
                else "configure o token em Serviços e ferramentas."
            )
        )

    @Slot()
    def start_scan(self):
        if self.worker is not None or not self.scan_button.isEnabled():
            return
        self.model.clear()
        self.details.clear()
        self.recognition_details.clear()
        self.issues.clear()
        self._summary = None
        roots = [Path(self.folders.item(index).text()) for index in range(self.folders.count())]
        formats = frozenset(name for name in ALL_FORMATS if self.format_boxes[name].isChecked())
        worker = ScanWorker(roots, self.recursive.isChecked(), formats, self)
        self.worker = worker
        worker.records_ready.connect(self.model.append_records)
        worker.progress_ready.connect(self._on_progress)
        worker.issue_ready.connect(self._on_issue)
        worker.scan_complete.connect(self._on_complete)
        worker.scan_failed.connect(self._on_failed)
        worker.finished.connect(self._thread_finished)
        self.progress.setRange(0, 0)
        self.status.setText("Varrendo pastas e lendo metadados…")
        self.cancel_button.setText("Cancelar varredura")
        self.cancel_button.setEnabled(True)
        self._update_actions()
        worker.start()

    @Slot()
    def cancel_scan(self):
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Cancelando…")

    @Slot(object)
    def _on_progress(self, summary: ScanSummary):
        self.status.setText(
            f"{summary.visited_files} arquivos examinados • {summary.audio_files} músicas • "
            f"{summary.invalid_files} arquivos inválidos • "
            f"{summary.inaccessible_paths} falhas de acesso"
        )

    @Slot(object)
    def _on_issue(self, issue: ScanIssue):
        # Plain text prevents filenames containing HTML from becoming links/markup.
        cursor = self.issues.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(f"{issue.path}\n{issue.message}\n\n")

    @Slot(object)
    def _on_complete(self, summary: ScanSummary):
        self._summary = summary
        prefix = "Varredura cancelada" if summary.cancelled else "Varredura concluída"
        self.status.setText(
            f"{prefix} • {summary.audio_files} músicas • {summary.warnings} avisos • "
            f"{summary.invalid_files} inválidos • {summary.inaccessible_paths} falhas de acesso • "
            f"{summary.skipped_links} links ignorados"
        )
        if summary.audio_files:
            self.source_tabs.setCurrentIndex(1)

    @Slot(str)
    def _on_failed(self, message: str):
        self.status.setText(message)

    @Slot()
    def _thread_finished(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.cancel_button.setText("Cancelar tarefa")
        self.cancel_button.setEnabled(False)
        self._update_actions()
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _show_details(self, *_):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.details.clear()
            self.recognition_details.clear()
            return
        source = self.proxy.mapToSource(indexes[0])
        record = self.model.records[source.row()]
        lines = [
            record.path,
            "",
            f"Formato: {record.format or 'não identificado'}",
            f"Tamanho: {record.size:,} bytes",
            f"Duração: {record.duration or '—'} s",
            f"Taxa: {record.sample_rate or '—'} Hz",
            "",
        ]
        labels = {
            "title": "Título",
            "artist": "Artista",
            "album": "Álbum",
            "album_artist": "Artista do álbum",
            "track": "Faixa",
            "disc": "Disco",
            "date": "Data",
            "genre": "Gênero",
        }
        lines.extend(
            f"{label}: {'; '.join(getattr(record.tags, key)) or '—'}"
            for key, label in labels.items()
        )
        lines.extend(
            [
                "Letra embutida: "
                + (
                    "não lida"
                    if record.status == "error"
                    else "sim"
                    if record.tags.has_lyrics
                    else "não"
                ),
                f"Capas: {record.tags.cover_count if record.status != 'error' else '—'}",
                "",
                *record.messages,
            ]
        )
        self.details.setPlainText("\n".join(lines))
        self._show_recognition(record.id)

    def _configure_recognition(self):
        dialog = RecognitionSettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.selected_settings()
            configure_logging(self.settings.acoustid_key, self.settings.audd_token)
            self.status.setText("Configuração de reconhecimento atualizada para esta sessão.")
            self._update_actions()

    def start_identification(self, *, selected: bool = False):
        if self.worker is not None:
            return
        if selected:
            rows = [
                self.proxy.mapToSource(index).row()
                for index in self.table.selectionModel().selectedRows()
            ]
            records = [self.model.records[row] for row in sorted(set(rows))]
        else:
            records = list(self.model.records)
        records = [record for record in records if record.status != "error"]
        options = RecognitionOptions(
            self.acoustid_box.isChecked(),
            self.shazam_box.isChecked(),
            self.metadata_box.isChecked(),
            self.refresh_box.isChecked(),
            self.audd_box.isChecked(),
        )
        if not records or not (options.acoustid or options.shazamio or options.audd):
            return
        header = self.table.horizontalHeader()
        for position, column in enumerate((9, 10, 11, 12), start=1):
            header.moveSection(header.visualIndex(column), position)
        self.settings = replace(self.settings, audd_max_requests=self.audd_limit.value())
        self._analysis_budget(0, self.settings.audd_max_requests)
        worker = IdentificationWorker(records, self.settings, options, self)
        self.worker = worker
        worker.stage_ready.connect(self._analysis_stage)
        worker.result_ready.connect(self._analysis_result)
        worker.item_cancelled.connect(self._analysis_cancelled)
        worker.progress_ready.connect(self._analysis_progress)
        worker.warning_ready.connect(self._analysis_warning)
        worker.budget_ready.connect(self._analysis_budget)
        worker.analysis_complete.connect(self._analysis_complete)
        worker.finished.connect(self._thread_finished)
        self.progress.setRange(0, len(records))
        self.progress.setValue(0)
        self.cancel_button.setText("Cancelar identificação")
        self.cancel_button.setEnabled(True)
        self.status.setText(f"Iniciando identificação de {len(records)} músicas…")
        self.tabs.setCurrentWidget(self.recognition_details)
        self._update_actions()
        worker.start()

    @Slot(str, str)
    def _analysis_stage(self, file_id: str, stage: str):
        self.model.set_analysis_state(file_id, stage)
        self.status.setText(stage + "…")

    @Slot(str)
    def _analysis_cancelled(self, file_id: str):
        self.model.set_analysis_state(file_id, "Análise cancelada")

    @Slot(str)
    def _analysis_warning(self, message: str):
        self._on_issue(ScanIssue("Reconhecimento", message))

    @Slot(int, int)
    def _analysis_budget(self, used: int, limit: int):
        self.audd_usage.setText(f"AudD: {used}/{limit} tentativas reservadas nesta execução.")

    @Slot(object)
    def _analysis_result(self, outcome: IdentificationReport):
        self.model.update_identification(outcome)
        self._show_details()

    @Slot(int, int)
    def _analysis_progress(self, completed: int, total: int):
        self.progress.setValue(completed)
        self.status.setText(f"Identificação: {completed}/{total} músicas analisadas.")

    @Slot(int, int, bool)
    def _analysis_complete(self, completed: int, total: int, cancelled: bool):
        agreeing = sum(
            item.decision.status == DecisionStatus.AGREEMENT
            for item in self.model.identifications.values()
        )
        self.status.setText(
            f"Identificação {'cancelada' if cancelled else 'concluída'} • {completed}/{total} "
            f"nesta execução • {agreeing} com fontes concordantes na biblioteca."
        )

    def _show_recognition(self, file_id: str):
        outcome = self.model.identifications.get(file_id)
        if outcome is None:
            self.recognition_details.setPlainText(
                "Esta música ainda não foi identificada pelos serviços."
            )
            return
        decision = outcome.decision
        lines = [
            DECISION_LABELS[decision.status],
            f"Artista proposto: {decision.artist or '—'}",
            f"Título proposto: {decision.title or '—'}",
            *decision.reasons,
            "",
        ]
        for result in outcome.results:
            lines.append(
                f"{PROVIDER_LABELS.get(result.provider, result.provider)}: "
                f"{RESULT_LABELS.get(result.status.value, result.status.value)}"
                + (" • cache" if result.cached else "")
            )
            lines.append(result.message)
            for candidate in result.candidates:
                lines.append(f"  {candidate.artist or '—'} — {candidate.title or '—'}")
                lines.append(
                    f"  ID: {candidate.external_id}; duração: {candidate.duration or '—'} s"
                )
                if candidate.recording_id:
                    lines.append(f"  MBID: {candidate.recording_id}")
                if candidate.score is not None:
                    lines.append(f"  Score original: {candidate.score} (não é probabilidade)")
                if candidate.title_aliases:
                    lines.append("  Títulos alternativos: " + "; ".join(candidate.title_aliases))
                if candidate.isrcs:
                    lines.append("  ISRC: " + ", ".join(candidate.isrcs))
            if result.releases:
                lines.append("  Lançamentos possíveis, sem escolha automática de álbum/ano:")
                lines.extend(
                    f"  • {release.title} ({release.date or 'data desconhecida'})"
                    for release in result.releases
                )
            lines.append("")
        self.recognition_details.setPlainText("\n".join(lines))

    def closeEvent(self, event):
        if self.worker is not None:
            self._closing = True
            self.cancel_scan()
            self.status.setText("Encerrando a tarefa antes de fechar…")
            event.ignore()
        else:
            event.accept()
