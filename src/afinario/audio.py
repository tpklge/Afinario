"""Ferramentas locais somente leitura; saída de diagnóstico nunca contém stderr bruto."""

import json
import math
import shutil
import subprocess
import threading
from pathlib import Path

from afinario.cancellation import hidden_process_options, run_cancellable
from afinario.domain import Status
from afinario.transport import ProviderError


def executable(command: str) -> str:
    resolved = shutil.which(command)
    if resolved is None:
        raise ProviderError(
            Status.BLOCKED, f"Executável auxiliar não encontrado no PATH: {Path(command).name}."
        )
    return resolved


def run_tool(
    command: str, args: list[str], timeout: float = 60, cancelled: threading.Event | None = None
) -> str:
    try:
        if cancelled is None:
            result = subprocess.run(
                [executable(command), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                **hidden_process_options(),
            )
        else:
            result = run_cancellable(
                [executable(command), *args], timeout=timeout, cancelled=cancelled
            )
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderError(Status.AUDIO, "Falha ou timeout no processamento local.") from None
    if result.returncode:
        raise ProviderError(Status.AUDIO, "Executável não conseguiu processar o áudio.")
    return result.stdout


def audio_duration(path: Path, ffprobe: str, *, cancelled: threading.Event | None = None) -> float:
    data = json.loads(
        run_tool(
            ffprobe,
            [
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path.resolve()),
            ],
            cancelled=cancelled,
        )
    )
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Duração inválida")
    return duration


def fingerprint(
    path: Path, fpcalc: str, *, cancelled: threading.Event | None = None
) -> tuple[str, float]:
    data = json.loads(run_tool(fpcalc, ["-json", str(path.resolve())], cancelled=cancelled))
    duration, value = float(data["duration"]), data["fingerprint"]
    if not isinstance(value, str) or not value or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Fingerprint inválido")
    return value, duration


def extract_sample(
    path: Path,
    target: Path,
    offset: float,
    ffmpeg: str,
    *,
    cancelled: threading.Event | None = None,
) -> None:
    run_tool(
        ffmpeg,
        [
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-ss",
            str(offset),
            "-i",
            str(path.resolve()),
            "-t",
            "12",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        cancelled=cancelled,
    )
