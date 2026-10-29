"""Resource paths shared by source and frozen desktop builds."""

import sys
from pathlib import Path


def bundled_tool(name: str) -> str:
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)
        suffix = ".exe" if sys.platform == "win32" else ""
        candidate = root / "tools" / f"{name}{suffix}"
        if candidate.is_file():
            return str(candidate)
    return name


def shazam_command(path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        name = "AfinarioWorker.exe" if sys.platform == "win32" else "AfinarioWorker"
        worker = Path(sys.executable).with_name(name)
        return [str(worker), "--shazam-worker", str(path)]
    from afinario.cancellation import worker_interpreter

    return [worker_interpreter(), "-m", "afinario.shazam_worker", str(path)]
