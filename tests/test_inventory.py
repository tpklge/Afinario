import hashlib
import shutil
import threading
from pathlib import Path

import pytest

from afinario.inventory import read_track, scan

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "extension,expected",
    [
        ("mp3", "MP3"),
        ("m4a", "M4A"),
        ("flac", "FLAC"),
        ("ogg", "Vorbis"),
        ("opus", "Opus"),
        ("wav", "WAV"),
    ],
)
def test_real_container_and_tags_read_without_changes(tmp_path, extension, expected):
    source = FIXTURES / f"tone.{extension}"
    target = tmp_path / f"música.{extension}"
    shutil.copyfile(source, target)
    before = target.read_bytes()
    stat = target.stat()
    record = read_track(target)
    assert record.format == expected
    assert record.status == "ok"
    assert record.tags.title == ("Título sintético",)
    assert record.tags.artist == ("Artista de teste",)
    assert record.tags.album == ("Álbum de teste",)
    assert record.tags.has_lyrics
    assert record.duration > 0
    if extension != "opus":
        assert record.sample_rate > 0
    else:
        # Mutagen's OpusInfo does not expose a sample_rate attribute.
        assert record.sample_rate is None
    if extension in ("mp3", "m4a", "wav"):
        assert record.tags.cover_count == 1
    if extension == "m4a":
        assert record.tags.track == ("1/12",)
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == stat.st_mtime_ns


@pytest.mark.parametrize("extension", ["mp3", "m4a", "flac", "ogg", "opus", "wav"])
def test_detection_ignores_misleading_extension(tmp_path, extension):
    target = tmp_path / "arquivo.txt"
    shutil.copyfile(FIXTURES / f"tone.{extension}", target)
    record = read_track(target)
    assert record.format is not None
    assert record.status == "warning"
    assert "incompatível" in record.messages[0]


def test_recursive_overlap_and_bad_audio_are_isolated(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    shutil.copyfile(FIXTURES / "tone.flac", nested / "two.flac")
    (tmp_path / "broken.mp3").write_bytes(b"invalid")
    (tmp_path / "note.txt").write_text("not audio")
    records = []
    summary = scan([tmp_path, nested, tmp_path], on_record=records.append)
    assert summary.audio_files == 2
    assert summary.invalid_files == 1
    assert summary.ignored_files == 1
    assert len(records) == 3
    assert len({record.path for record in records}) == 3
    assert summary.duplicate_paths >= 2


def test_nonrecursive_still_accepts_nested_explicit_root(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    shutil.copyfile(FIXTURES / "tone.mp3", nested / "one.mp3")
    assert scan([tmp_path], recursive=False).audio_files == 0
    assert scan([tmp_path, nested], recursive=False).audio_files == 1


def test_filter_uses_real_format(tmp_path):
    shutil.copyfile(FIXTURES / "tone.flac", tmp_path / "wrong.mp3")
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "wrong.flac")
    records = []
    summary = scan([tmp_path], formats=frozenset({"MP3"}), on_record=records.append)
    assert summary.audio_files == 1
    assert records[0].path.endswith("wrong.flac")
    assert records[0].format == "MP3"


def test_missing_folder_does_not_stop_valid_root(tmp_path):
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    issues = []
    summary = scan([tmp_path / "missing", tmp_path], on_issue=issues.append)
    assert summary.audio_files == 1
    assert summary.inaccessible_paths == 1
    assert len(issues) == 1


def test_corrupt_file_outside_selected_formats_is_ignored(tmp_path):
    (tmp_path / "broken.flac").write_bytes(b"invalid")
    summary = scan([tmp_path], formats=frozenset({"MP3"}))
    assert summary.invalid_files == 0
    assert summary.ignored_files == 1


def test_symlinks_and_cycles_are_skipped(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    shutil.copyfile(FIXTURES / "tone.mp3", real / "one.mp3")
    try:
        (real / "cycle").symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "alias.mp3").symlink_to(real / "one.mp3")
    except OSError:
        pytest.skip("O sistema não permite criar links nesta conta.")
    summary = scan([tmp_path])
    assert summary.audio_files == 1
    assert summary.skipped_links == 2


def test_cancel_returns_partial_results(tmp_path):
    for index in range(8):
        shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / f"{index}.mp3")
    stop = threading.Event()
    records = []

    def receive(record):
        records.append(record)
        stop.set()

    summary = scan([tmp_path], cancelled=stop, on_record=receive)
    assert summary.cancelled
    assert summary.audio_files == 1
    assert len(records) == 1


def test_unreadable_file_does_not_abort(tmp_path, monkeypatch):
    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    monkeypatch.setattr(
        "afinario.inventory.read_track",
        lambda _: (_ for _ in ()).throw(PermissionError("private details")),
    )
    records = []
    summary = scan([tmp_path], on_record=records.append)
    assert summary.invalid_files == 1
    assert records[0].status == "error"
    assert "private" not in str(records[0].messages)


def test_changed_file_is_rejected(tmp_path, monkeypatch):
    import afinario.inventory as inventory

    target = tmp_path / "one.mp3"
    shutil.copyfile(FIXTURES / "tone.mp3", target)
    original = inventory._tags

    def change(audio):
        result = original(audio)
        # External writer, simulated only on a generated fixture.
        with target.open("ab") as stream:
            stream.write(b"external change")
        return result

    monkeypatch.setattr(inventory, "_tags", change)
    with pytest.raises(OSError, match="alterado"):
        read_track(target)


def test_entire_fixture_tree_is_unchanged():
    paths = list(FIXTURES.glob("tone.*"))
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    scan([FIXTURES])
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_cli_inventory_is_offline_and_reports_errors(tmp_path, capsys):
    import json

    from afinario.cli import main

    shutil.copyfile(FIXTURES / "tone.mp3", tmp_path / "one.mp3")
    (tmp_path / "broken.flac").write_bytes(b"not flac")
    assert main(["scan", str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["network_used"] is False
    assert report["summary"]["audio_files"] == 1
    assert report["summary"]["invalid_files"] == 1
    assert len(report["records"]) == 2
