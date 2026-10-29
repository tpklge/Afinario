"""Configuração TOML sem segredos e caminhos nativos por plataforma."""

import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import PlatformDirs

from afinario.runtime import bundled_tool


def secret_from_environment(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    # Existing IDE processes may predate the user's persistent environment change.
    # This optional Windows adapter is never imported on Linux/macOS.
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
                value, _ = winreg.QueryValueEx(registry, name)
                return value if isinstance(value, str) and value else None
        except OSError:
            pass
    return None


def acoustid_key_from_environment() -> str | None:
    return secret_from_environment("AFINARIO_ACOUSTID_KEY")


@dataclass(frozen=True)
class Settings:
    timeout_seconds: float = 30
    attempts: int = 2
    user_agent: str = "Afinario/0.1.0 (https://github.com/tpklge/Afinario)"
    ffmpeg: str = field(default_factory=lambda: bundled_tool("ffmpeg"))
    ffprobe: str = field(default_factory=lambda: bundled_tool("ffprobe"))
    fpcalc: str = field(default_factory=lambda: bundled_tool("fpcalc"))
    acoustid_key: str | None = field(default=None, repr=False)
    analysis_workers: int = 2
    shazam_interval_seconds: float = 3
    audd_token: str | None = field(default=None, repr=False)
    audd_max_requests: int = 0

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        data = {} if path is None else tomllib.loads(path.read_text(encoding="utf-8"))
        return cls.from_data(data)

    def public_data(self) -> dict:
        """Allowlist for persistence: credentials never become configuration data."""
        return {
            "network": {
                "timeout_seconds": self.timeout_seconds,
                "attempts": self.attempts,
                "user_agent": self.user_agent,
                "shazam_interval_seconds": self.shazam_interval_seconds,
            },
            "tools": {
                name: name if getattr(self, name) == bundled_tool(name) else getattr(self, name)
                for name in ("ffmpeg", "ffprobe", "fpcalc")
            },
            "processing": {
                "analysis_workers": self.analysis_workers,
                "audd_max_requests": self.audd_max_requests,
            },
        }

    @classmethod
    def from_data(cls, data: dict) -> "Settings":
        if not isinstance(data, dict):
            raise ValueError("Configuração deve ser um objeto.")
        if set(data) - {"network", "tools", "processing"}:
            raise ValueError("Seção de configuração desconhecida.")
        network, tools = data.get("network", {}), data.get("tools", {})
        processing = data.get("processing", {})
        if not all(isinstance(section, dict) for section in (network, tools, processing)):
            raise ValueError("network e tools devem ser tabelas TOML.")
        if set(network) - {"timeout_seconds", "attempts", "user_agent", "shazam_interval_seconds"}:
            raise ValueError("Opção de rede desconhecida.")
        if set(tools) - {"ffmpeg", "ffprobe", "fpcalc"}:
            raise ValueError("Executável desconhecido.")
        if set(processing) - {"analysis_workers", "audd_max_requests"}:
            raise ValueError("Opção de processamento desconhecida.")
        workers = processing.get("analysis_workers", 2)
        paid_limit = processing.get("audd_max_requests", 0)
        if type(paid_limit) is not int or not 0 <= paid_limit <= 100000:
            raise ValueError("audd_max_requests deve estar entre 0 e 100000.")
        if type(workers) is not int or not 1 <= workers <= 4:
            raise ValueError("analysis_workers deve estar entre 1 e 4.")
        interval = network.get("shazam_interval_seconds", 3)
        if (
            type(interval) not in (int, float)
            or not math.isfinite(interval)
            or not 1 <= interval <= 300
        ):
            raise ValueError("shazam_interval_seconds deve estar entre 1 e 300.")
        timeout = network.get("timeout_seconds", 30)
        attempts = network.get("attempts", 2)
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 1 <= timeout <= 120
        ):
            raise ValueError("timeout_seconds deve estar entre 1 e 120.")
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise ValueError("attempts deve estar entre 1 e 3.")
        agent = network.get("user_agent", cls.user_agent)
        if not isinstance(agent, str) or not agent.strip() or not agent.isascii():
            raise ValueError("user_agent deve ser texto ASCII não vazio.")
        if any(ord(c) < 32 or ord(c) == 127 for c in agent):
            raise ValueError("user_agent não pode conter caracteres de controle.")
        for value in tools.values():
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ValueError("Caminho de executável inválido.")
        return cls(
            timeout_seconds=float(timeout),
            attempts=attempts,
            user_agent=agent,
            acoustid_key=acoustid_key_from_environment(),
            analysis_workers=workers,
            shazam_interval_seconds=float(interval),
            audd_token=secret_from_environment("AFINARIO_AUDD_TOKEN"),
            audd_max_requests=paid_limit,
            **{
                name: bundled_tool(name) if value == name else value
                for name, value in tools.items()
            },
        )


def app_paths() -> dict[str, str]:
    dirs = PlatformDirs("afinario", appauthor=False)
    return {
        "config": dirs.user_config_dir,
        "data": dirs.user_data_dir,
        "cache": dirs.user_cache_dir,
        "logs": dirs.user_log_dir,
    }
