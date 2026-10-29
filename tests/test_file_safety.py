from pathlib import Path
from types import SimpleNamespace

import pytest

import afinario.file_safety as safety


def test_windows_move_requests_durability_without_replacement(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.mp3", tmp_path / "destination.mp3"
    source.write_bytes(b"original")
    destination.write_bytes(b"foreign")
    calls = []

    class NativeMove:
        def __call__(self, src, dst, flags):
            calls.append(flags)
            if Path(dst).exists() and not flags & 1:
                return 0
            Path(src).replace(dst)
            return 1

    kernel = SimpleNamespace(MoveFileExW=NativeMove())
    monkeypatch.setattr(safety, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(safety.ctypes, "WinDLL", lambda *a, **k: kernel, raising=False)
    monkeypatch.setattr(
        safety.ctypes, "WinError", lambda code: FileExistsError(code, "exists"), raising=False
    )
    monkeypatch.setattr(safety.ctypes, "get_last_error", lambda: 183, raising=False)
    with pytest.raises(FileExistsError):
        safety.move_exclusive(source, destination)
    assert source.read_bytes() == b"original"
    assert destination.read_bytes() == b"foreign"
    destination.unlink()
    safety.move_exclusive(source, destination)
    assert destination.read_bytes() == b"original"
    assert not source.exists()
    assert all(flags & 8 and not flags & 1 for flags in calls)
