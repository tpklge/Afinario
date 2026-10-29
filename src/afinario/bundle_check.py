"""Offline installed-build check; never opens the user's library or credentials."""

import importlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import wave
from pathlib import Path

from afinario.audio import audio_duration, extract_sample, fingerprint, run_tool
from afinario.cancellation import hidden_process_options
from afinario.config import Settings
from afinario.diagnostics import doctor
from afinario.runtime import shazam_command


def main(destination: str) -> int:
    report = {"ok": False}
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtWidgets import QApplication

        import afinario.credentials
        from afinario.inventory import read_track
        from afinario.library import LibraryPreferences, LibraryStore
        from afinario.operations import OperationService
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
            "keyring.backends.macOS" if sys.platform == "darwin" else "keyring.backends.Windows",
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
            player.setSource(QUrl.fromLocalFile(str(source)))
            deadline = time.monotonic() + 10
            while player.duration() <= 0 and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.02)
            report["player_loaded"] = player.duration() > 0
            player.stop()
            player.setSource(QUrl())
            if not report["player_loaded"]:
                raise RuntimeError("O player incluído não conseguiu carregar o áudio local.")
            tagged = root / "original.flac"
            run_tool(settings.ffmpeg, ["-v", "error", "-n", "-i", str(source), str(tagged)])
            before = tagged.read_bytes()
            with LibraryStore(root / "operations.sqlite3") as library:
                run = library.start_scan(LibraryPreferences())
                record = library.save_scan_records(run, [read_track(tagged)])[0]
                library.finish_run(run, "completed", {})
                draft = library.load_reviews([record])[0]
                draft = draft.edit("title", ("Teste do pacote",))
                draft = draft.edit("filename", ("Conferência 日本語.flac",))
                library.save_review(draft.approve(("title", "filename")))
                service = OperationService(library, settings)
                plan = service.plan([record], consensus_names=False)
                result = service.apply(plan.id)[0]
                if result["state"] != "completed":
                    raise RuntimeError("Falha na escrita de tags/renomeação do pacote.")
                restored = service.restore(result["id"])
                report["metadata_restore_exact"] = (
                    restored["state"] == "completed" and tagged.read_bytes() == before
                )
                if not report["metadata_restore_exact"]:
                    raise RuntimeError("O teste de restauração do pacote não preservou os bytes.")
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
