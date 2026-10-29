import json
import subprocess
from types import SimpleNamespace

import pytest

import afinario.credentials as credentials
from afinario.config import Settings
from afinario.credentials import ACCOUNT, SERVICE, CredentialError, CredentialStore
from afinario.credentials import system_backend as select_native_backend


def test_bundle_persists_and_saved_values_override_older_environment():
    store = CredentialStore()
    store.save(Settings(acoustid_key="TEST-ACOUSTID", audd_token="TEST-AUDD"))
    restored = CredentialStore().apply(Settings(acoustid_key="OLD-ENV"))
    assert restored.acoustid_key == "TEST-ACOUSTID"
    assert restored.audd_token == "TEST-AUDD"
    assert "TEST-AUDD" not in repr(restored)
    assert "TEST-ACOUSTID" not in json.dumps(restored.public_data())


def test_empty_saved_field_removes_token_and_disables_old_environment():
    store = CredentialStore()
    store.save(Settings(acoustid_key="old", audd_token="old"))
    store.save(Settings())
    assert (
        CredentialStore().apply(Settings(acoustid_key="env", audd_token="env")).audd_token is None
    )
    assert CredentialStore().load() == {"acoustid_key": "", "audd_token": ""}


def test_absent_vault_bundle_keeps_environment_fallback():
    assert CredentialStore().apply(Settings(acoustid_key="ENV")).acoustid_key == "ENV"


@pytest.mark.parametrize("method", ["load", "save"])
def test_locked_vault_does_not_leak_tokens_or_fall_back_to_plaintext(tmp_path, method):
    class BrokenVault:
        def get_password(self, *args):
            raise OSError("PRIVATE-TOKEN")

        def set_password(self, *args):
            raise OSError("PRIVATE-TOKEN")

    store = CredentialStore(BrokenVault())
    with pytest.raises(CredentialError) as exc:
        store.load() if method == "load" else store.save(Settings(audd_token="PRIVATE-TOKEN"))
    assert "PRIVATE-TOKEN" not in str(exc.value)
    assert list(tmp_path.iterdir()) == []


def test_bundle_is_written_once_not_as_partial_credentials():
    calls = []
    backend = SimpleNamespace(set_password=lambda *args: calls.append(args))
    CredentialStore(backend).save(Settings(acoustid_key="A", audd_token="B"))
    assert len(calls) == 1
    assert calls[0][:2] == (SERVICE, ACCOUNT)
    assert json.loads(calls[0][2]) == {"acoustid_key": "A", "audd_token": "B"}


@pytest.mark.parametrize("payload", ["not-json", '{"audd_token":42}', "[]"])
def test_invalid_bundle_is_not_silently_replaced(payload):
    backend = SimpleNamespace(get_password=lambda *args: payload)
    with pytest.raises(CredentialError):
        CredentialStore(backend).load()


def test_git_ignores_local_secrets_and_database_files():
    paths = [
        ".env",
        ".env.local",
        "credentials.local.json",
        "library.sqlite3",
        "library.sqlite3-wal",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        input=("\0".join(paths) + "\0").encode("utf-8"),
        capture_output=True,
        check=True,
    )
    assert result.stdout.decode("utf-8").split("\0")[:-1] == paths


def test_explicit_native_backend_selection_without_using_insecure_plugins(monkeypatch):
    # Exercise the real selector, not conftest's isolated test vault.
    for platform, module_name, class_name in (
        ("darwin", "keyring.backends.macOS", "Keyring"),
        ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
        ("linux", "keyring.backends.SecretService", "Keyring"),
    ):
        marker = object()
        monkeypatch.setattr(credentials.sys, "platform", platform)
        monkeypatch.setitem(
            credentials.sys.modules,
            module_name,
            SimpleNamespace(
                **{
                    class_name: lambda value=marker: value,
                }
            ),
        )
        assert select_native_backend() is marker
