"""Contratos normalizados. Nenhuma escrita em arquivos musicais nesta etapa."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    AUTH = "authentication_error"
    RATE_LIMIT = "rate_limited"
    UNAVAILABLE = "unavailable"
    NETWORK = "network_error"
    INVALID = "invalid_response"
    BLOCKED = "blocked"
    AUDIO = "audio_error"


@dataclass(frozen=True)
class RecordingCandidate:
    provider: str
    external_id: str | None
    title: str | None = None
    artist: str | None = None
    duration: float | None = None
    score: float | None = None
    recording_id: str | None = None
    title_aliases: tuple[str, ...] = ()
    artist_aliases: tuple[str, ...] = ()
    isrcs: tuple[str, ...] = ()
    version: str | None = None


@dataclass(frozen=True)
class ReleaseCandidate:
    external_id: str | None
    title: str
    date: str | None = None
    country: str | None = None


@dataclass(frozen=True)
class LyricCandidate:
    provider: str
    external_id: str | None
    plain_text: str | None = field(default=None, repr=False)
    synced_text: str | None = field(default=None, repr=False)
    instrumental: bool | None = None
    title: str | None = None
    artist: str | None = None
    duration: float | None = None
    source: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: Status
    message: str
    candidates: tuple[RecordingCandidate | LyricCandidate, ...] = ()
    attempts: int = 0
    elapsed_seconds: float = 0
    releases: tuple[ReleaseCandidate, ...] = ()
    cached: bool = False
    retry_after_seconds: float = 0

    def summary(self) -> dict[str, Any]:
        """Relatórios não incluem letras completas, áudio, fingerprint ou credenciais."""
        candidates: list[dict[str, Any]] = []
        for candidate in self.candidates:
            item: dict[str, Any] = {
                "external_id": candidate.external_id,
                "title": candidate.title,
                "artist": candidate.artist,
                "duration": candidate.duration,
            }
            if isinstance(candidate, LyricCandidate):
                item.update(
                    instrumental=candidate.instrumental,
                    plain_text_characters=len(candidate.plain_text or ""),
                    synced_text_characters=len(candidate.synced_text or ""),
                )
            else:
                item.update(score=candidate.score, recording_id=candidate.recording_id)
                item.update(
                    title_aliases=candidate.title_aliases,
                    artist_aliases=candidate.artist_aliases,
                    isrcs=candidate.isrcs,
                    version=candidate.version,
                )
            candidates.append(item)
        return {
            "provider": self.provider,
            "status": self.status.value,
            "message": self.message,
            "attempts": self.attempts,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "candidates": candidates,
            "releases": [
                {
                    "external_id": release.external_id,
                    "title": release.title,
                    "date": release.date,
                    "country": release.country,
                }
                for release in self.releases
            ],
            "cached": self.cached,
        }
