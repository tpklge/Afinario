"""Decisões conservadoras e explicáveis; tags existentes não participam da votação."""

import re
import unicodedata
from dataclasses import dataclass, replace
from enum import StrEnum

from afinario.domain import ProviderResult, RecordingCandidate, Status


class DecisionStatus(StrEnum):
    AGREEMENT = "agreement"
    INCOMPLETE = "incomplete"
    CONFLICT = "conflict"
    NO_MATCH = "no_match"
    PENDING = "pending"
    CHANGED = "changed"


DECISION_LABELS = {
    DecisionStatus.AGREEMENT: "Fontes concordam",
    DecisionStatus.INCOMPLETE: "Confirmação incompleta",
    DecisionStatus.CONFLICT: "Revisão necessária",
    DecisionStatus.NO_MATCH: "Não identificada",
    DecisionStatus.PENDING: "Consulta bloqueada ou falhou",
    DecisionStatus.CHANGED: "Arquivo alterado",
}


@dataclass(frozen=True)
class Decision:
    status: DecisionStatus
    artist: str | None = None
    title: str | None = None
    recording_id: str | None = None
    reasons: tuple[str, ...] = ()
    proposed_fields: tuple[str, ...] = ()
    policy_version: str = "resolver-v1"


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    # Latin accents can vary in credits. Preserve meaningful marks in other
    # scripts, including Japanese dakuten (ハ and パ must remain different).
    value = "".join(
        "".join(
            part for part in unicodedata.normalize("NFD", char) if not unicodedata.combining(part)
        )
        if "LATIN" in unicodedata.name(char, "")
        else char
        for char in value
    )
    return " ".join(
        "".join(
            char if char.isalnum() or unicodedata.category(char).startswith("M") else " "
            for char in value
        ).split()
    )


def _names(value: str | None, aliases: tuple[str, ...]) -> set[str]:
    return {normalize(item) for item in (value, *aliases) if item and normalize(item)}


def versions(candidate: RecordingCandidate) -> frozenset[str]:
    value = normalize(" ".join((candidate.title or "", candidate.version or "")))
    markers = (
        "live",
        "ao vivo",
        "remix",
        "mix",
        "radio edit",
        "acoustic",
        "acustico",
        "instrumental",
        "cover",
        "karaoke",
        "demo",
        "tv size",
        "short version",
        "extended",
        "sped up",
        "slowed",
        "remaster",
        "single version",
    )
    return frozenset(marker for marker in markers if re.search(r"\b" + marker + r"\b", value))


def _enriched(
    candidate: RecordingCandidate, metadata: list[RecordingCandidate]
) -> RecordingCandidate:
    match = next(
        (
            item
            for item in metadata
            if candidate.recording_id and item.recording_id == candidate.recording_id
        ),
        None,
    )
    if match is None:
        return candidate
    return replace(
        candidate,
        title=candidate.title or match.title,
        artist=candidate.artist or match.artist,
        duration=candidate.duration if candidate.duration is not None else match.duration,
        title_aliases=tuple(
            dict.fromkeys((*candidate.title_aliases, match.title or "", *match.title_aliases))
        ),
        artist_aliases=tuple(
            dict.fromkeys((*candidate.artist_aliases, match.artist or "", *match.artist_aliases))
        ),
        isrcs=tuple(dict.fromkeys((*candidate.isrcs, *match.isrcs))),
        version=candidate.version or match.version,
    )


def _leader(candidates: list[RecordingCandidate], provider: str):
    def order(item):
        return (
            -(item.score or 0),
            normalize(item.artist or ""),
            normalize(item.title or ""),
            item.recording_id or "",
            item.external_id or "",
            item.artist or "",
            item.title or "",
        )

    groups: dict[tuple, RecordingCandidate] = {}
    for candidate in candidates:
        key = (
            (candidate.recording_id,)
            if candidate.recording_id
            else (
                normalize(candidate.artist or ""),
                normalize(candidate.title or ""),
                versions(candidate),
            )
        )
        previous = groups.get(key)
        if previous is None or order(candidate) < order(previous):
            groups[key] = candidate
    values = sorted(groups.values(), key=order)
    if not values:
        return None, False
    # Provisional guardrails, not calibrated probabilities or automatic approval criteria.
    ambiguous = len(values) > 1 and (
        provider != "acoustid" or (values[0].score or 0) - (values[1].score or 0) < 0.05
    )
    weak = provider == "acoustid" and (values[0].score or 0) < 0.8
    return values[0], ambiguous or weak


def resolve(results: tuple[ProviderResult, ...], duration: float | None) -> Decision:
    metadata = [
        candidate
        for result in results
        if result.provider == "musicbrainz" and result.status == Status.OK
        for candidate in result.candidates
        if isinstance(candidate, RecordingCandidate)
    ]
    leaders = []
    audio_results = list(
        {
            result.provider: result
            for result in results
            if result.provider in ("acoustid", "shazamio", "audd")
        }.values()
    )
    for result in audio_results:
        if result.status != Status.OK:
            continue
        candidates = [
            _enriched(item, metadata)
            for item in result.candidates
            if isinstance(item, RecordingCandidate)
        ]
        leader, ambiguous = _leader(candidates, result.provider)
        if leader is None:
            continue
        if ambiguous:
            return Decision(
                DecisionStatus.CONFLICT,
                reasons=("Há candidatos próximos ou evidência insuficiente no provedor.",),
            )
        if duration is not None and leader.duration is not None:
            if abs(duration - leader.duration) > max(3, duration * 0.02):
                return Decision(
                    DecisionStatus.CONFLICT,
                    reasons=("A duração do candidato é incompatível com o arquivo.",),
                )
        leaders.append((result.provider, leader))
    if not leaders:
        if audio_results and all(item.status == Status.NOT_FOUND for item in audio_results):
            return Decision(DecisionStatus.NO_MATCH, reasons=("Nenhuma fonte reconheceu o áudio.",))
        return Decision(
            DecisionStatus.PENDING,
            reasons=("Não foi possível concluir as consultas de reconhecimento.",),
        )
    if len(leaders) > 1:
        a = leaders[0][1]
        for _, b in leaders[1:]:
            if versions(a) != versions(b):
                return Decision(
                    DecisionStatus.CONFLICT,
                    reasons=("As fontes indicam versões diferentes da faixa.",),
                )
            same_artist = bool(
                _names(a.artist, a.artist_aliases) & _names(b.artist, b.artist_aliases)
            )
            same_title = bool(_names(a.title, a.title_aliases) & _names(b.title, b.title_aliases))
            if a.isrcs and b.isrcs and not set(a.isrcs).intersection(b.isrcs):
                return Decision(
                    DecisionStatus.CONFLICT,
                    reasons=("Os identificadores ISRC informados são incompatíveis.",),
                )
            if (a.recording_id and b.recording_id and a.recording_id != b.recording_id) or not (
                same_artist and same_title
            ):
                return Decision(
                    DecisionStatus.CONFLICT,
                    reasons=("Artista, título ou gravação divergem entre as fontes.",),
                )
        return Decision(
            DecisionStatus.AGREEMENT,
            a.artist,
            a.title,
            a.recording_id,
            (
                f"{len(leaders)} reconhecedores concordam em artista e título, "
                "incluindo aliases conhecidos.",
                "Álbum, ano e número de faixa não foram confirmados.",
            ),
            ("artist", "title"),
        )
    leader = leaders[0][1]
    if not leader.artist or not leader.title:
        return Decision(
            DecisionStatus.INCOMPLETE,
            reasons=("A fonte retornou identificação sem artista ou título completos.",),
        )
    return Decision(
        DecisionStatus.INCOMPLETE,
        leader.artist,
        leader.title,
        leader.recording_id,
        (
            "Apenas um reconhecedor trouxe uma identificação utilizável.",
            "Revise a proposta; não há confirmação independente.",
        ),
        ("artist", "title"),
    )
