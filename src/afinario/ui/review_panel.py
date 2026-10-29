import difflib
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from afinario.domain import RecordingCandidate
from afinario.lyrics import LYRIC_LABELS, candidate_key
from afinario.review import FIELD_LABELS, LYRIC_FIELDS
from afinario.ui.model import PROVIDER_LABELS


class ApprovalCheck(QCheckBox):
    """The entire labelled target is clickable, including its padding on macOS."""

    def __init__(self, text="Aprovar", parent=None):
        super().__init__(text, parent)
        self.setMinimumHeight(42)
        self.setMinimumWidth(110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QCheckBox { spacing: 10px; padding: 7px; border: 1px solid #607c89;
                border-radius: 5px; font-weight: 600; background: #253543; }
            QCheckBox:hover { border: 2px solid #76ddc7; }
            QCheckBox:focus { border: 2px solid #ffffff; }
            QCheckBox::indicator { width: 24px; height: 24px; border: 2px solid #b4c8d2;
                border-radius: 4px; background: #18212c; }
            QCheckBox::indicator:checked { background: #44b89c; border-color: #b5ffeb; }
            QCheckBox:checked { background: #245c51; }
            QCheckBox:disabled { color: #83949f; border-color: #3c4b58; background: #202b35; }
        """)
        self.toggled.connect(lambda checked: self.setText(("✓ " if checked else "") + text))

    def hitButton(self, pos):
        return self.rect().contains(pos)


class ReviewPanel(QWidget):
    draft_changed = Signal(object)
    save_requested = Signal(object)
    search_requested = Signal()
    embedded_requested = Signal()
    import_requested = Signal()
    paste_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.draft = None
        self._loading = False
        self._recordings, self._releases, self._lyrics = [], [], []
        layout = QVBoxLayout(self)
        note = QLabel("Escolha os campos e salve a aprovação para a etapa de aplicação.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.pages = QTabWidget()
        metadata = QWidget()
        meta_layout = QVBoxLayout(metadata)
        self.recording_candidates = QComboBox()
        self.recording_candidates.setPlaceholderText("Escolher identificação alternativa…")
        self.recording_candidates.setAccessibleName("Candidatos de identificação")
        self.release_candidates = QComboBox()
        self.release_candidates.setPlaceholderText("Escolher álbum/data explicitamente…")
        self.release_candidates.setAccessibleName("Lançamentos possíveis")
        meta_layout.addWidget(self.recording_candidates)
        meta_layout.addWidget(self.release_candidates)
        grid = QGridLayout()
        for column, label in enumerate(("Campo", "Atual", "Proposto", "Aprovar")):
            grid.addWidget(QLabel(label), 0, column)
        self.current, self.proposed, self.checks = {}, {}, {}
        for row, (name, label) in enumerate(FIELD_LABELS.items(), 1):
            if name in LYRIC_FIELDS:
                continue
            current, proposed, check = QLineEdit(), QLineEdit(), ApprovalCheck()
            current.setReadOnly(True)
            current.setAccessibleName(f"{label} atual")
            proposed.setAccessibleName(f"{label} proposto")
            check.setAccessibleName(f"Aprovar {label}")
            self.current[name], self.proposed[name], self.checks[name] = current, proposed, check
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(current, row, 1)
            grid.addWidget(proposed, row, 2)
            grid.addWidget(check, row, 3)
            proposed.textEdited.connect(lambda text, key=name: self._edit(key, text))
        meta_layout.addLayout(grid)
        meta_layout.addStretch(1)
        self.pages.addTab(metadata, "Metadados")

        lyrics = QWidget()
        lyric_layout = QVBoxLayout(lyrics)
        self.lyric_status = QLabel(
            "Leia a letra embutida, importe ou consulte as fontes de letras."
        )
        self.lyric_status.setWordWrap(True)
        self.lyric_status.setTextFormat(Qt.TextFormat.PlainText)
        lyric_layout.addWidget(self.lyric_status)
        actions = QHBoxLayout()
        for label, signal in (
            ("Buscar letras", self.search_requested),
            ("Ler embutida", self.embedded_requested),
            ("Importar TXT/LRC…", self.import_requested),
            ("Colar letra…", self.paste_requested),
        ):
            button = QPushButton(label)
            button.clicked.connect(signal.emit)
            actions.addWidget(button)
        lyric_layout.addLayout(actions)
        self.lyric_candidates = QComboBox()
        self.lyric_candidates.setPlaceholderText("Escolher uma letra para comparar…")
        self.lyric_candidates.setAccessibleName("Candidatos de letras")
        lyric_layout.addWidget(self.lyric_candidates)
        self.replace_lyrics = QCheckBox("Autorizar substituição da letra existente")
        lyric_layout.addWidget(self.replace_lyrics)
        formats = QTabWidget()
        for name in LYRIC_FIELDS:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            check = ApprovalCheck(f"Aprovar {FIELD_LABELS[name].lower()}")
            self.checks[name] = check
            page_layout.addWidget(check)
            texts = QHBoxLayout()
            for target, label, readonly in (
                (self.current, "Atual", True),
                (self.proposed, "Proposta", False),
            ):
                column = QVBoxLayout()
                column.addWidget(QLabel(label))
                editor = QPlainTextEdit()
                editor.setMinimumHeight(100)
                editor.setReadOnly(readonly)
                editor.setAccessibleName(f"{FIELD_LABELS[name]} {label.lower()}")
                target[name] = editor
                column.addWidget(editor)
                texts.addLayout(column)
                if not readonly:
                    editor.textChanged.connect(
                        lambda key=name, field=editor: self._edit(key, field.toPlainText())
                    )
            page_layout.addLayout(texts)
            formats.addTab(page, FIELD_LABELS[name])
        lyric_layout.addWidget(formats)
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setMaximumHeight(100)
        self.diff.setAccessibleName("Diferenças entre letras atuais e propostas")
        lyric_layout.addWidget(self.diff)
        self.pages.addTab(lyrics, "Letras e diferenças")
        layout.addWidget(self.pages)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.save_button = QPushButton("Salvar aprovação dos campos marcados")
        self.save_button.clicked.connect(self._approve)
        layout.addWidget(self.save_button)
        self.recording_candidates.currentIndexChanged.connect(self._select_recording)
        self.release_candidates.currentIndexChanged.connect(self._select_release)
        self.lyric_candidates.currentIndexChanged.connect(self._select_lyric)
        self.replace_lyrics.toggled.connect(self._replacement)
        self.setEnabled(False)

    def show_record(self, record, draft, identification=None, lyrics=None):
        self._loading = True
        self.draft = draft
        self._recordings, self._releases = [], []
        self.recording_candidates.clear()
        self.release_candidates.clear()
        for result in identification.results if identification else ():
            for candidate in result.candidates:
                if (
                    isinstance(candidate, RecordingCandidate)
                    and candidate.artist
                    and candidate.title
                ):
                    self._recordings.append(candidate)
                    self.recording_candidates.addItem(
                        f"{PROVIDER_LABELS.get(candidate.provider, candidate.provider)}: "
                        f"{candidate.artist} — {candidate.title}"
                    )
            for release in result.releases:
                self._releases.append((result.provider, release))
                self.release_candidates.addItem(f"{release.title} ({release.date or 'sem data'})")
        self.recording_candidates.setCurrentIndex(-1)
        self.release_candidates.setCurrentIndex(-1)
        self._lyrics = list(lyrics.candidates if lyrics else ())
        self.lyric_candidates.clear()
        for candidate in self._lyrics:
            label = candidate.source or candidate.provider
            if candidate.provider == "local" and candidate.source:
                label = Path(candidate.source).name
            kind = (
                "instrumental"
                if candidate.instrumental
                else (
                    "simples + LRC"
                    if candidate.plain_text and candidate.synced_text
                    else "LRC"
                    if candidate.synced_text
                    else "simples"
                )
            )
            self.lyric_candidates.addItem(f"{label} • {kind}")
            details = [candidate.source or candidate.provider]
            if candidate.external_id:
                details.append(f"ID da fonte: {candidate.external_id}")
            if lyrics:
                assessment = next(
                    (item for item in lyrics.assessments if item.key == candidate_key(candidate)),
                    None,
                )
                if assessment:
                    details.extend(assessment.reasons)
            self.lyric_candidates.setItemData(
                self.lyric_candidates.count() - 1,
                "\n".join(details),
                Qt.ItemDataRole.ToolTipRole,
            )
        self.lyric_candidates.setCurrentIndex(-1)
        self.lyric_status.setText(
            (
                LYRIC_LABELS[lyrics.status]
                + f"\nBusca: {lyrics.artist} — {lyrics.title}\n"
                + "\n".join(lyrics.reasons)
            )
            if lyrics
            else "Leia a letra embutida, importe ou consulte as fontes de letras."
        )
        self._loading = False
        self._render()

    def _render(self):
        self._loading = True
        for item in self.draft.fields:
            for values, target in ((item.current, self.current), (item.proposed, self.proposed)):
                text = ("\n\n" if item.name in LYRIC_FIELDS else "; ").join(values)
                editor = target[item.name]
                if item.name in LYRIC_FIELDS:
                    editor.setPlainText(text)
                else:
                    editor.setText(text)
            self.proposed[item.name].setToolTip(f"Origem: {item.source}")
        self.replace_lyrics.setChecked(self.draft.replace_existing_lyrics)
        self.replace_lyrics.setEnabled(self.draft.has_existing_lyrics)
        self._loading = False
        self._checks()
        self._differences()

    def _checks(self):
        for item in self.draft.fields:
            check = self.checks[item.name]
            check.setChecked(item.approved)
            can_approve = item.changed and not self.draft.blocked_reason
            if item.name in LYRIC_FIELDS:
                can_approve = (
                    can_approve
                    and bool(item.proposed)
                    and (not self.draft.has_existing_lyrics or self.draft.replace_existing_lyrics)
                )
            check.setEnabled(bool(can_approve))
        self.message.setText(
            self.draft.blocked_reason
            or (
                f"Revisão {self.draft.revision} • "
                f"{len(self.draft.approved_fields)} campo(s) aprovado(s). "
                + (
                    "Letra existente preservada."
                    if self.draft.has_existing_lyrics and not self.draft.replace_existing_lyrics
                    else ""
                )
            )
        )

    def _differences(self):
        lines = []
        for name in LYRIC_FIELDS:
            item = self.draft.field(name)
            if item.changed:
                lines.extend(
                    difflib.unified_diff(
                        "\n\n".join(item.current).splitlines(),
                        "\n\n".join(item.proposed).splitlines(),
                        fromfile=f"Atual: {FIELD_LABELS[name]}",
                        tofile="Proposta",
                        lineterm="",
                    )
                )
        self.diff.setPlainText("\n".join(lines))

    def _publish(self, draft, *, render=False):
        self.draft = draft
        if render:
            self._render()
        else:
            self._checks()
            self._differences()
        self.message.setText("Edição pendente de gravação; aprovações anteriores invalidadas.")
        self.draft_changed.emit(draft)

    def _edit(self, name, text):
        if self._loading or self.draft is None:
            return
        values = (text,) if text else ()
        if name not in LYRIC_FIELDS and name != "filename":
            values = tuple(value.strip() for value in text.split(";") if value.strip())
        draft = self.draft.edit(name, values)
        if name in ("artist", "title"):
            self._loading = True
            for key in LYRIC_FIELDS:
                self.proposed[key].setPlainText("\n\n".join(draft.field(key).proposed))
            self._loading = False
        self._publish(draft)

    def _select_recording(self, index):
        if self._loading or self.draft is None or index < 0:
            return
        candidate = self._recordings[index]
        draft = self.draft.edit(
            "artist", (candidate.artist,), f"{candidate.provider}:{candidate.external_id}"
        )
        draft = draft.edit(
            "title", (candidate.title,), f"{candidate.provider}:{candidate.external_id}"
        )
        self._publish(draft, render=True)

    def _select_release(self, index):
        if self._loading or self.draft is None or index < 0:
            return
        provider, release = self._releases[index]
        source = f"{provider}:{release.external_id}"
        draft = self.draft.edit("album", (release.title,), source)
        if release.date:
            draft = draft.edit("date", (release.date,), source)
        self._publish(draft, render=True)

    def _select_lyric(self, index):
        if not self._loading and self.draft is not None and index >= 0:
            self._publish(self.draft.select_lyrics(self._lyrics[index]), render=True)

    def _replacement(self, allowed):
        if not self._loading and self.draft is not None:
            self._publish(self.draft.allow_replacement(allowed))

    def _approve(self):
        if self.draft is None:
            return
        try:
            draft = self.draft.approve(
                name for name, check in self.checks.items() if check.isChecked()
            )
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.save_requested.emit(draft)

    def mark_saved(self, draft):
        if self.draft is not None and self.draft.file_id == draft.file_id:
            self.draft = draft
            self._checks()

    def clear(self):
        self._loading = True
        self.draft = None
        for editor in (*self.current.values(), *self.proposed.values()):
            editor.clear()
        self._loading = False
        self.setEnabled(False)
