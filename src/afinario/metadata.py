"""Enriquecimento de uma gravação; lançamentos são alternativas, não tags aprovadas."""

import time
from uuid import UUID

from afinario.domain import ProviderResult, RecordingCandidate, ReleaseCandidate, Status
from afinario.providers import number, text
from afinario.transport import ProviderError, Transport


class MusicBrainz:
    name = "musicbrainz"

    def __init__(self, transport: Transport):
        self.transport = transport

    def recording(self, recording_id: str) -> ProviderResult:
        start = time.monotonic()
        attempts = 0
        try:
            recording_id = str(UUID(recording_id))
            data, attempts = self.transport.json(
                self.name,
                "GET",
                f"https://musicbrainz.org/ws/2/recording/{recording_id}",
                params={"inc": "artists+aliases+isrcs+releases", "fmt": "json"},
            )
            if not isinstance(data, dict) or data.get("id") != recording_id:
                raise ValueError("Invalid recording")
            credits = data.get("artist-credit", [])
            if not isinstance(credits, list):
                raise ValueError("Invalid artist credits")
            artist = (
                "".join(
                    (text(credit.get("name")) or text(credit.get("artist", {}).get("name")) or "")
                    + (credit.get("joinphrase") or "")
                    for credit in credits
                )
                or None
            )
            artist_aliases = ()
            if len(credits) == 1:
                artist_aliases = tuple(
                    name
                    for alias in credits[0].get("artist", {}).get("aliases", [])
                    if (name := text(alias.get("name")))
                )
            aliases = tuple(
                name for alias in data.get("aliases", []) if (name := text(alias.get("name")))
            )
            length = number(data.get("length"))
            candidate = RecordingCandidate(
                self.name,
                recording_id,
                text(data.get("title")),
                artist,
                length / 1000 if length is not None else None,
                recording_id=recording_id,
                title_aliases=aliases,
                artist_aliases=artist_aliases,
                isrcs=tuple(value for value in data.get("isrcs", []) if text(value)),
                version=text(data.get("disambiguation")),
            )
            releases = []
            seen = set()
            for row in data.get("releases", []):
                if text(row.get("id")) and text(row.get("title")) and row["id"] not in seen:
                    seen.add(row["id"])
                    releases.append(
                        ReleaseCandidate(
                            row["id"],
                            row["title"],
                            text(row.get("date")),
                            text(row.get("country")),
                        )
                    )
            return ProviderResult(
                self.name,
                Status.OK,
                "Metadados complementares recebidos.",
                (candidate,),
                attempts,
                time.monotonic() - start,
                tuple(releases),
            )
        except ProviderError as exc:
            return ProviderResult(
                self.name,
                exc.status,
                str(exc),
                attempts=exc.attempts,
                elapsed_seconds=time.monotonic() - start,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            return ProviderResult(
                self.name,
                Status.INVALID,
                "Metadados de gravação inválidos.",
                attempts=attempts,
                elapsed_seconds=time.monotonic() - start,
            )
