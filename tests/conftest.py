import httpx
import pytest

from afinario.config import Settings
from afinario.transport import Transport


@pytest.fixture
def transport_factory(monkeypatch):
    clients = []
    monkeypatch.setattr("afinario.transport.time.sleep", lambda _: None)

    def create(handler, attempts=1):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return Transport(Settings(attempts=attempts), client)

    yield create
    for client in clients:
        client.close()
