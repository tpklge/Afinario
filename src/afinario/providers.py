"""Adaptadores de prova, separados dos contratos e da CLI."""

import math
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from afinario.domain import LyricCandidate, ProviderResult, RecordingCandidate, Status
from afinario.transport import ProviderError, Transport


def text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def number(value: Any) -> float | None:
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def lyric_text(value: Any) -> str | None:
    result = text(value)
    if result and any(
        marker in result.casefold() for marker in ("<html", "<!doctype", "<script", "captcha")
    ):
        raise ValueError("Conteúdo inesperado no campo de letra.")
    return result


def run_provider(provider: str, action: Callable[[], tuple[tuple, int]]) -> ProviderResult:
    start = time.monotonic()
    try:
        candidates, attempts = action()
        return ProviderResult(
            provider,
            Status.OK if candidates else Status.NOT_FOUND,
            "Candidatos recebidos; correspondência ainda não validada."
            if candidates
            else "Nenhum resultado encontrado.",
            candidates,
            attempts,
            time.monotonic() - start,
        )
    except ProviderError as exc:
        return ProviderResult(
            provider,
            exc.status,
            str(exc),
            attempts=exc.attempts,
            elapsed_seconds=time.monotonic() - start,
            retry_after_seconds=exc.retry_after_seconds,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return ProviderResult(
            provider,
            Status.INVALID,
            "Estrutura de resposta inválida.",
            elapsed_seconds=time.monotonic() - start,
        )


class LRCLib:
    name = "lrclib"

    def __init__(self, transport: Transport):
        self.transport = transport

    def search(self, artist: str, title: str) -> ProviderResult:
        def action() -> tuple[tuple, int]:
            data, attempts = self.transport.json(
                self.name,
                "GET",
                "https://lrclib.net/api/search",
                params={"artist_name": artist, "track_name": title},
            )
            if not isinstance(data, list):
                raise ValueError("Expected list")
            candidates = []
            for row in data:
                if not isinstance(row, dict) or type(row.get("id")) is not int:
                    raise ValueError("Invalid candidate")
                plain, synced = (
                    lyric_text(row.get("plainLyrics")),
                    lyric_text(row.get("syncedLyrics")),
                )
                instrumental = row.get("instrumental")
                if instrumental is not None and type(instrumental) is not bool:
                    raise ValueError("Invalid instrumental flag")
                if plain or synced or instrumental is True:
                    candidates.append(
                        LyricCandidate(
                            self.name,
                            str(row["id"]),
                            plain,
                            synced,
                            instrumental,
                            text(row.get("trackName")),
                            text(row.get("artistName")),
                            number(row.get("duration")),
                        )
                    )
            return tuple(candidates), attempts

        return run_provider(self.name, action)


class LyricsOVH:
    name = "lyrics.ovh"

    def __init__(self, transport: Transport):
        self.transport = transport

    def search(self, artist: str, title: str) -> ProviderResult:
        def action() -> tuple[tuple, int]:
            url = f"https://api.lyrics.ovh/v1/{quote(artist, safe='')}/{quote(title, safe='')}"
            data, attempts = self.transport.json(self.name, "GET", url)
            if not isinstance(data, dict) or "lyrics" not in data:
                raise ValueError("Missing lyrics")
            plain = lyric_text(data["lyrics"])
            # The API does not return artist/title/duration evidence.
            candidates = (LyricCandidate(self.name, None, plain),) if plain else ()
            return candidates, attempts

        return run_provider(self.name, action)


class AcoustID:
    name = "acoustid"

    def __init__(self, transport: Transport, key: str):
        self.transport, self.key = transport, key

    def lookup(self, fingerprint: str, duration: float) -> ProviderResult:
        def action() -> tuple[tuple, int]:
            data, attempts = self.transport.json(
                self.name,
                "POST",
                "https://api.acoustid.org/v2/lookup",
                application_error_statuses=(400,),
                data={
                    "client": self.key,
                    "duration": str(round(duration)),
                    "fingerprint": fingerprint,
                    "meta": "recordings",
                    "format": "json",
                },
            )
            if not isinstance(data, dict):
                raise ValueError("Expected object")
            if data.get("status") == "error":
                code = data.get("error", {}).get("code")
                status = Status.AUTH if code in (4, 5) else Status.INVALID
                if code == 13:
                    status = Status.RATE_LIMIT
                self.transport.record_failure(self.name, status)
                message = (
                    "AcoustID recusou a chave de aplicação (client). "
                    "Confira a chave em Serviços e ferramentas."
                    if status == Status.AUTH
                    else "AcoustID recusou a consulta."
                )
                raise ProviderError(status, message, attempts)
            if data.get("status") != "ok" or not isinstance(data.get("results"), list):
                raise ValueError("Invalid response")
            candidates = []
            for match in data["results"]:
                external_id = text(match.get("id"))
                if not external_id:
                    raise ValueError("Missing match ID")
                recordings = match.get("recordings", [])
                if not isinstance(recordings, list):
                    raise ValueError("Invalid recordings")
                if not recordings:
                    candidates.append(
                        RecordingCandidate(
                            self.name,
                            external_id,
                            score=number(match.get("score")),
                        )
                    )
                for recording in recordings:
                    artists = recording.get("artists", [])
                    artist = (
                        " / ".join(name for item in artists if (name := text(item.get("name"))))
                        or None
                    )
                    candidates.append(
                        RecordingCandidate(
                            self.name,
                            external_id,
                            text(recording.get("title")),
                            artist,
                            number(recording.get("duration")),
                            number(match.get("score")),
                            text(recording.get("id")),
                        )
                    )
            return tuple(candidates), attempts

        return run_provider(self.name, action)
