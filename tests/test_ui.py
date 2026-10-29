import shutil
import sqlite3
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


def open_window(qtbot, *args, **kwargs):
    window = MainWindow(*args, **kwargs)
    qtbot.addWidget(window, before_close_func=lambda widget: close_window(qtbot, widget))
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    return window


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
    window = open_window(qtbot)
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
    window = open_window(qtbot)
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
    window = open_window(qtbot)
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
    window = open_window(qtbot)
    assert not window.scan_button.isEnabled()
    window.add_folder(tmp_path)
    assert window.scan_button.isEnabled()
    for box in window.format_boxes.values():
        box.setChecked(False)
    assert not window.scan_button.isEnabled()


def test_access_errors_are_visible_without_losing_valid_tracks(qtbot, tmp_path):
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    window = open_window(qtbot)
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
    window = open_window(qtbot, Settings(acoustid_key="test-key"))
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
    call_lock = threading.Lock()

    def identify(self, record, options, stage):
        with call_lock:
            calls.append(record.id)
            first = len(calls) == 1
        stage("Identificando")
        if first:
            return IdentificationReport(record.id, record.path, Decision(DecisionStatus.NO_MATCH))
        entered.set()
        if not self.stop.wait(5):
            raise RuntimeError("Cancellation not delivered")
        raise AnalysisCancelled

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    window = open_window(qtbot, Settings(acoustid_key="test-key"))
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
        "afinario.ui.app.main", lambda args, settings, **kwargs: captured.append(settings) or 0
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
        window = open_window(qtbot, Settings(audd_token="TEST-TOKEN", audd_max_requests=1))
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


def test_audd_token_dialog_is_masked_before_saving(qtbot):
    from PySide6.QtWidgets import QLineEdit

    from afinario.ui.recognition_settings import RecognitionSettingsDialog

    dialog = RecognitionSettingsDialog(Settings(audd_token="TEST-TOKEN"))
    qtbot.addWidget(dialog)
    assert dialog.audd_token.echoMode() == QLineEdit.EchoMode.Password
    dialog.audd_token.setText("NEW-TOKEN")
    assert dialog.selected_settings().audd_token == "NEW-TOKEN"


def test_approval_target_can_be_clicked_outside_small_indicator(qtbot):
    from afinario.ui.review_panel import ApprovalCheck

    check = ApprovalCheck()
    qtbot.addWidget(check)
    check.resize(140, 44)
    check.show()
    from PySide6.QtCore import QPoint

    qtbot.mouseClick(
        check, Qt.MouseButton.LeftButton, pos=QPoint(check.width() - 5, check.height() // 2)
    )
    assert check.isChecked() and "✓" in check.text()
    check.setFocus()
    qtbot.keyClick(check, Qt.Key.Key_Space)
    assert not check.isChecked()


def test_pause_and_resume_identification_after_reopening_interface(qtbot, tmp_path, monkeypatch):
    from afinario.identification import IdentificationReport
    from afinario.resolver import Decision, DecisionStatus

    root = tmp_path / "music"
    root.mkdir()
    for i in range(3):
        shutil.copyfile(FIXTURES / "tone.mp3", root / f"{i}.mp3")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def identify(self, record, options, stage):
        calls.append(record.id)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return IdentificationReport(record.id, record.path, Decision(DecisionStatus.NO_MATCH))

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    window = open_window(qtbot, Settings(analysis_workers=1))
    window.add_folder(root)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None)
    window.start_identification()
    try:
        qtbot.waitUntil(entered.is_set)
        assert window.pause_button.isEnabled()
        window.pause_button.click()
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.worker is None)
    assert len(calls) == 1
    assert any(
        row["kind"] == "recognition" and row["state"] == "paused"
        for row in window.batches_panel.rows
    )
    close_window(qtbot, window)
    reopened = open_window(qtbot)
    index = next(i for i, r in enumerate(reopened.batches_panel.rows) if r["kind"] == "recognition")
    reopened.batches_panel.table.selectRow(index)
    assert reopened.batches_panel.resume.isEnabled()
    reopened.batches_panel.resume.click()
    qtbot.waitUntil(lambda: reopened.worker is None)
    assert len(calls) == 3 and len(set(calls)) == 3
    assert (
        next(r for r in reopened.batches_panel.rows if r["kind"] == "recognition")["state"]
        == "completed"
    )
    target = tmp_path / "ui-report.json"
    reopened._start_report(destination=str(target))
    qtbot.waitUntil(lambda: reopened.worker is None)
    assert target.exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_automatic_identity_then_lyrics_pipeline_uses_correct_current_tags(
    qtbot, tmp_path, monkeypatch
):
    import mutagen

    from afinario.domain import LyricCandidate, ProviderResult, RecordingCandidate, Status
    from afinario.identification import IdentificationReport, file_digest
    from afinario.lyrics import LyricReport, LyricStatus, candidate_key, embedded_lyrics, record_key
    from afinario.resolver import resolve

    root = tmp_path / "music"
    root.mkdir()
    source = root / "wrong.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", source)
    audio = mutagen.File(source)
    audio.tags.delall("USLT")
    audio.save()
    lyric_calls = []

    def identify(self, record, options, stage):
        results = tuple(
            ProviderResult(
                p,
                Status.OK,
                "test",
                (
                    RecordingCandidate(
                        p,
                        "id",
                        "Song",
                        "Artist",
                        duration=record.duration,
                        score=0.99 if p == "acoustid" else None,
                    ),
                ),
            )
            for p in ("acoustid", "audd")
        )
        return IdentificationReport(
            record.id,
            record.path,
            resolve(results, record.duration),
            results,
            file_digest(Path(record.path), threading.Event()),
            record.duration,
        )

    def query(self, record, artist, title, context, *args, **kwargs):
        lyric_calls.append(record.id)
        assert record.tags.artist == ("Artist",) and record.tags.title == ("Song",)
        candidate = LyricCandidate(
            "lrclib", "id", "Automatic lyric", title=title, artist=artist, duration=record.duration
        )
        return LyricReport(
            record.id,
            record.path,
            record_key(record),
            context,
            artist,
            title,
            LyricStatus.FOUND,
            (ProviderResult("lrclib", Status.OK, "test", (candidate,)),),
            recommended_key=candidate_key(candidate),
            source_sha256=file_digest(Path(record.path), threading.Event()),
        )

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    monkeypatch.setattr("afinario.ui.lyrics_worker.LyricsService.query", query)
    window = open_window(qtbot)
    window.add_folder(root)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None)
    window.start_identification()
    qtbot.waitUntil(lambda: window.worker is None, timeout=15000)
    assert len(lyric_calls) == 1
    current = window.model.records[0]
    assert Path(current.path).name == "Artist - Song.mp3"
    assert current.tags.artist == ("Artist",) and current.tags.title == ("Song",)
    assert any(c.plain_text == "Automatic lyric" for c in embedded_lyrics(Path(current.path)))
    assert len(window.operations_panel.history) == 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_preview_apply_approved_fields_and_restore_through_interface(qtbot, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "original.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", path)
    original = path.read_bytes()
    window = open_window(qtbot)
    window.operations_panel.auto_rename.setChecked(False)
    window.add_folder(music)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None)
    record = window.model.records[0]
    draft = window.model.reviews[record.id].edit("title", ("Approved title",))
    draft = draft.edit("filename", ("Approved filename.mp3",)).approve(("title", "filename"))
    window._approve_review(draft)
    qtbot.waitUntil(lambda: window.worker is None)
    window.operations_panel.preview_all.click()
    qtbot.waitUntil(lambda: window.worker is None)
    assert window.operations_panel.plan.ready[0].destination.endswith("Approved filename.mp3")
    assert path.read_bytes() == original
    window.operations_panel.apply_button.click()
    qtbot.waitUntil(lambda: window.worker is None)
    current = window.model.records[0]
    assert current.id == record.id
    assert current.tags.title == ("Approved title",)
    assert Path(current.path).exists() and not path.exists()
    window.operations_panel.backups.selectRow(0)
    assert window.operations_panel.restore_button.isEnabled()
    window.operations_panel.restore_button.click()
    qtbot.waitUntil(lambda: window.worker is None)
    assert path.read_bytes() == original
    assert window.model.records[0].id == record.id


def test_blocked_labels_distinguish_keys_tools_and_paid_limit(qtbot):
    from afinario.domain import ProviderResult, Status
    from afinario.ui.model import result_label

    assert (
        result_label(
            ProviderResult(
                "acoustid", Status.BLOCKED, "Executável auxiliar não encontrado no PATH."
            )
        )
        == "ferramenta ausente"
    )
    assert (
        result_label(ProviderResult("audd", Status.BLOCKED, "Limite AudD desta execução atingido."))
        == "limite da execução atingido"
    )
    assert (
        result_label(
            ProviderResult("acoustid", Status.BLOCKED, "Configure a chave de aplicação AcoustID.")
        )
        == "credencial ausente"
    )


def test_terminal_result_ignores_late_provider_stages(qtbot):
    window = open_window(qtbot)
    record = InventoryRecord("/library/a.mp3", "MP3", 10, 20)
    window.model.append_records([record])
    window._analysis_pending = {record.id}
    window._analysis_stage(record.id, "Consultando")
    window._analysis_result(
        IdentificationReport(record.id, record.path, Decision(DecisionStatus.PENDING))
    )
    window._analysis_complete(1, 1, False)
    status = window.status.text()
    window._analysis_stage(record.id, "Consultando novamente")
    assert window.status.text() == status
    assert "1 bloqueadas/com falha" in status
    assert "pendente" not in window.model.data(window.model.index(0, 11)).lower()
    assert record.id not in window.model.analysis_states


def test_saved_keys_call_both_providers_and_changed_answer_survives_restart(
    qtbot, tmp_path, monkeypatch
):
    import httpx

    from afinario.credentials import CredentialStore
    from afinario.transport import Transport

    path = tmp_path / "music"
    path.mkdir()
    shutil.copyfile(FIXTURES / "tone.mp3", path / "song.mp3")
    CredentialStore().save(Settings(acoustid_key="TEST-KEY", audd_token="TEST-TOKEN"))
    monkeypatch.setattr(
        "afinario.identification.fingerprint", lambda *a, **k: ("synthetic-fingerprint", 0.4)
    )
    monkeypatch.setattr(
        "afinario.identification.extract_sample",
        lambda source, target, *a, **k: target.write_bytes(b"synthetic WAV"),
    )
    calls = []
    title = ["First title"]

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "api.acoustid.org":
            assert b"TEST-KEY" in request.content
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [
                        {
                            "id": "id",
                            "score": 0.99,
                            "recordings": [
                                {
                                    "id": "recording",
                                    "title": title[0],
                                    "duration": 0.4,
                                    "artists": [{"name": "Artist"}],
                                }
                            ],
                        }
                    ],
                },
            )
        assert request.url.host == "api.audd.io"
        assert b"TEST-TOKEN" in request.content
        return httpx.Response(
            200,
            json={
                "status": "success",
                "result": {
                    "title": title[0],
                    "artist": "Artist",
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(
            "afinario.ui.recognition_worker.Transport",
            lambda settings, cancelled: Transport(settings, client, cancelled),
        )
        window = open_window(qtbot)
        assert window.settings.acoustid_key == "TEST-KEY"
        assert window.settings.audd_token == "TEST-TOKEN"
        window.add_folder(path)
        window.start_scan()
        qtbot.waitUntil(lambda: window.worker is None)
        window.audd_box.setChecked(True)
        window.audd_limit.setValue(1)
        window.metadata_box.setChecked(False)
        window.start_identification()
        qtbot.waitUntil(lambda: window.worker is None)
        assert sorted(calls) == ["api.acoustid.org", "api.audd.io"]
        assert "Aplicação automática: 1 concluída" in window.status.text()
        assert window.model.records[0].tags.artist == ("Artist",)
        assert window.model.records[0].tags.title == ("First title",)
        renamed = Path(window.model.records[0].path)
        assert renamed.name == "Artist - First title.mp3"
        assert renamed.exists()
        assert not (path / "song.mp3").exists()
        title[0] = "Second title"
        window.refresh_box.setChecked(True)
        window.start_identification()
        qtbot.waitUntil(lambda: window.worker is None)
        report = next(iter(window.model.identifications.values()))
        assert report.decision.status == DecisionStatus.CONFLICT
        assert "First title" in " ".join(report.decision.reasons)
        window.table.selectRow(0)
        assert any(
            "First title" in window.review_panel.recording_candidates.itemText(i)
            for i in range(window.review_panel.recording_candidates.count())
        )
        close_window(qtbot, window)
        reopened = open_window(qtbot)
        assert reopened.audd_box.isChecked()
        assert reopened.audd_limit.value() == 1
        restored = next(iter(reopened.model.identifications.values()))
        assert restored == report


def close_window(qtbot, window):
    window.show()
    window.close()
    qtbot.waitUntil(lambda: window.worker is None and not window.isVisible(), timeout=10000)


def test_library_and_recognition_survive_closing_and_rescanning(qtbot, tmp_path, monkeypatch):
    music = tmp_path / "músicas"
    music.mkdir()
    audio = music / "日本語.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", audio)
    original_bytes = audio.read_bytes()
    calls = []

    def identify(self, record, options, stage):
        calls.append(record.id)
        return IdentificationReport(
            record.id,
            record.path,
            Decision(
                DecisionStatus.AGREEMENT, "Artist", "Title", proposed_fields=("artist", "title")
            ),
        )

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    path = tmp_path / "application" / "library.sqlite3"
    window = open_window(qtbot, Settings(acoustid_key="SESSION-KEY"), library_path=path)
    window.add_folder(music)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    file_id = window.model.records[0].id
    window.start_identification()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    report = window.model.identifications[file_id]
    window.search.setText("日本語")
    window.settings = Settings(
        fpcalc="chosen-fpcalc", acoustid_key="SESSION-KEY", analysis_workers=3
    )
    close_window(qtbot, window)

    reopened = open_window(qtbot, library_path=path)
    assert reopened.model.rowCount() == 1
    assert reopened.model.identifications[file_id] == report
    assert reopened.folders.item(0).text() == str(music)
    assert reopened.search.text() == "日本語"
    assert reopened.settings.fpcalc == "chosen-fpcalc"
    assert reopened.settings.analysis_workers == 3
    assert reopened.settings.acoustid_key != "SESSION-KEY"
    assert calls == [file_id]  # Reopening/rescanning does not issue online requests.
    reopened.start_scan()
    qtbot.waitUntil(lambda: reopened.worker is None, timeout=10000)
    assert reopened.model.records[0].id == file_id
    assert reopened.model.identifications[file_id] == report
    assert calls == [file_id]
    assert audio.read_bytes() == original_bytes


def test_rescan_after_external_change_discards_proposal_keeps_uuid(qtbot, tmp_path, monkeypatch):
    from mutagen.id3 import TIT2
    from mutagen.mp3 import MP3

    music = tmp_path / "music"
    music.mkdir()
    path = music / "one.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", path)

    def identify(self, record, options, stage):
        return IdentificationReport(record.id, record.path, Decision(DecisionStatus.NO_MATCH))

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    window = open_window(qtbot)
    window.add_folder(music)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    file_id = window.model.records[0].id
    window.start_identification()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert file_id in window.model.identifications
    # Simulate a change made by another program, only on the test's private fixture.
    audio = MP3(path)
    audio.tags.add(TIT2(encoding=3, text="Título alterado externamente"))
    audio.save()
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert window.model.records[0].id == file_id
    assert not window.model.identifications
    assert window.model.records[0].tags.title == ("Título alterado externamente",)


def test_preferences_without_any_scan_and_explicit_config_precedence(qtbot, tmp_path):
    path = tmp_path / "library.sqlite3"
    window = open_window(qtbot, library_path=path)
    window.add_folder(tmp_path / "Músicas")
    window.recursive.setChecked(False)
    window.format_boxes["FLAC"].setChecked(False)
    window.settings = Settings(fpcalc="stored-fpcalc", audd_token="NEVER-SAVED")
    close_window(qtbot, window)
    reopened = open_window(
        qtbot,
        Settings(fpcalc="explicit-fpcalc"),
        library_path=path,
        restore_settings=False,
        folders=[tmp_path / "CLI override"],
    )
    assert reopened.settings.fpcalc == "explicit-fpcalc"
    assert reopened.settings.audd_token != "NEVER-SAVED"
    assert not reopened.recursive.isChecked()
    assert not reopened.format_boxes["FLAC"].isChecked()
    assert reopened.folders.count() == 1
    assert reopened.folders.item(0).text() == str(tmp_path / "CLI override")
    assert reopened.model.rowCount() == 0


def test_library_loading_stays_off_ui_thread_and_close_waits(qtbot, tmp_path, monkeypatch):
    from afinario.library import LibraryStore

    entered, release = threading.Event(), threading.Event()
    original = LibraryStore.load

    def slow_load(self):
        entered.set()
        assert release.wait(5)
        return original(self)

    monkeypatch.setattr(LibraryStore, "load", slow_load)
    window = MainWindow(library_path=tmp_path / "library.sqlite3")
    qtbot.addWidget(window, before_close_func=lambda widget: close_window(qtbot, widget))
    window.show()
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat), timeout=1000)
        assert window.close() is False
        assert window.isVisible()
    finally:
        release.set()
        qtbot.waitUntil(lambda: window.worker is None and not window.isVisible(), timeout=10000)


def test_corrupt_library_shows_error_and_never_creates_blank_replacement(qtbot, tmp_path):
    path = tmp_path / "library.sqlite3"
    original = b"damaged database - preserve for recovery"
    path.write_bytes(original)
    window = open_window(qtbot, library_path=path)
    assert "Não foi possível abrir" in window.status.text()
    assert "preservados" in window.issues.toPlainText()
    window.add_folder(tmp_path)
    assert not window.scan_button.isEnabled()
    close_window(qtbot, window)
    assert path.read_bytes() == original


def test_failed_recognition_persistence_is_visible_and_not_reported_as_success(
    qtbot,
    tmp_path,
    monkeypatch,
):
    from afinario.library import LibraryStore

    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")

    def identify(self, record, options, stage):
        return IdentificationReport(record.id, record.path, Decision(DecisionStatus.NO_MATCH))

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr("afinario.ui.recognition_worker.IdentificationService.identify", identify)
    window = open_window(qtbot)
    window.add_folder(tmp_path)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    monkeypatch.setattr(LibraryStore, "save_identification", fail)
    window.start_identification()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert "Falha" in window.status.text()
    assert "concluída" not in window.status.text()
    assert not window.model.identifications


def test_scan_issues_and_partial_cancelled_library_are_restored(qtbot, tmp_path, monkeypatch):
    import afinario.ui.worker as worker
    from afinario.inventory import ScanIssue, ScanSummary, read_track

    source = tmp_path / "one.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", source)
    path = tmp_path / "application" / "library.sqlite3"

    def partial_scan(roots, *, on_record, on_issue, **kwargs):
        on_record(read_track(source))
        on_issue(ScanIssue(str(tmp_path / "missing"), "Pasta indisponível"))
        return ScanSummary(audio_files=1, inaccessible_paths=1, cancelled=True)

    monkeypatch.setattr(worker, "scan", partial_scan)
    window = open_window(qtbot, library_path=path)
    window.add_folder(tmp_path)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    file_id = window.model.records[0].id
    close_window(qtbot, window)
    reopened = open_window(qtbot, library_path=path)
    assert reopened.model.records[0].id == file_id
    assert "incompleta" in reopened.status.text()
    assert "Pasta indisponível" in reopened.issues.toPlainText()
    assert reopened._summary.cancelled


def test_configuration_save_restores_credentials_without_database_secrets(qtbot, tmp_path):
    from afinario.credentials import CredentialStore
    from afinario.ui.recognition_settings import RecognitionSettingsDialog

    path = tmp_path / "library.sqlite3"
    window = open_window(qtbot, library_path=path)
    dialog = RecognitionSettingsDialog(
        window.settings,
        window,
        library_path=path,
        preferences=window._preferences(),
    )
    qtbot.addWidget(dialog)
    dialog.key.setText("TEST-PRIVATE-ACOUSTID")
    dialog.audd_token.setText("TEST-PRIVATE-AUDD")
    dialog.tools["fpcalc"].setText("saved-fpcalc")
    dialog.accept()
    qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
    assert dialog.result() == dialog.DialogCode.Accepted
    assert CredentialStore().load()["audd_token"] == "TEST-PRIVATE-AUDD"
    reopened = open_window(qtbot, library_path=path)
    assert reopened.settings.audd_token == "TEST-PRIVATE-AUDD"
    assert reopened.settings.acoustid_key == "TEST-PRIVATE-ACOUSTID"
    assert reopened.settings.fpcalc == "saved-fpcalc"
    close_window(qtbot, reopened)
    assert b"TEST-PRIVATE" not in path.read_bytes()


def test_configuration_failure_keeps_dialog_open_without_exposing_secret(qtbot, monkeypatch):
    from afinario.ui.recognition_settings import RecognitionSettingsDialog

    class Locked:
        def set_password(self, *args):
            raise OSError("TEST-SECRET")

    monkeypatch.setattr("afinario.credentials.system_backend", Locked)
    dialog = RecognitionSettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.audd_token.setText("TEST-SECRET")
    dialog.accept()
    qtbot.waitUntil(lambda: dialog.worker is None, timeout=10000)
    assert dialog.isVisible()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert "Não foi possível salvar" in dialog.save_status.text()
    assert "TEST-SECRET" not in dialog.save_status.text()


def test_per_field_approval_persists_and_edits_revoke_it(qtbot, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    source = music / "track.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", source)
    original = source.read_bytes()
    path = tmp_path / "application" / "library.sqlite3"
    window = open_window(qtbot, library_path=path)
    window.add_folder(music)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    window.table.selectRow(0)
    field = window.review_panel.proposed["title"]
    field.selectAll()
    qtbot.keyClicks(field, "Edited title")
    qtbot.waitUntil(lambda: window.worker is None and not window._pending_reviews, timeout=10000)
    window.review_panel.checks["title"].setChecked(True)
    window.review_panel.save_button.click()
    qtbot.waitUntil(lambda: window.worker is None and not window._pending_reviews, timeout=10000)
    file_id = window.model.records[0].id
    assert window.model.reviews[file_id].approved_fields == ("title",)
    assert not window.model.reviews[file_id].field("album").approved
    close_window(qtbot, window)
    reopened = open_window(qtbot, library_path=path)
    assert reopened.model.reviews[file_id].approved_fields == ("title",)
    reopened.table.selectRow(0)
    field = reopened.review_panel.proposed["artist"]
    field.selectAll()
    qtbot.keyClicks(field, "Another artist")
    assert not reopened.model.reviews[file_id].approved_fields
    close_window(qtbot, reopened)
    third = open_window(qtbot, library_path=path)
    assert not third.model.reviews[file_id].approved_fields
    assert source.read_bytes() == original


def test_lyrics_ui_queries_both_sources_and_requires_replacement_approval(
    qtbot,
    tmp_path,
    monkeypatch,
    transport_factory,
):
    import httpx

    from afinario.lyrics import LyricStatus

    music = tmp_path / "music"
    music.mkdir()
    shutil.copyfile(FIXTURES / "tone.mp3", music / "one.mp3")
    calls = []
    window = open_window(qtbot, library_path=tmp_path / "library.sqlite3")
    window.add_folder(music)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    record = window.model.records[0]

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "lrclib.net":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "trackName": record.tags.title[0],
                        "artistName": record.tags.artist[0],
                        "duration": record.duration,
                        "plainLyrics": "Letra remota sintética",
                    }
                ],
            )
        return httpx.Response(200, json={"lyrics": "Letra remota sintética"})

    monkeypatch.setattr(
        "afinario.ui.lyrics_worker.Transport",
        lambda *args, **kwargs: transport_factory(handler),
    )
    window.table.selectRow(0)
    window.start_lyrics()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert calls == ["lrclib.net", "api.lyrics.ovh"]
    assert window.model.lyrics[record.id].status == LyricStatus.FOUND
    draft = window.model.reviews[record.id]
    assert draft.field("lyrics").current
    assert draft.field("lyrics").proposed == draft.field("lyrics").current
    assert not draft.approved_fields
    panel = window.review_panel
    panel.lyric_candidates.setCurrentIndex(panel.lyric_candidates.count() - 1)
    assert not panel.checks["lyrics"].isEnabled()
    assert "Letra remota sintética" in panel.diff.toPlainText()
    panel.replace_lyrics.setChecked(True)
    qtbot.waitUntil(lambda: window.worker is None and not window._pending_reviews, timeout=10000)
    panel.checks["lyrics"].setChecked(True)
    panel.save_button.click()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    assert window.model.reviews[record.id].approved_fields == ("lyrics",)


def test_imported_lrc_can_be_approved_offline(qtbot, tmp_path, monkeypatch):
    music = tmp_path / "music"
    music.mkdir()
    shutil.copyfile(FIXTURES / "tone.mp3", music / "one.mp3")
    letter = tmp_path / "local.lrc"
    letter.write_text("[00:01.00]Texto local de teste", encoding="utf-8")
    window = open_window(qtbot)
    window.add_folder(music)
    window.start_scan()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    window.table.selectRow(0)

    def no_http(*args, **kwargs):
        pytest.fail("Importing a local lyric must not query providers")

    monkeypatch.setattr("afinario.transport.Transport.json", no_http)
    window.start_lyrics(import_path=str(letter))
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    panel = window.review_panel
    panel.lyric_candidates.setCurrentIndex(panel.lyric_candidates.count() - 1)
    panel.replace_lyrics.setChecked(True)
    qtbot.waitUntil(lambda: window.worker is None and not window._pending_reviews, timeout=10000)
    panel.checks["synced_lyrics"].setChecked(True)
    panel.save_button.click()
    qtbot.waitUntil(lambda: window.worker is None, timeout=10000)
    draft = window.model.reviews[window.model.records[0].id]
    assert draft.approved_fields == ("synced_lyrics",)
    assert draft.field("synced_lyrics").source.startswith("local:")
