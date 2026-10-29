"""Segredos do usuário no cofre nativo, nunca em TOML, SQLite ou no repositório."""

import json
import sys
from dataclasses import replace

from afinario.config import Settings

SERVICE = "Afinario"
ACCOUNT = "provider-credentials-v1"
FIELDS = ("acoustid_key", "audd_token")


class CredentialError(RuntimeError):
    pass


def system_backend():
    # Explicitly select an OS backend. Never fall back to plaintext files or to
    # an arbitrary third-party backend configured for another Python program.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    if sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring

        return Keyring()
    raise CredentialError("Não há cofre de credenciais compatível neste sistema.")


class CredentialStore:
    def __init__(self, backend=None):
        self._backend = backend

    @property
    def backend(self):
        if self._backend is None:
            self._backend = system_backend()
        return self._backend

    def load(self) -> dict[str, str] | None:
        try:
            payload = self.backend.get_password(SERVICE, ACCOUNT)
            if payload is None:
                return None
            values = json.loads(payload)
            if (
                not isinstance(values, dict)
                or set(values) != set(FIELDS)
                or any(not isinstance(value, str) for value in values.values())
            ):
                raise ValueError("Invalid credential bundle")
            return values
        except Exception:
            raise CredentialError(
                "Não foi possível ler as credenciais salvas. Desbloqueie o cofre do sistema."
            ) from None

    def apply(self, settings: Settings) -> Settings:
        values = self.load()
        # An explicit saved empty field disables that credential, including an
        # older environment value. With no saved bundle, keep the env fallback.
        return (
            settings
            if values is None
            else replace(settings, **{name: values[name] or None for name in FIELDS})
        )

    def save(self, settings: Settings):
        values = {name: getattr(settings, name) or "" for name in FIELDS}
        if any(not isinstance(value, str) for value in values.values()):
            raise CredentialError("Credenciais inválidas.")
        try:
            # One credential entry makes replacement of the bundle atomic from
            # the application's perspective and avoids partially saved tokens.
            self.backend.set_password(SERVICE, ACCOUNT, json.dumps(values))
        except Exception:
            raise CredentialError(
                "Não foi possível salvar as credenciais. Desbloqueie o cofre e tente novamente."
            ) from None
