import json
import logging
import shutil
import sqlite3
from pathlib import Path

import pytest

from afinario.cli import main
from afinario.config import Settings, app_paths
from afinario.logging_config import RedactSecrets


@pytest.mark.parametrize(
    "body",
    [
        "[network]\nattempts = 0",
        "[network]\ntimeout_seconds = nan",
        "[network]\ntimeout_seconds = true",
        "[network]\nattempts = true",
        "[tools]\nffmpeg = 42",
        "[network]\nsecret = 'key'",
        "[unknown]\na = 1",
        "network = 'wrong'",
        "[network]\nuser_agent = 'bad\nheader'",
        "[processing]\nanalysis_workers = 0",
        "[processing]\nanalysis_workers = 5",
        "[processing]\naudd_max_requests = -1",
        "[processing]\naudd_max_requests = true",
        "[network]\nshazam_interval_seconds = nan",
    ],
)
def test_bad_config_is_rejected(tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)


def test_config_reads_environment_not_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AFINARIO_ACOUSTID_KEY", "SECRET")
    path = tmp_path / "config.toml"
    path.write_text('[network]\nattempts = 1\n[tools]\nffmpeg = "custom"', encoding="utf-8")
    settings = Settings.load(path)
    assert settings.acoustid_key == "SECRET"
    assert settings.ffmpeg == "custom"
    assert "SECRET" not in repr(settings)
    assert app_paths()["data"]


@pytest.mark.parametrize(
    "args",
    [
        ["probe", "--artist", "A", "--title", "B"],
        ["probe", "--online"],
        ["probe", "--online", "--artist", "A"],
        ["probe", "--online", "--artist", " ", "--title", "B"],
        ["probe", "--online", "--audio", "does-not-exist.mp3"],
        ["probe", "--online", "--artist", "A", "--title", "B", "--allow-audio-upload"],
    ],
)
def test_cli_rejects_invalid_or_unauthorized_probe(args):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_doctor_offline_and_report_does_not_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("afinario.cli.doctor", lambda _: {"network_used": False})
    target = tmp_path / "existing.mp3"
    target.write_bytes(b"original music bytes")
    assert main(["doctor", "--report", str(target)]) == 2
    assert target.read_bytes() == b"original music bytes"
    fresh = tmp_path / "doctor.json"
    assert main(["doctor", "--report", str(fresh)]) == 0
    assert json.loads(fresh.read_text())["environment"]["network_used"] is False
    assert "network_used" in capsys.readouterr().out


def test_logs_redact_secret_and_sensitive_parameters():
    record = logging.LogRecord(
        "afinario", logging.INFO, "", 0, "failed SECRET token=abc client=def", (), None
    )
    assert RedactSecrets(("SECRET",)).filter(record)
    assert "SECRET" not in record.getMessage()
    assert "abc" not in record.getMessage()
    assert "def" not in record.getMessage()


def test_audd_token_and_concurrency_config_are_loaded_without_repr_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("AFINARIO_AUDD_TOKEN", "AUDD-TOKEN-SECRET")
    path = tmp_path / "config.toml"
    path.write_text(
        "[processing]\nanalysis_workers = 3\naudd_max_requests = 10\n"
        "[network]\nshazam_interval_seconds = 5",
        encoding="utf-8",
    )
    settings = Settings.load(path)
    assert settings.audd_token == "AUDD-TOKEN-SECRET"
    assert settings.analysis_workers == 3
    assert settings.audd_max_requests == 10
    assert settings.shazam_interval_seconds == 5
    assert "AUDD-TOKEN-SECRET" not in repr(settings)


def test_cli_scan_persists_records_and_reuses_ids(tmp_path, capsys):
    from afinario.library import LibraryStore

    shutil.copyfile(Path(__file__).parent / "fixtures" / "tone.mp3", tmp_path / "one.mp3")
    assert main(["scan", str(tmp_path)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["scan", str(tmp_path)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["records"][0]["id"] == second["records"][0]["id"]
    with LibraryStore() as db:
        assert db.load().records[0].id == first["records"][0]["id"]


def test_cli_reports_persistence_failure_without_traceback_or_mutating_audio(
    tmp_path,
    monkeypatch,
    capsys,
):
    from afinario.library import LibraryStore

    audio = tmp_path / "one.mp3"
    shutil.copyfile(Path(__file__).parent / "fixtures" / "tone.mp3", audio)
    original = audio.read_bytes()

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("PRIVATE diagnostic")

    monkeypatch.setattr(LibraryStore, "save_scan_records", fail)
    assert main(["scan", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "Falha ao salvar" in captured.err
    assert "PRIVATE" not in captured.err
    assert audio.read_bytes() == original


def test_doctor_uses_saved_credentials_without_exporting_values(monkeypatch, capsys):
    from afinario.credentials import CredentialStore

    CredentialStore().save(Settings(acoustid_key="TEST-KEY", audd_token="TEST-TOKEN"))
    monkeypatch.setattr(
        "afinario.cli.doctor",
        lambda settings: {
            "acoustid_key_configured": bool(settings.acoustid_key),
            "audd_token_configured": bool(settings.audd_token),
        },
    )
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["environment"]["audd_token_configured"]
    assert "TEST-KEY" not in output and "TEST-TOKEN" not in output


def test_cli_scan_preserves_previously_saved_service_settings(tmp_path, capsys):
    from afinario.library import LibraryPreferences, LibraryStore

    with LibraryStore() as library:
        library.save_preferences(
            LibraryPreferences(settings=Settings(fpcalc="saved-tool").public_data())
        )
    shutil.copyfile(Path(__file__).parent / "fixtures/tone.mp3", tmp_path / "one.mp3")
    assert main(["scan", str(tmp_path)]) == 0
    capsys.readouterr()
    with LibraryStore() as library:
        assert library.load().preferences.settings["tools"]["fpcalc"] == "saved-tool"
