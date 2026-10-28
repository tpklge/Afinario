import asyncio
import json
import sys
from abc import ABC
from types import ModuleType

import pytest

from afinario.domain import Status
from afinario.shazam_worker import main, recognize
from afinario.transport import ProviderError


@pytest.fixture
def fake_shazam(monkeypatch):
    package = ModuleType("shazamio")
    interface = ModuleType("shazamio.interfaces.client")
    interface.HTTPClientInterface = ABC
    package.Shazam = None
    monkeypatch.setitem(sys.modules, "shazamio", package)
    monkeypatch.setitem(sys.modules, "shazamio.interfaces.client", interface)
    return package


def test_shazam_uses_bounded_transport_and_closes_it(monkeypatch, fake_shazam):
    calls = []
    closed = []

    class FakeTransport:
        def __init__(self, settings):
            assert settings.attempts == 1

        def json(self, provider, method, url, **kwargs):
            calls.append((provider, method, kwargs))
            assert "proxy" not in kwargs
            return {"matches": []}, 1

        def close(self):
            closed.append(True)

    class FakeShazam:
        def __init__(self, http_client):
            self.http = http_client

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def recognize(self, path):
            return await self.http.request("POST", "https://example.test", proxy=None, json={})

    fake_shazam.Shazam = FakeShazam
    monkeypatch.setattr("afinario.shazam_worker.Transport", FakeTransport)
    assert asyncio.run(recognize("synthetic.wav")) == {"matches": []}
    assert len(calls) == 1
    assert closed == [True]


@pytest.mark.parametrize("status", [Status.RATE_LIMIT, Status.AUTH, Status.NETWORK])
def test_worker_preserves_errors_without_exposing_message(monkeypatch, capsys, status):
    async def fail(_):
        raise ProviderError(status, "SECRET upstream message")

    monkeypatch.setattr("afinario.shazam_worker.recognize", fail)
    monkeypatch.setattr(sys, "argv", ["worker", "synthetic.wav"])
    assert main() == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == status.value
    assert "SECRET" not in output


def test_worker_preserves_isrc_when_provided(monkeypatch, capsys):
    async def success(_):
        return {
            "matches": [{}],
            "track": {"key": "id", "title": "Title", "subtitle": "Artist", "isrc": "code"},
        }

    monkeypatch.setattr("afinario.shazam_worker.recognize", success)
    monkeypatch.setattr(sys, "argv", ["worker", "synthetic.wav"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok"
    assert result["isrcs"] == ["CODE"]
