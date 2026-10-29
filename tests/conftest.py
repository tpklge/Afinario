from types import SimpleNamespace

import httpx
import pytest

from afinario.config import Settings
from afinario.transport import Transport


@pytest.fixture(autouse=True)
def isolated_application_data(tmp_path_factory, monkeypatch):
    """Tests must never read or write the real user's library/cache on any OS."""
    root = tmp_path_factory.mktemp("application")
    vault = {}

    class TestVault:
        def get_password(self, service, account):
            return vault.get((service, account))

        def set_password(self, service, account, value):
            vault[service, account] = value

    monkeypatch.setattr("afinario.credentials.system_backend", TestVault)
    monkeypatch.setattr(
        "afinario.config.PlatformDirs",
        lambda *args, **kwargs: SimpleNamespace(
            user_config_dir=str(root / "config"),
            user_data_dir=str(root / "data"),
            user_cache_dir=str(root / "cache"),
            user_log_dir=str(root / "logs"),
        ),
    )


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
