"""Offline installed-build check; never opens the user's library or credentials."""

import importlib
import json
import shutil
import struct
import subprocess
import tempfile
import time
import traceback
import wave
from pathlib import Path

from afinario.audio import audio_duration, extract_sample, fingerprint
from afinario.cancellation import hidden_process_options
from afinario.config import Settings
from afinario.diagnostics import doctor
from afinario.runtime import shazam_command


def main(destination: str) -> int:
    report = {"ok": False}
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtWidgets import QApplication

        import afinario.credentials
        from afinario.ui.window import MainWindow

        # Isolated GUI/library check: never access real user credentials or songs.
        app = QApplication.instance() or QApplication(["Afinario bundle check"])
        output = QAudioOutput()
        player = QMediaPlayer()
        player.setAudioOutput(output)
        settings = Settings()
        report["environment"] = doctor(settings)
        if not all(item["available"] for item in report["environment"]["tools"].values()):
            raise RuntimeError("Ferramentas de áudio ausentes no pacote.")
        for name in (
            "afinario.ui.window",
            "keyring.backends.Windows",
            "mutagen",
            "httpx",
            "shazamio",
        ):
            importlib.import_module(name)
        with tempfile.TemporaryDirectory(prefix="Afinario áudio 日本語 ") as directory:
            root = Path(directory)

            class EmptyVault:
                def get_password(self, service, account):
                    return None

            afinario.credentials.system_backend = EmptyVault
            window = MainWindow(
                settings, library_path=root / "library.sqlite3", restore_settings=False
            )
            window.show()
            deadline = time.monotonic() + 30
            timer = QTimer()

            def close_when_ready():
                ready = window._library_available and window.worker is None
                if ready or time.monotonic() >= deadline:
                    report["main_window_ready"] = ready
                    timer.stop()
                    window.close()

            timer.timeout.connect(close_when_ready)
            timer.start(100)
            app.exec()
            if not report.get("main_window_ready"):
                raise RuntimeError("A janela não concluiu a abertura da biblioteca temporária.")
            source = root / "teste original.wav"
            with wave.open(str(source), "wb") as stream:
                stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                stream.writeframes(struct.pack("<h", 1000) * 16000 * 20)
            report["duration"] = audio_duration(source, settings.ffprobe)
            extract_sample(source, root / "trecho.wav", 0, settings.ffmpeg)
            value, _ = fingerprint(source, settings.fpcalc)
            report["fingerprint_available"] = bool(value)
            command = shazam_command(source)
            worker = subprocess.run(
                [command[0], "--worker-self-test"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=True,
                **hidden_process_options(),
            )
            report["worker"] = json.loads(worker.stdout)
        report["ok"] = bool(report["worker"]["shazamio"] and report["fingerprint_available"])
        report["python_on_path"] = shutil.which("python") is not None
    except Exception:
        report["error"] = traceback.format_exc()
    Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
