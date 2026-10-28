import importlib.util
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from afinario.audio import audio_duration, extract_sample, fingerprint
from afinario.cancellation import hidden_process_options, run_cancellable, worker_interpreter
from afinario.config import Settings
from afinario.domain import ProviderResult, RecordingCandidate, Status
from afinario.providers import AcoustID, LRCLib, LyricsOVH, text
from afinario.transport import ProviderError, Transport


def lyrics_probe(transport: Transport, artist: str, title: str) -> list[ProviderResult]:
    return [LRCLib(transport).search(artist, title), LyricsOVH(transport).search(artist, title)]


def shazam_sample(
    path: Path, timeout: float, cancelled: threading.Event | None = None
) -> ProviderResult:
    start = time.monotonic()
    try:
        if cancelled is None:
            process = subprocess.run(
                [worker_interpreter(), "-m", "afinario.shazam_worker", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                check=False,
                **hidden_process_options(),
            )
        else:
            process = run_cancellable(
                [worker_interpreter(), "-m", "afinario.shazam_worker", str(path)],
                timeout=timeout,
                cancelled=cancelled,
            )
        if process.returncode:
            raise ValueError("Worker failed")
        data = json.loads(process.stdout)
        status = Status(data["status"])
        candidates = ()
        if status == Status.OK:
            if not text(data.get("key")):
                raise ValueError("Missing identifier")
            candidates = (
                RecordingCandidate(
                    "shazamio",
                    data["key"],
                    text(data.get("title")),
                    text(data.get("artist")),
                    isrcs=tuple(
                        value.strip().upper()
                        for value in data.get("isrcs", [])
                        if isinstance(value, str) and value.strip()
                    ),
                ),
            )
        return ProviderResult(
            "shazamio",
            status,
            "Resultado experimental do ShazamIO.",
            candidates,
            1,
            time.monotonic() - start,
            retry_after_seconds=float(data.get("retry_after_seconds", 0)),
        )
    except subprocess.TimeoutExpired:
        return ProviderResult(
            "shazamio",
            Status.NETWORK,
            "Timeout do reconhecedor experimental.",
            attempts=1,
            elapsed_seconds=time.monotonic() - start,
        )
    except (ValueError, KeyError, TypeError, OSError):
        return ProviderResult(
            "shazamio",
            Status.INVALID,
            "Falha do reconhecedor experimental.",
            attempts=1,
            elapsed_seconds=time.monotonic() - start,
        )


def recognition_probe(
    transport: Transport,
    settings: Settings,
    path: Path,
    allow_audio_upload: bool,
) -> list[ProviderResult]:
    results = []
    if not settings.acoustid_key:
        results.append(
            ProviderResult(
                "acoustid", Status.BLOCKED, "Defina AFINARIO_ACOUSTID_KEY para consultar."
            )
        )
    else:
        try:
            value, duration = fingerprint(path, settings.fpcalc)
            results.append(AcoustID(transport, settings.acoustid_key).lookup(value, duration))
        except ProviderError as exc:
            results.append(ProviderResult("acoustid", exc.status, str(exc)))
        except (ValueError, TypeError, KeyError):
            results.append(ProviderResult("acoustid", Status.AUDIO, "Fingerprint local inválido."))
    if not allow_audio_upload:
        results.append(
            ProviderResult(
                "shazamio", Status.BLOCKED, "Envio de amostra exige --allow-audio-upload."
            )
        )
    elif importlib.util.find_spec("shazamio") is None:
        results.append(
            ProviderResult(
                "shazamio", Status.BLOCKED, "Instale o extra recognition para usar ShazamIO."
            )
        )
    else:
        try:
            duration = audio_duration(path, settings.ffprobe)
            # Two distinct useful windows, bounded by the actual file duration.
            offsets = list(
                dict.fromkeys([min(30, max(0, duration - 12)), max(0, duration / 2 - 6)])
            )
            start = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="afinario-probe-") as temporary:
                for index, offset in enumerate(offsets):
                    if index:
                        time.sleep(1)
                    sample = Path(temporary) / f"sample-{index}.wav"
                    extract_sample(path, sample, offset, settings.ffmpeg)
                    result = shazam_sample(sample, settings.timeout_seconds)
                    result = ProviderResult(
                        result.provider,
                        result.status,
                        result.message,
                        result.candidates,
                        index + 1,
                        time.monotonic() - start,
                    )
                    if result.status != Status.NOT_FOUND:
                        break
                results.append(result)
        except ProviderError as exc:
            results.append(ProviderResult("shazamio", exc.status, str(exc)))
        except (ValueError, TypeError, KeyError, OSError):
            results.append(ProviderResult("shazamio", Status.AUDIO, "Amostra local inválida."))
    return results
