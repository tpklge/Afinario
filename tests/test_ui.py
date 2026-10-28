import shutil
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QAbstractItemModelTester  # noqa: E402

from afinario.config import Settings  # noqa: E402
from afinario.identification import IdentificationReport  # noqa: E402
from afinario.inventory import InventoryRecord, TrackTags  # noqa: E402
from afinario.resolver import Decision, DecisionStatus  # noqa: E402
from afinario.ui.model import LibraryModel  # noqa: E402
from afinario.ui.window import MainWindow  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def test_table_model_contract_and_insertions(qtbot):
    model = LibraryModel()
    tester = QAbstractItemModelTester(model, QAbstractItemModelTester.FailureReportingMode.Warning)
    model.append_records(
        [InventoryRecord("/library/a.mp3", "MP3", 10, 20, tags=TrackTags(artist=("Artista",)))]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 1)) == "Artista"
    assert not (model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
    model.clear()
    assert model.rowCount() == 0
    assert tester.model() is model


def test_window_scans_filters_and_displays_details(qtbot, tmp_path):
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    (tmp_path / "broken.mp3").write_bytes(b"invalid")
    window = MainWindow()
    qtbot.addWidget(window)
    window.add_folder(tmp_path)
    window.add_folder(tmp_path)
    assert window.folders.count() == 1
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert window.model.rowCount() == 2
    assert "1 músicas" in window.status.text()
    window.search.setText("Artista de teste")
    assert window.proxy.rowCount() == 1
    window.table.selectRow(0)
    assert "Título sintético" in window.details.toPlainText()
    assert "Capas: 1" in window.details.toPlainText()
    window.search.setText("missing")
    assert window.proxy.rowCount() == 0


def test_ui_keeps_processing_events_and_can_cancel(qtbot, tmp_path, monkeypatch):
    import afinario.inventory as inventory

    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    entered, release = threading.Event(), threading.Event()
    original = inventory.read_track

    def slow_read(path):
        entered.set()
        assert release.wait(5)
        return original(path)

    monkeypatch.setattr(inventory, "read_track", slow_read)
    window = MainWindow()
    qtbot.addWidget(window)
    window.add_folder(tmp_path)
    window.scan_button.click()
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat), timeout=1000)
        assert not window.scan_button.isEnabled()
        window.cancel_button.click()
        assert not window.cancel_button.isEnabled()
    finally:
        release.set()
        qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert window._summary.cancelled
    assert "cancelada" in window.status.text()


def test_close_waits_for_worker_without_freezing(qtbot, tmp_path, monkeypatch):
    import afinario.inventory as inventory

    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    entered, release = threading.Event(), threading.Event()
    original = inventory.read_track

    def slow_read(path):
        entered.set()
        release.wait(5)
        return original(path)

    monkeypatch.setattr(inventory, "read_track", slow_read)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.add_folder(tmp_path)
    window.scan_button.click()
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        assert window.close() is False
        assert window.isVisible()
    finally:
        release.set()
        qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=3000)


def test_no_scan_without_roots_or_formats(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window.scan_button.isEnabled()
    window.add_folder(tmp_path)
    assert window.scan_button.isEnabled()
    for box in window.format_boxes.values():
        box.setChecked(False)
    assert not window.scan_button.isEnabled()


def test_access_errors_are_visible_without_losing_valid_tracks(qtbot, tmp_path):
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    window = MainWindow()
    qtbot.addWidget(window)
    window.add_folder(tmp_path / "missing")
    window.add_folder(tmp_path)
    window.scan_button.click()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert window.model.rowCount() == 1
    assert "Não foi possível acessar" in window.issues.toPlainText()
    assert window._summary.inaccessible_paths == 1


def test_selected_audio_is_identified_without_changing_current_tags(qtbot, tmp_path, monkeypatch):
    calls = []
    for name in ("first", "second"):
        shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / f"{name}.mp3")
    monkeypatch.setattr(
        "afinario.ui.recognition_worker.app_paths", lambda: {"cache": str(tmp_path / "cache")}
    )

    def identify(self, record, options, stage):
        calls.append((record, options))
        stage("Consultando serviços")
        return IdentificationReport(
            record.id,
            record.path,
            Decision(
                DecisionStatus.AGREEMENT,
                "Artista reconhecido",
                "Título reconhecido",
                reasons=("Teste de integração da interface.",),
                proposed_fields=("artist", "title"),
            ),
        )

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    window = MainWindow(Settings(acoustid_key="test-key"))
    qtbot.addWidget(window)
    window.add_folder(tmp_path)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert calls == []  # Scanning never silently starts network recognition.
    window.search.setText("second.mp3")
    window.table.selectRow(0)
    window.shazam_box.setChecked(True)
    window.recognize_selected.click()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert len(calls) == 1
    record, options = calls[0]
    assert Path(record.path).name == "second.mp3"
    assert options.shazamio
    assert len(window.model.identifications) == 1
    row = window.model._rows[record.id]
    assert window.model.data(window.model.index(row, 1)) == "Artista de teste"
    assert window.model.data(window.model.index(row, 9)) == "Artista reconhecido"
    assert window.model.data(window.model.index(row, 11)) == "Fontes concordam"
    assert "Título reconhecido" in window.recognition_details.toPlainText()


def test_cancel_identification_keeps_ui_responsive_and_previous_results(
    qtbot, tmp_path, monkeypatch
):
    from afinario.cancellation import AnalysisCancelled

    for name in ("first", "second"):
        shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / f"{name}.mp3")
    monkeypatch.setattr(
        "afinario.ui.recognition_worker.app_paths", lambda: {"cache": str(tmp_path / "cache")}
    )
    entered = threading.Event()
    calls = []

    def identify(self, record, options, stage):
        calls.append(record.id)
        stage("Identificando")
        if len(calls) == 1:
            return IdentificationReport(record.id, record.path, Decision(DecisionStatus.NO_MATCH))
        entered.set()
        if not self.stop.wait(5):
            raise RuntimeError("Cancellation not delivered")
        raise AnalysisCancelled

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    window = MainWindow(Settings(acoustid_key="test-key"))
    qtbot.addWidget(window)
    window.add_folder(tmp_path)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    window.recognize_all.click()
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat), timeout=1000)
        assert not window.scan_button.isEnabled()
    finally:
        window.cancel_scan()
        qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert len(window.model.identifications) == 1
    assert "cancelada" in window.status.text()
    assert "Análise cancelada" in window.model.analysis_states.values()


def test_gui_receives_local_tools_configuration(tmp_path, monkeypatch):
    from afinario.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "afinario.local.toml").write_text(
        '[tools]\nfpcalc = "custom-fpcalc"', encoding="utf-8"
    )
    captured = []
    monkeypatch.setattr(
        "afinario.ui.app.main", lambda args, settings: captured.append(settings) or 0
    )
    assert main(["gui"]) == 0
    assert captured[0].fpcalc == "custom-fpcalc"


def test_audd_gui_honors_paid_limit_with_parallel_tracks(qtbot, tmp_path, monkeypatch):
    import httpx

    from afinario.transport import Transport

    for extension in ("mp3", "flac"):
        shutil.copyfile(FIXTURES / f"tone.{extension}", tmp_path / f"tone.{extension}")
    monkeypatch.setattr(
        "afinario.ui.recognition_worker.app_paths", lambda: {"cache": str(tmp_path / "cache")}
    )
    monkeypatch.setattr(
        "afinario.identification.extract_sample",
        lambda path, target, *args, **kwargs: target.write_bytes(b"synthetic WAV"),
    )
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "success", "result": None})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            "afinario.ui.recognition_worker.Transport",
            lambda settings, cancelled: Transport(settings, client, cancelled),
        )
        window = MainWindow(Settings(audd_token="TEST-TOKEN", audd_max_requests=1))
        qtbot.addWidget(window)
        window.add_folder(tmp_path)
        window.start_scan()
        qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
        window.acoustid_box.setChecked(False)
        window.audd_box.setChecked(True)
        window.recognize_all.click()
        qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
        assert len(calls) == 1
        assert "1/1" in window.audd_usage.text()
        assert len(window.model.identifications) == 2
        statuses = [
            result.status.value
            for outcome in window.model.identifications.values()
            for result in outcome.results
        ]
        assert sorted(statuses) == ["blocked", "not_found"]


def test_audd_token_dialog_is_masked_and_does_not_persist(qtbot):
    from PySide6.QtWidgets import QLineEdit

    from afinario.ui.recognition_settings import RecognitionSettingsDialog

    dialog = RecognitionSettingsDialog(Settings(audd_token="TEST-TOKEN"))
    qtbot.addWidget(dialog)
    assert dialog.audd_token.echoMode() == QLineEdit.EchoMode.Password
    dialog.audd_token.setText("NEW-TOKEN")
    assert dialog.selected_settings().audd_token == "NEW-TOKEN"
