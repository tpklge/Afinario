import sys
from pathlib import Path

from afinario.config import Settings
from afinario.runtime import bundled_tool, shazam_command


def test_source_build_preserves_native_tools_and_python_worker(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert bundled_tool("ffmpeg") == "ffmpeg"
    source = tmp_path / "música 日本語.wav"
    command = shazam_command(source)
    assert command[1:] == ["-m", "afinario.shazam_worker", str(source)]


def test_frozen_build_resolves_tools_without_path_and_uses_separate_worker(monkeypatch, tmp_path):
    internal = tmp_path / "instalação 日本語" / "_internal"
    tools = internal / "tools"
    tools.mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe", "fpcalc"):
        (tools / f"{name}.exe").write_bytes(b"tool fixture")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(internal.parent / "Afinario.exe"))
    monkeypatch.setenv("PATH", "")
    for settings in (Settings(), Settings.from_data({"tools": {"ffmpeg": "ffmpeg"}})):
        for name in ("ffmpeg", "ffprobe", "fpcalc"):
            assert Path(getattr(settings, name)) == tools / f"{name}.exe"
    source = tmp_path / "sample.wav"
    assert shazam_command(source) == [
        str(internal.parent / "AfinarioWorker.exe"),
        "--shazam-worker",
        str(source),
    ]
    custom = str(tmp_path / "custom-ffmpeg.exe")
    assert Settings.from_data({"tools": {"ffmpeg": custom}}).ffmpeg == custom


def test_frozen_missing_tool_keeps_diagnostic_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled_tool("fpcalc") == "fpcalc"
