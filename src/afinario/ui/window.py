import json
import shutil
import sys
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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

from afinario.automation import automatic_fields, identity_is_valid
from afinario.change_plan import agreement_allows_rename
from afinario.config import Settings
from afinario.identification import IdentificationReport, RecognitionOptions
from afinario.inventory import ALL_FORMATS, ScanIssue, ScanSummary
from afinario.library import LibraryPreferences, LibraryState, _record, default_library_path
from afinario.logging_config import configure_logging
from afinario.lyrics import LyricOptions, recognition_key
from afinario.resolver import DECISION_LABELS, DecisionStatus
from afinario.ui.batches_panel import BatchesPanel
from afinario.ui.library_worker import LoadLibraryWorker, SavePreferencesWorker
from afinario.ui.lyrics_worker import LyricsWorker
from afinario.ui.model import PROVIDER_LABELS, LibraryModel, result_label
from afinario.ui.operations_panel import OperationsPanel
from afinario.ui.operations_worker import OperationsWorker
from afinario.ui.player import AudioPlayer
from afinario.ui.recognition_settings import RecognitionSettingsDialog
from afinario.ui.recognition_worker import IdentificationWorker
from afinario.ui.report_worker import ReportWorker
from afinario.ui.review_panel import ReviewPanel
from afinario.ui.review_worker import SaveReviewsWorker
from afinario.ui.worker import ScanWorker


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        library_path: Path | None = None,
        restore_settings: bool = True,
        folders: list[Path] | None = None,
    ):
        super().__init__()
        self.setWindowTitle("Afinário • Biblioteca musical")
        self.resize(1280, 800)
        self.setMinimumSize(880, 560)
        self.settings = settings or Settings.load()
        self.library_path = library_path if library_path is not None else default_library_path()
        self._restore_settings = restore_settings
        self._initial_folders = folders
        self._library_available = False
        self._preferences_saved = False
        self._analysis_error = False
        self._analysis_pending = set()
        self._analysis_completed = set()
        self._auto_apply_ids = set()
        self._auto_lyrics_ids = set()
        self._auto_apply_stage = "identity"
        self._batch_paused = False
        self._need_batch_refresh = False
        self._resume_payload = None
        self._lyric_ids = set()
        self._pending_reviews = {}
        self._review_batch = {}
        self._review_save_failed = False
        self._review_timer = QTimer(self)
        self._review_timer.setSingleShot(True)
        self._review_timer.timeout.connect(self._flush_reviews)
        self.worker = None
        self._closing = False
        self._summary: ScanSummary | None = None
        self._build()
        self._load_library()

    def _load_library(self):
        worker = LoadLibraryWorker(self.library_path, self, settings=self.settings)
        self.worker = worker
        worker.loaded.connect(self._library_loaded)
        worker.credentials_ready.connect(self._credentials_loaded)
        worker.history_ready.connect(self.operations_panel.show_history)
        worker.batches_ready.connect(self.batches_panel.show_batches)
        worker.credentials_failed.connect(self._analysis_warning)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._thread_finished)
        self.progress.setRange(0, 0)
        self.status.setText("Abrindo a biblioteca salva…")
        self._update_actions()
        worker.start()

    @Slot(object)
    def _credentials_loaded(self, settings):
        self.settings = settings
        configure_logging(settings.acoustid_key, settings.audd_token)

    @Slot(object)
    def _library_loaded(self, state: LibraryState):
        preferences = state.preferences
        self._library_available = True
        if self._restore_settings and preferences.settings and preferences.platform == sys.platform:
            self.settings = replace(
                Settings.from_data(preferences.settings),
                acoustid_key=self.settings.acoustid_key,
                audd_token=self.settings.audd_token,
            )
        roots = self._initial_folders
        if roots is None:
            roots = [Path(path) for path in preferences.roots]
        for root in roots:
            self.add_folder(root)
        self.recursive.setChecked(preferences.recursive)
        for name, box in self.format_boxes.items():
            box.setChecked(name in preferences.formats)
        self.search.setText(preferences.search)
        options = LyricOptions(**preferences.lyrics_options)
        self.lrclib_box.setChecked(options.lrclib)
        self.ovh_box.setChecked(options.lyrics_ovh)
        self.lyric_mode.setCurrentIndex(0 if options.mode == "full" else 1)
        self.audd_limit.setValue(self.settings.audd_max_requests)
        self.operations_panel.auto_rename.setChecked(preferences.auto_rename_agreement)
        self.operations_panel.auto_tags.setChecked(preferences.auto_tags_agreement)
        self.operations_panel.auto_lyrics.setChecked(preferences.auto_lyrics)
        self.operations_panel.backup_directory.setText(preferences.backup_directory)
        recognition = RecognitionOptions(**preferences.recognition_options)
        for box, value in (
            (self.acoustid_box, recognition.acoustid),
            (self.shazam_box, recognition.shazamio),
            (self.audd_box, recognition.audd),
            (self.metadata_box, recognition.musicbrainz),
        ):
            box.setChecked(value)
        self.model.append_records(list(state.records))
        for report in state.identifications:
            self.model.update_identification(report)
        for report in state.lyrics:
            self.model.update_lyrics(report)
        for draft in state.reviews:
            self.model.update_review(draft)
        for issue in state.issues:
            self._on_issue(issue)
        if state.summary:
            self._summary = ScanSummary(**state.summary)
        if state.run_id:
            incomplete = state.run_state in ("running", "failed", "cancelled")
            self.status.setText(
                f"Biblioteca restaurada • {len(state.records)} músicas • "
                + ("última varredura incompleta. " if incomplete else "")
                + "Use Varrer para atualizar arquivos alterados fora do aplicativo."
            )
        else:
            self.status.setText(
                "Adicione pastas para começar. A biblioteca será salva neste computador."
            )

    def _preferences(self) -> LibraryPreferences:
        return LibraryPreferences(
            roots=tuple(self.folders.item(index).text() for index in range(self.folders.count())),
            recursive=self.recursive.isChecked(),
            formats=tuple(
                sorted(name for name, box in self.format_boxes.items() if box.isChecked())
            ),
            search=self.search.text(),
            settings=self.settings.public_data(),
            lyrics_options=asdict(self._lyric_options(refresh=False)),
            recognition_options={
                "acoustid": self.acoustid_box.isChecked(),
                "shazamio": self.shazam_box.isChecked(),
                "audd": self.audd_box.isChecked(),
                "musicbrainz": self.metadata_box.isChecked(),
            },
            auto_rename_agreement=self.operations_panel.auto_rename.isChecked(),
            auto_tags_agreement=self.operations_panel.auto_tags.isChecked(),
            auto_lyrics=self.operations_panel.auto_lyrics.isChecked(),
            backup_directory=self.operations_panel.backup_directory.text().strip(),
        )

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
            "Automação de nomes, tags e letras com backup; configure em Aplicar e restaurar."
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
        audd_note = QLabel("Para enviar ao AudD, marque o serviço e defina um limite acima de 0.")
        audd_note.setWordWrap(True)
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
            audd_note,
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
            "de um trecho; AudD recebe até 12 s de áudio. "
            "Nomes, tags e letras automáticas seguem as opções em Aplicar e restaurar."
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("subtitle")
        recognition_layout.addWidget(privacy)
        self.key_state = QLabel()
        self.key_state.setWordWrap(True)
        recognition_layout.addWidget(self.key_state)
        recognition_layout.addStretch(1)
        memory = QLabel("A biblioteca e as propostas são salvas automaticamente neste computador.")
        memory.setToolTip(str(self.library_path))
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
        lyrics_panel = QWidget()
        lyric_layout = QVBoxLayout(lyrics_panel)
        self.lrclib_box = QCheckBox("Consultar LRCLIB (público)")
        self.lrclib_box.setChecked(True)
        self.ovh_box = QCheckBox("Consultar lyrics.ovh (público)")
        self.ovh_box.setChecked(True)
        self.lyric_mode = QComboBox()
        self.lyric_mode.addItems(
            ["Completo: consultar ambas as fontes", "Rápido: segunda fonte se necessário"]
        )
        self.lyric_refresh = QCheckBox("Atualizar letras (ignorar cache)")
        self.lyrics_selected = QPushButton("Buscar letras selecionadas")
        self.lyrics_all = QPushButton("Buscar letras da biblioteca")
        for widget in (
            self.lrclib_box,
            self.ovh_box,
            self.lyric_mode,
            self.lyric_refresh,
            self.lyrics_selected,
            self.lyrics_all,
        ):
            lyric_layout.addWidget(widget)
        note = QLabel(
            "A busca envia artista e título. Letras existentes são preservadas por padrão. "
            "Confira os resultados em Revisar e aprovar → Letras e diferenças."
        )
        note.setWordWrap(True)
        lyric_layout.addWidget(note)
        lyric_layout.addStretch(1)
        self.source_tabs.addTab(lyrics_panel, "Letras")
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
        result_split = self.result_split = QSplitter(Qt.Orientation.Vertical)
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
        self.review_panel = ReviewPanel()
        review_scroll = QScrollArea()
        review_scroll.setWidgetResizable(True)
        review_scroll.setWidget(self.review_panel)
        self.review_tab = review_scroll
        self.tabs.addTab(review_scroll, "Revisar e aprovar")
        self.operations_panel = OperationsPanel()
        self.tabs.addTab(self.operations_panel, "Aplicar e restaurar")
        self.batches_panel = BatchesPanel()
        self.tabs.addTab(self.batches_panel, "Lotes e relatórios")
        result_split.addWidget(self.tabs)
        result_split.setStretchFactor(0, 3)
        result_split.setStretchFactor(1, 2)
        result_split.setSizes([360, 240])
        content.addWidget(result_split, 1)
        self.player = AudioPlayer(self)
        content.addWidget(self.player)
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
        self.pause_button = QPushButton("Pausar lote")
        self.pause_button.clicked.connect(self._pause_batch)
        footer.addWidget(self.pause_button)
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
        self.table.doubleClicked.connect(lambda _: self.player.toggle())
        self.recognize_selected.clicked.connect(lambda: self.start_identification(selected=True))
        self.recognize_all.clicked.connect(lambda: self.start_identification(selected=False))
        self.settings_button.clicked.connect(self._configure_recognition)
        self.acoustid_box.toggled.connect(self._update_actions)
        self.shazam_box.toggled.connect(self._update_actions)
        self.audd_box.toggled.connect(self._update_actions)
        self.audd_limit.valueChanged.connect(self._update_actions)
        self.lrclib_box.toggled.connect(self._update_actions)
        self.ovh_box.toggled.connect(self._update_actions)
        self.lyrics_selected.clicked.connect(lambda: self.start_lyrics(selected=True))
        self.lyrics_all.clicked.connect(lambda: self.start_lyrics(selected=False))
        self.review_panel.draft_changed.connect(self._review_changed)
        self.review_panel.save_requested.connect(self._approve_review)
        self.review_panel.search_requested.connect(lambda: self.start_lyrics(selected=True))
        self.review_panel.embedded_requested.connect(
            lambda: self.start_lyrics(selected=True, read_only=True)
        )
        self.review_panel.import_requested.connect(self._import_lyrics)
        self.review_panel.paste_requested.connect(self._paste_lyrics)
        self.tabs.currentChanged.connect(self._details_tab_changed)
        self.operations_panel.plan_requested.connect(self._plan_changes)
        self.operations_panel.apply_requested.connect(
            lambda plan_id: self._start_operation("apply", plan_id=plan_id)
        )
        self.operations_panel.restore_requested.connect(
            lambda operation_id: self._start_operation("restore", operation_id=operation_id)
        )
        self.operations_panel.recovery_requested.connect(lambda: self._start_operation("recover"))
        self.batches_panel.resume_requested.connect(self._resume_batch)
        self.batches_panel.export_requested.connect(self._export_report)
        self.batches_panel.refresh_requested.connect(lambda: self._start_report())
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
        running = self.worker is not None or bool(self._pending_reviews)
        self.operations_panel.set_busy(running or not self._library_available)
        self.batches_panel.set_busy(running or not self._library_available)
        can_pause = (
            self.worker is not None
            and hasattr(self.worker, "pause")
            and not (
                isinstance(self.worker, OperationsWorker)
                and self.worker.task not in ("auto", "apply")
            )
        )
        self.pause_button.setEnabled(can_pause)
        self.scan_button.setEnabled(
            not running
            and self._library_available
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
            and self._library_available
            and options_valid
            and any(item.status != "error" for item in self.model.records)
        )
        selected = self.table.selectionModel().selectedRows()
        can_lyrics = (
            not running
            and self._library_available
            and (self.lrclib_box.isChecked() or self.ovh_box.isChecked())
        )
        self.lyrics_selected.setEnabled(bool(can_lyrics and selected))
        self.lyrics_all.setEnabled(bool(can_lyrics and self.model.records))
        self.review_panel.setEnabled(
            self.worker is None and self._library_available and bool(selected)
        )
        for widget in (self.lrclib_box, self.ovh_box, self.lyric_mode, self.lyric_refresh):
            widget.setEnabled(not running)
        self.recognize_selected.setEnabled(
            not running
            and self._library_available
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
            "AcoustID: chave presente; o acesso será validado na consulta."
            if self.settings.acoustid_key
            else "AcoustID: falta configurar a chave em Serviços e ferramentas."
        )
        missing_tools = [
            name
            for name in ("fpcalc", "ffmpeg", "ffprobe")
            if shutil.which(getattr(self.settings, name)) is None
        ]
        if missing_tools:
            self.key_state.setText(
                self.key_state.text()
                + "\nFerramentas ausentes: "
                + ", ".join(missing_tools)
                + ". Escolha os executáveis em Serviços e ferramentas."
            )
        if self.audd_box.isChecked() and self.audd_limit.value() == 0:
            self.key_state.setText(
                self.key_state.text() + "\nAudD bloqueado pelo limite 0 de novas consultas."
            )
        self.key_state.setText(
            self.key_state.text()
            + "\nAudD: "
            + (
                "token presente; o acesso será validado na consulta."
                if self.settings.audd_token
                else "configure o token em Serviços e ferramentas."
            )
        )

    @Slot()
    def start_scan(self, *, batch_id=None):
        if self.worker is not None or not self.scan_button.isEnabled():
            return
        self.player.set_record(None)
        self.operations_panel.invalidate_plan()
        self.model.clear()
        self.details.clear()
        self.recognition_details.clear()
        self.issues.clear()
        self._summary = None
        roots = [Path(self.folders.item(index).text()) for index in range(self.folders.count())]
        formats = frozenset(name for name in ALL_FORMATS if self.format_boxes[name].isChecked())
        worker = ScanWorker(
            roots,
            self.recursive.isChecked(),
            formats,
            self,
            library_path=self.library_path,
            preferences=self._preferences(),
            batch_id=batch_id,
        )
        self.worker = worker
        worker.batch_ready.connect(self._batch_changed)
        worker.records_ready.connect(self.model.append_records)
        worker.identifications_ready.connect(self._restore_identifications)
        worker.lyrics_ready.connect(self._restore_lyrics)
        worker.reviews_ready.connect(self._restore_reviews)
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
        if self.worker is not None and hasattr(self.worker, "cancel"):
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
        prefix = (
            "Varredura pausada"
            if self._batch_paused
            else ("Varredura cancelada" if summary.cancelled else "Varredura concluída")
        )
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
        self._on_issue(ScanIssue(str(self.library_path), message))

    @Slot(list)
    def _restore_identifications(self, reports: list):
        for report in reports:
            self.model.update_identification(report)

    @Slot(list)
    def _restore_lyrics(self, reports):
        for report in reports:
            self.model.update_lyrics(report)

    @Slot(list)
    def _restore_reviews(self, drafts):
        for draft in drafts:
            self.model.update_review(draft)

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
        if self._pending_reviews and not self._review_save_failed:
            self._flush_reviews()
            return
        if self._auto_apply_ids and not self._closing:
            ids, self._auto_apply_ids = self._auto_apply_ids, set()
            records = [r for r in self.model.records if r.id in ids]
            self._start_operation("auto", records=records, stage=self._auto_apply_stage)
            return
        if self._auto_lyrics_ids and not self._closing:
            ids, self._auto_lyrics_ids = self._auto_lyrics_ids, set()
            records = [r for r in self.model.records if r.id in ids]
            self.start_lyrics(selected=False, records_override=records, automatic=True)
            return
        if self._resume_payload and not self._closing:
            payload, self._resume_payload = self._resume_payload, None
            self._launch_resume(payload)
            return
        if self._need_batch_refresh and not self._closing:
            self._need_batch_refresh = False
            self._start_report()
            return
        if self._closing:
            QTimer.singleShot(0, self, self.close)

    def _show_details(self, *_):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.player.set_record(None)
            self.details.clear()
            self.recognition_details.clear()
            self.review_panel.clear()
            return
        source = self.proxy.mapToSource(indexes[0])
        record = self.model.records[source.row()]
        self.player.set_record(record)
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
        self.review_panel.show_record(
            record,
            self.model.reviews[record.id],
            self.model.identifications.get(record.id),
            self.model.lyrics.get(record.id),
        )

    def _configure_recognition(self):
        dialog = RecognitionSettingsDialog(
            self.settings,
            self,
            library_path=self.library_path,
            preferences=self._preferences(),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.selected_settings()
            configure_logging(self.settings.acoustid_key, self.settings.audd_token)
            self.audd_limit.setValue(self.settings.audd_max_requests)
            self.status.setText("Configurações salvas. Credenciais disponíveis neste computador.")
            self._update_actions()

    def start_identification(self, *, selected: bool = False, batch_id=None, records_override=None):
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
        if records_override is not None:
            records = records_override
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
        self._analysis_error = False
        self.operations_panel.invalidate_plan()
        self._auto_apply_ids.clear()
        self._analysis_pending = {record.id for record in records}
        self._analysis_completed.clear()
        for record in records:
            self.model.set_analysis_state(record.id, "Na fila")
        worker = IdentificationWorker(
            records,
            self.settings,
            options,
            self,
            library_path=self.library_path,
            preferences=self._preferences(),
            batch_id=batch_id,
        )
        self.worker = worker
        worker.batch_ready.connect(self._batch_changed)
        worker.stage_ready.connect(self._analysis_stage)
        worker.result_ready.connect(self._analysis_result)
        worker.item_cancelled.connect(self._analysis_cancelled)
        worker.progress_ready.connect(self._analysis_progress)
        worker.warning_ready.connect(self._analysis_warning)
        worker.analysis_failed.connect(self._recognition_failed)
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
        if file_id not in self._analysis_pending:
            return
        self.model.set_analysis_state(file_id, stage)
        self.status.setText(stage + "…")

    @Slot(str)
    def _analysis_cancelled(self, file_id: str):
        self._analysis_pending.discard(file_id)
        self.model.set_analysis_state(file_id, "Análise cancelada")

    @Slot(str)
    def _analysis_warning(self, message: str):
        self._on_issue(ScanIssue("Reconhecimento", message))

    @Slot(str)
    def _recognition_failed(self, message: str):
        self._analysis_error = True
        for file_id in self._analysis_pending:
            self.model.set_analysis_state(file_id, "Falha ao concluir a consulta")
        self._analysis_pending.clear()
        self._on_failed(message)

    @Slot(int, int)
    def _analysis_budget(self, used: int, limit: int):
        self.audd_usage.setText(f"AudD: {used}/{limit} tentativas reservadas nesta execução.")

    @Slot(object)
    def _analysis_result(self, outcome: IdentificationReport):
        self._analysis_pending.discard(outcome.file_id)
        self._analysis_completed.add(outcome.file_id)
        self.model.update_identification(outcome)
        self._show_details()

    @Slot(int, int)
    def _analysis_progress(self, completed: int, total: int):
        self.progress.setValue(completed)
        self.status.setText(f"Identificação: {completed}/{total} músicas analisadas.")

    @Slot(int, int, bool)
    def _analysis_complete(self, completed: int, total: int, cancelled: bool):
        if self._analysis_error:
            return
        if self._batch_paused:
            for file_id in self._analysis_pending:
                self.model.set_analysis_state(file_id, "Análise pausada")
            self._analysis_pending.clear()
            self.status.setText(
                f"Lote pausado • {completed}/{total}. Retome em Lotes e relatórios."
            )
            return
        for file_id in self._analysis_pending:
            self.model.set_analysis_state(
                file_id, "Análise cancelada" if cancelled else "Consulta sem resultado final"
            )
        self._analysis_pending.clear()
        counts = Counter(
            self.model.identifications[file_id].decision.status
            for file_id in self._analysis_completed
        )
        if not cancelled and (
            self.operations_panel.auto_rename.isChecked()
            or self.operations_panel.auto_tags.isChecked()
            or self.operations_panel.auto_lyrics.isChecked()
        ):
            self._auto_apply_stage = "identity"
            self._auto_apply_ids = {
                file_id
                for file_id in self._analysis_completed
                if agreement_allows_rename(
                    self.model.identifications[file_id], self.model.reviews[file_id]
                )
            }
        self.status.setText(
            f"Identificação {'cancelada' if cancelled else 'concluída'} • {completed}/{total} "
            f"nesta execução • {counts[DecisionStatus.AGREEMENT]} confirmadas • "
            f"{counts[DecisionStatus.INCOMPLETE] + counts[DecisionStatus.CONFLICT]} para revisão • "
            f"{counts[DecisionStatus.PENDING]} bloqueadas/com falha • "
            f"{counts[DecisionStatus.NO_MATCH]} sem correspondência."
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
                f"{result_label(result)}" + (" • cache" if result.cached else "")
            )
            lines.append(result.message)
            lines.append(f"Tentativas HTTP: {result.attempts}")
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

    def _lyric_options(self, *, refresh=None):
        return LyricOptions(
            self.lrclib_box.isChecked(),
            self.ovh_box.isChecked(),
            "full" if self.lyric_mode.currentIndex() == 0 else "quick",
            self.lyric_refresh.isChecked() if refresh is None else refresh,
        )

    def _details_tab_changed(self, _):
        if self.tabs.currentWidget() in (
            self.review_tab,
            self.operations_panel,
            self.batches_panel,
        ):
            height = self.result_split.height()
            self.result_split.setSizes([height // 3, height * 2 // 3])

    def start_lyrics(
        self,
        *,
        selected=True,
        import_path=None,
        pasted=None,
        read_only=False,
        records_override=None,
        automatic=False,
        batch_id=None,
        requests_override=None,
    ):
        if self.worker is not None or self._pending_reviews or not self._library_available:
            return
        if selected:
            rows = sorted(
                {
                    self.proxy.mapToSource(index).row()
                    for index in self.table.selectionModel().selectedRows()
                }
            )
            records = [self.model.records[row] for row in rows]
        else:
            records = list(self.model.records)
        records = [record for record in records if record.status != "error"]
        if records_override is not None:
            records = records_override
        if import_path is not None or pasted is not None:
            records = records[:1]
        if not records:
            return
        self._lyric_ids = {r.id for r in records}
        requests = []
        for record in records:
            if requests_override is not None:
                break
            draft = self.model.reviews[record.id]
            requests.append(
                (
                    record,
                    " / ".join(draft.field("artist").proposed),
                    " / ".join(draft.field("title").proposed),
                    recognition_key(self.model.identifications.get(record.id)),
                )
            )
        worker = LyricsWorker(
            requests_override if requests_override is not None else requests,
            self.settings,
            self._lyric_options(),
            self.library_path,
            self,
            import_path=import_path,
            pasted=pasted,
            read_only=read_only,
            batch_id=batch_id,
        )
        self.worker = worker
        worker.batch_ready.connect(self._batch_changed)
        self._lyric_failure = False
        worker.result_ready.connect(self._lyrics_result)
        worker.review_ready.connect(self._lyrics_review)
        worker.progress_ready.connect(self._analysis_progress)
        worker.failed.connect(self._lyrics_failed)
        worker.completed.connect(self._lyrics_complete)
        worker.finished.connect(self._thread_finished)
        self.progress.setRange(0, len(records))
        self.progress.setValue(0)
        self.cancel_button.setText("Cancelar letras")
        self.cancel_button.setEnabled(True)
        self.status.setText("Preparando letras para revisão…")
        if not automatic:
            self.tabs.setCurrentWidget(self.review_tab)
        self.review_panel.pages.setCurrentIndex(1)
        self._update_actions()
        worker.start()

    @Slot(object)
    def _lyrics_result(self, report):
        self.model.update_lyrics(report)
        self._show_details()

    @Slot(object)
    def _lyrics_review(self, draft):
        self.model.update_review(draft)
        self._show_details()

    @Slot(str)
    def _lyrics_failed(self, message):
        self._lyric_failure = True
        self.status.setText(message)
        self._on_issue(ScanIssue("Letras", message))

    @Slot(int, int, bool)
    def _lyrics_complete(self, count, total, cancelled):
        if self._batch_paused:
            self.status.setText(f"Letras pausadas • {count}/{total}. Retome em Lotes e relatórios.")
            return
        if not cancelled and self.operations_panel.auto_lyrics.isChecked():
            self._auto_apply_ids = {
                r.id
                for r in self.model.records
                if r.id in self._lyric_ids
                and automatic_fields(
                    r,
                    self.model.identifications.get(r.id),
                    self.model.reviews[r.id],
                    self.model.lyrics.get(r.id),
                    apply_lyrics=True,
                )
            }
            self._auto_apply_stage = "lyrics"
        if not self._lyric_failure:
            self.status.setText(
                f"Letras: {count}/{total} arquivos • "
                + ("cancelado." if cancelled else "resultados salvos para revisão.")
            )

    def _import_lyrics(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar letra", "", "Letras (*.txt *.lrc)")
        if path:
            self.start_lyrics(import_path=path)

    def _paste_lyrics(self):
        text, accepted = QInputDialog.getMultiLineText(self, "Colar letra", "Letra simples:")
        if accepted:
            self.start_lyrics(pasted=text)

    @Slot(object)
    def _review_changed(self, draft):
        self.operations_panel.invalidate_plan()
        self.model.update_review(draft)
        self._pending_reviews[draft.file_id] = draft
        self._review_save_failed = False
        self._review_timer.start(250)
        self._update_actions()

    @Slot(object)
    def _approve_review(self, draft):
        self.operations_panel.invalidate_plan()
        self.model.update_review(draft.invalidate())
        self._pending_reviews[draft.file_id] = draft
        self._review_save_failed = False
        self._flush_reviews()

    def _flush_reviews(self):
        if self.worker is not None or not self._pending_reviews or self._review_save_failed:
            return
        self._review_timer.stop()
        self._review_batch = dict(self._pending_reviews)
        self._pending_reviews.clear()
        worker = SaveReviewsWorker(self.library_path, list(self._review_batch.values()), self)
        self.worker = worker
        worker.saved.connect(self._review_saved)
        worker.failed.connect(self._review_failed)
        worker.finished.connect(self._thread_finished)
        self.status.setText("Salvando revisão dos campos…")
        self._update_actions()
        worker.start()

    @Slot(object)
    def _review_saved(self, draft):
        self._review_batch.pop(draft.file_id, None)
        self.model.update_review(draft)
        self.review_panel.mark_saved(draft)
        self.status.setText(f"Revisão salva • {len(draft.approved_fields)} campo(s) aprovado(s).")

    @Slot(str)
    def _review_failed(self, message):
        self._pending_reviews.update(self._review_batch)
        self._review_batch.clear()
        self._review_save_failed = True
        self._closing = False
        self._on_failed(message)

    def _plan_changes(self, selected):
        if selected:
            ids = {
                self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()
            }
            records = [self.model.records[i] for i in sorted(ids)]
        else:
            records = list(self.model.records)
        if records:
            self._start_operation("plan", records=records)

    def _start_operation(self, task, **arguments):
        if self.worker is not None or self._pending_reviews or not self._library_available:
            return
        self.player.shutdown()
        worker = OperationsWorker(
            self.library_path,
            self.settings,
            self._preferences(),
            task,
            self,
            **arguments,
        )
        self.worker = worker
        worker.batch_ready.connect(self._batch_changed)
        worker.ready.connect(self._operation_ready)
        worker.failed.connect(self._operation_failed)
        worker.stage_ready.connect(self._operation_stage)
        worker.finished.connect(self._thread_finished)
        self.progress.setRange(0, 0)
        self.cancel_button.setText("Cancelar após etapa segura")
        self.cancel_button.setEnabled(True)
        self.status.setText("Preparando alterações e backups…")
        if task != "auto":
            self.tabs.setCurrentWidget(self.operations_panel)
        self._update_actions()
        worker.start()

    @Slot(str, str, str)
    def _operation_stage(self, file_id, state, message):
        self.status.setText(message or "Aplicando alteração com recuperação protegida…")

    @Slot(str)
    def _operation_failed(self, message):
        self.operations_panel.message.setText(message)
        self._on_issue(ScanIssue("Aplicação", message))
        self.status.setText(message)

    @Slot(object)
    def _operation_ready(self, result):
        selected = {
            self.model.records[self.proxy.mapToSource(i).row()].id
            for i in self.table.selectionModel().selectedRows()
        }
        self.model.clear()
        self._library_loaded(result["state"])
        self.operations_panel.show_history(result["history"])
        self.batches_panel.show_batches(result.get("batches", []))
        if (
            not result.get("paused")
            and not result["cancelled"]
            and (
                result["task"] == "apply"
                or result["task"] == "auto"
                and result.get("stage") != "lyrics"
            )
            and self.operations_panel.auto_lyrics.isChecked()
        ):
            relevant = {row["file_id"] for row in result["results"] if row["state"] == "completed"}
            if result["task"] == "auto" and result["plan"]:
                relevant.update(i.record.id for i in result["plan"].items if i.status == "noop")
            self._auto_lyrics_ids = {
                r.id
                for r in self.model.records
                if r.id in relevant
                and not r.tags.has_lyrics
                and identity_is_valid(
                    r, self.model.identifications.get(r.id), self.model.reviews[r.id]
                )
            }
        for row in range(self.proxy.rowCount()):
            if (
                self.model.records[self.proxy.mapToSource(self.proxy.index(row, 0)).row()].id
                in selected
            ):
                self.table.selectRow(row)
                break
        if result["task"] == "plan":
            self.operations_panel.show_plan(result["plan"])
            self.status.setText(self.operations_panel.message.text())
        else:
            if result["plan"]:
                self.operations_panel.show_plan(result["plan"])
                for item in result["plan"].items:
                    if item.status == "blocked":
                        self._on_issue(ScanIssue(item.record.path, item.message))
            self.operations_panel.invalidate_plan()
            completed = sum(r["state"] == "completed" for r in result["results"])
            failed = sum(r["state"] != "completed" for r in result["results"])
            if result["plan"]:
                failed += sum(item.status == "blocked" for item in result["plan"].items)
            message = (
                f"{'Aplicação automática' if result['task'] == 'auto' else 'Alterações'}: "
                f"{completed} concluída(s), {failed} bloqueada(s)/com falha. "
                + ("Cancelado em ponto seguro. " if result["cancelled"] else "")
                + "Consulte Backups e restauração."
            )
            if result["task"] == "recover":
                message = "Recuperação verificada. Confira o histórico de backups."
            if result["task"] == "auto" and result["plan"] and not result["plan"].ready:
                message = (
                    "Identificação concluída; nenhuma alteração automática necessária ou elegível."
                )
            if result.get("paused"):
                message = "Aplicação pausada em ponto seguro. Retome em Lotes e relatórios."
            self.operations_panel.message.setText(message)
            self.status.setText(message)
            for row in result["results"]:
                if row.get("message"):
                    self._on_issue(ScanIssue("Aplicação", row["message"]))

    @Slot(str, str)
    def _batch_changed(self, batch_id, state):
        self._batch_paused = state == "paused"
        self._need_batch_refresh = state != "running"

    def _pause_batch(self):
        if self.worker is not None and hasattr(self.worker, "pause"):
            self.worker.pause()
            self._auto_apply_ids.clear()
            self._auto_lyrics_ids.clear()
            self.pause_button.setEnabled(False)
            self.status.setText(
                "Pausando: aguardando as músicas em andamento chegarem a um ponto seguro…"
            )

    def _start_report(self, *, destination=None, file_ids=None, batch_id=None):
        if self.worker is not None or self._pending_reviews:
            return
        worker = ReportWorker(
            self.library_path,
            self,
            destination=destination,
            file_ids=file_ids,
            secrets=(self.settings.acoustid_key or "", self.settings.audd_token or ""),
            batch_id=batch_id,
        )
        self.worker = worker
        worker.ready.connect(self._report_ready)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(self._thread_finished)
        if destination or batch_id:
            self.status.setText(
                "Exportando relatório…" if destination else "Preparando retomada do lote…"
            )
            self.progress.setRange(0, 0)
        self._update_actions()
        worker.start()

    def _report_ready(self, result):
        if "resume_batch" in result:
            self._resume_payload = result
            return
        self.batches_panel.show_batches(result["batches"])
        if result["destination"]:
            self.status.setText(
                f"Relatório exportado: {result['count']} música(s) • {result['destination']}"
            )

    def _export_report(self, selected):
        ids = None
        if selected:
            ids = [
                self.model.records[self.proxy.mapToSource(i).row()].id
                for i in self.table.selectionModel().selectedRows()
            ]
            if not ids:
                self.status.setText("Selecione músicas na biblioteca antes de exportar.")
                return
        path, kind = QFileDialog.getSaveFileName(
            self, "Exportar relatório", "afinario-relatorio.json", "JSON (*.json);;CSV (*.csv)"
        )
        if path:
            if not Path(path).suffix:
                path += ".csv" if kind.startswith("CSV") else ".json"
            self._start_report(destination=path, file_ids=ids)

    def _resume_batch(self, row):
        self._start_report(batch_id=row["id"])

    def _launch_resume(self, result):
        if result.get("context"):
            self.model.restore_context(result["context"])
        row = result["resume_batch"]
        data = json.loads(row["payload_json"])
        batch_id = row["id"]
        self._batch_paused = False
        if row["kind"] == "scan":
            self.folders.clear()
            for root in data["roots"]:
                self.add_folder(Path(root))
            self.recursive.setChecked(data["recursive"])
            for name, box in self.format_boxes.items():
                box.setChecked(name in data["formats"])
            self.start_scan(batch_id=batch_id)
        elif row["kind"] == "recognition":
            for box, key in (
                (self.acoustid_box, "acoustid"),
                (self.shazam_box, "shazamio"),
                (self.audd_box, "audd"),
                (self.metadata_box, "musicbrainz"),
            ):
                box.setChecked(data["options"][key])
            records = [_record(item["payload_json"]) for item in result["items"]]
            self.start_identification(batch_id=batch_id, records_override=records)
        elif row["kind"] == "lyrics":
            requests = []
            for item in result["items"]:
                request = json.loads(item["payload_json"])
                record = _record(json.dumps(request["record"]))
                requests.append((record, request["artist"], request["title"], request["context"]))
            options = data["options"]
            self.lrclib_box.setChecked(options["lrclib"])
            self.ovh_box.setChecked(options["lyrics_ovh"])
            self.lyric_mode.setCurrentIndex(0 if options["mode"] == "full" else 1)
            self.lyric_refresh.setChecked(options["refresh"])
            self.start_lyrics(
                batch_id=batch_id,
                records_override=[r[0] for r in requests],
                requests_override=requests,
                import_path=data["import_path"],
                pasted=data["pasted"],
                read_only=data["read_only"],
            )
        else:
            self._start_operation(data["task"], batch_id=batch_id)

    def closeEvent(self, event):
        self.player.shutdown()
        if self.worker is not None:
            self._closing = True
            if hasattr(self.worker, "pause"):
                self.worker.pause()
            else:
                self.cancel_scan()
            self.status.setText("Encerrando a tarefa antes de fechar…")
            event.ignore()
        elif self._pending_reviews:
            self._closing = True
            self._review_save_failed = False
            self._flush_reviews()
            event.ignore()
        elif self._library_available and not self._preferences_saved:
            self._closing = True
            self._preferences_saved = True
            worker = SavePreferencesWorker(self.library_path, self._preferences(), self)
            self.worker = worker
            worker.failed.connect(self._on_failed)
            worker.finished.connect(self._thread_finished)
            self.status.setText("Salvando preferências…")
            self._update_actions()
            worker.start()
            event.ignore()
        else:
            event.accept()
