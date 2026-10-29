"""Local audio preview. Selecting a row never starts playback or uploads audio."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from afinario.inventory import is_link


def clock_text(milliseconds):
    seconds = max(0, int(milliseconds)) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


class AudioPlayer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.backend = None
        self.output = None
        self._duration = 0
        self._failed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        self.track = QLabel("Ouvir: selecione uma música na biblioteca.")
        self.track.setTextFormat(Qt.TextFormat.PlainText)
        self.track.setWordWrap(True)
        layout.addWidget(self.track)
        row = QHBoxLayout()
        self.play_button = QPushButton("Reproduzir")
        self.play_button.setAccessibleName("Reproduzir ou pausar a música selecionada")
        self.stop_button = QPushButton("Parar")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName("Posição da reprodução")
        self.seek.setRange(0, 0)
        self.time = QLabel("0:00 / 0:00")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setAccessibleName("Volume")
        self.volume.setRange(0, 100)
        self.volume.setValue(50)
        self.volume.setMaximumWidth(100)
        self.volume.setToolTip("Volume da reprodução")
        for widget in (
            self.play_button,
            self.stop_button,
            self.seek,
            self.time,
            QLabel("Volume"),
            self.volume,
        ):
            row.addWidget(widget, 1 if widget is self.seek else 0)
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.message)
        self.play_button.clicked.connect(self.toggle)
        self.stop_button.clicked.connect(self.stop)
        self.seek.sliderMoved.connect(self._seek)
        self.volume.valueChanged.connect(self._volume)
        self._controls()

    def set_record(self, record):
        path = record.path if record is not None and record.status != "error" else None
        if path == self.path:
            return
        self.stop()
        if self.backend is not None:
            self.backend.setSource(QUrl())
        self.path = path
        self._failed = False
        self.message.clear()
        self.track.setText(
            "Ouvir: " + Path(path).name if path else "Ouvir: selecione uma música na biblioteca."
        )
        self.track.setToolTip(path or "")
        self._duration = round((record.duration or 0) * 1000) if path else 0
        self._position(0)
        self._controls()

    def _create_backend(self):
        # Multimedia is initialized only on an explicit request to listen.
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        self.backend = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(self.volume.value() / 100)
        self.backend.setAudioOutput(self.output)
        self.backend.positionChanged.connect(self._position)
        self.backend.durationChanged.connect(self._duration_changed)
        self.backend.seekableChanged.connect(self._controls)
        self.backend.playbackStateChanged.connect(self._controls)
        self.backend.errorOccurred.connect(self._error)

    def toggle(self):
        if not self.path:
            return
        path = Path(self.path)
        if not path.is_file() or is_link(path):
            self.message.setText("Arquivo indisponível. Confira a pasta e faça uma nova varredura.")
            return
        if self.backend is None:
            try:
                self._create_backend()
            except ImportError:
                self.message.setText("Instale as dependências do extra gui para ativar o player.")
                return
        if self.backend.playbackState() == self.backend.PlaybackState.PlayingState:
            self.backend.pause()
            return
        self.message.clear()
        url = QUrl.fromLocalFile(str(path.absolute()))
        if self._failed or self.backend.source() != url:
            self._failed = False
            self.backend.setSource(url)
        self.backend.play()

    def stop(self):
        if self.backend is not None:
            self.backend.stop()
        self._position(0)

    def _controls(self, *_):
        self.play_button.setEnabled(bool(self.path))
        active = self.backend is not None and self.backend.playbackState() != (
            self.backend.PlaybackState.StoppedState
        )
        playing = self.backend is not None and self.backend.playbackState() == (
            self.backend.PlaybackState.PlayingState
        )
        self.play_button.setText("Pausar" if playing else "Reproduzir")
        self.stop_button.setEnabled(active)
        self.seek.setEnabled(bool(self.backend is not None and self.backend.isSeekable()))

    def _position(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.time.setText(f"{clock_text(position)} / {clock_text(self._duration)}")

    def _duration_changed(self, duration):
        self._duration = duration
        self.seek.setRange(0, min(duration, 2_147_483_647))
        self._position(self.backend.position())

    def _seek(self, position):
        if self.backend is not None and self.backend.isSeekable():
            self.backend.setPosition(position)

    def _volume(self, value):
        if self.output is not None:
            self.output.setVolume(value / 100)

    def _error(self, *_):
        self._failed = True
        self.message.setText(
            "Não foi possível reproduzir este áudio. Confira o arquivo, "
            "o formato e a saída de som do sistema."
        )
        self._controls()

    def shutdown(self):
        self.stop()
        if self.backend is not None:
            self.backend.setSource(QUrl())
