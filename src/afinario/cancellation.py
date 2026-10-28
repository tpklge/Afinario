import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def hidden_process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def worker_interpreter() -> str:
    executable = Path(sys.executable)
    console = executable.with_name("python.exe")
    if executable.name.lower() == "pythonw.exe" and console.is_file():
        return str(console)
    return sys.executable


class AnalysisCancelled(Exception):
    """Interrupção solicitada, distinta de erro de provedor ou ausência de resultado."""


def check_cancelled(event: threading.Event | None) -> None:
    if event is not None and event.is_set():
        raise AnalysisCancelled


def run_cancellable(
    argv: list[str],
    *,
    timeout: float,
    cancelled: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    if cancelled is None:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            **hidden_process_options(),
        )
    check_cancelled(cancelled)
    start = time.monotonic()
    with subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_process_options(),
    ) as process:
        try:
            while True:
                check_cancelled(cancelled)
                if time.monotonic() - start >= timeout:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
