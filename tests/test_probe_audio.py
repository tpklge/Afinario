import json
import subprocess
from types import SimpleNamespace

import pytest

from afinario.audio import extract_sample, fingerprint
from afinario.config import Settings
from afinario.domain import Status
from afinario.probe import recognition_probe, shazam_sample
from afinario.transport import ProviderError


def test_audio_commands_use_argv_and_preserve_original(tmp_path, monkeypatch):
    path = tmp_path / "música with spaces.mp3"
    path.write_bytes(b"original")
    calls = []
    monkeypatch.setattr("afinario.audio.executable", lambda value: value)

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "duration": 200,
                    "fingerprint": "FP",
                }
            ),
        )

    monkeypatch.setattr("afinario.audio.subprocess.run", execute)
    assert fingerprint(path, "fpcalc") == ("FP", 200)
    extract_sample(path, tmp_path / "sample.wav", 30, "ffmpeg")
    assert calls[0][0][-1] == str(path.resolve())
    assert calls[1][0][0] == "ffmpeg"
    assert "-n" in calls[1][0]
    assert all(not kwargs.get("shell", False) for _, kwargs in calls)
    assert path.read_bytes() == b"original"


def test_recognition_requires_credentials_and_upload_consent(transport_factory, tmp_path):
    def no_requests(_):
        pytest.fail("Unexpected network access")

    result = recognition_probe(
        transport_factory(no_requests), Settings(), tmp_path / "sample.mp3", False
    )
    assert [item.status for item in result] == [Status.BLOCKED, Status.BLOCKED]


def test_missing_tool_does_not_prevent_other_result(transport_factory, tmp_path, monkeypatch):
    def missing(*_):
        raise ProviderError(Status.BLOCKED, "Missing tool")

    monkeypatch.setattr("afinario.probe.fingerprint", missing)
    result = recognition_probe(
        transport_factory(lambda _: None),
        Settings(acoustid_key="secret"),
        tmp_path / "a.mp3",
        False,
    )
    assert len(result) == 2
    assert all(item.status == Status.BLOCKED for item in result)


def test_shazam_worker_timeout_is_not_not_found(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("shazam", 1)

    monkeypatch.setattr("afinario.probe.subprocess.run", timeout)
    assert shazam_sample(tmp_path / "sample.wav", 1).status == Status.NETWORK


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"status": "ok", "key": "123", "title": "T", "artist": "A"}, Status.OK),
        ({"status": "not_found"}, Status.NOT_FOUND),
        ({"status": "rate_limited"}, Status.RATE_LIMIT),
        ({"status": "ok"}, Status.INVALID),
    ],
)
def test_shazam_worker_result(monkeypatch, tmp_path, payload, status):
    monkeypatch.setattr(
        "afinario.probe.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
        ),
    )
    result = shazam_sample(tmp_path / "sample.wav", 1)
    assert result.status == status
