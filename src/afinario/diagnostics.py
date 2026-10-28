import importlib.metadata
import platform
import shutil
import subprocess

from afinario.config import Settings, app_paths


def doctor(settings: Settings) -> dict:
    tools = {}
    for name in ("ffmpeg", "ffprobe", "fpcalc"):
        command = shutil.which(getattr(settings, name))
        version = None
        if command:
            try:
                result = subprocess.run(
                    [command, "-version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    version = (result.stdout or result.stderr).splitlines()[0][:200]
            except (OSError, subprocess.TimeoutExpired, IndexError):
                pass
        tools[name] = {"available": bool(version), "version": version}
    packages = {}
    for name in ("httpx", "platformdirs", "mutagen", "PySide6-Essentials", "shazamio"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "system": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "paths": app_paths(),
        "packages": packages,
        "tools": tools,
        "acoustid_key_configured": bool(settings.acoustid_key),
        "audd_token_configured": bool(settings.audd_token),
        "network_used": False,
    }
