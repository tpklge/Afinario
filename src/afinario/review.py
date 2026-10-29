"""Revisão por campo: propostas, procedência e aprovação da versão exata."""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from afinario.domain import LyricCandidate
from afinario.lyrics import (
    TIMESTAMP,
    LyricStatus,
    candidate_key,
    digest,
    recognition_key,
    record_key,
)
from afinario.resolver import DecisionStatus, normalize

FIELD_LABELS = {
    "artist": "Artista",
    "title": "Título",
    "album": "Álbum",
    "album_artist": "Artista do álbum",
    "track": "Faixa",
    "disc": "Disco",
    "date": "Data/ano",
    "genre": "Gênero",
    "filename": "Nome do arquivo",
    "lyrics": "Letra simples",
    "synced_lyrics": "Letra sincronizada (LRC)",
}
LYRIC_FIELDS = ("lyrics", "synced_lyrics")


@dataclass(frozen=True)
class FieldChoice:
    name: str
    current: tuple[str, ...] = ()
    proposed: tuple[str, ...] = ()
    source: str = "preservado"
    approved: bool = False

    @property
    def changed(self):
        return self.current != self.proposed


@dataclass(frozen=True)
class ReviewDraft:
    file_id: str
    snapshot_key: str
    context_key: str
    fields: tuple[FieldChoice, ...]
    revision: int = 0
    has_existing_lyrics: bool = False
    replace_existing_lyrics: bool = False
    lyric_query_artist: str = ""
    lyric_query_title: str = ""
    approved_at: str | None = None
    policy_version: str = "review-v1"
    blocked_reason: str = ""

    def field(self, name):
        return next(item for item in self.fields if item.name == name)

    def invalidate(self):
        return replace(
            self,
            fields=tuple(replace(item, approved=False) for item in self.fields),
            approved_at=None,
        )

    def edit(self, name: str, values: tuple[str, ...], source: str = "manual"):
        if (
            name not in FIELD_LABELS
            or not isinstance(values, tuple)
            or any(not isinstance(value, str) for value in values)
        ):
            raise ValueError("Campo de revisão inválido.")
        fields = []
        for item in self.invalidate().fields:
            if item.name == name:
                item = replace(item, proposed=values, source=source)
            elif name in ("artist", "title") and item.name in LYRIC_FIELDS:
                item = replace(item, proposed=item.current, source="preservado")
            fields.append(item)
        return replace(self.invalidate(), fields=tuple(fields))

    def select_lyrics(self, candidate: LyricCandidate):
        draft = self
        origin = "local" if candidate.provider in ("embedded", "local") else "letra"
        for name, text in (
            ("lyrics", candidate.plain_text),
            ("synced_lyrics", candidate.synced_text),
        ):
            draft = draft.edit(
                name, (text,) if text else (), f"{origin}:{candidate_key(candidate)}"
            )
        return draft

    def allow_replacement(self, allowed: bool):
        return replace(self.invalidate(), replace_existing_lyrics=allowed)

    def approve(self, names):
        selected = set(names)
        if selected - FIELD_LABELS.keys():
            raise ValueError("Seleção de aprovação inválida.")
        if selected and self.blocked_reason:
            raise ValueError(self.blocked_reason)
        for name in selected:
            item = self.field(name)
            if not item.changed:
                raise ValueError(f"{FIELD_LABELS[name]} não possui alteração para aprovar.")
            if name in ("artist", "title", *LYRIC_FIELDS) and not any(
                value.strip() for value in item.proposed
            ):
                raise ValueError(f"{FIELD_LABELS[name]} não pode ser aprovado sem conteúdo.")
            if name in LYRIC_FIELDS:
                if name == "synced_lyrics" and not any(TIMESTAMP.search(v) for v in item.proposed):
                    raise ValueError("A letra sincronizada precisa conter timestamps LRC válidos.")
                if self.has_existing_lyrics and not self.replace_existing_lyrics:
                    raise ValueError("Autorize explicitamente a substituição da letra existente.")
                if item.source.startswith("letra:") and not self.lyric_query_matches:
                    raise ValueError(
                        "Atualize a busca de letras para o artista e título desta revisão."
                    )
            if name == "filename":
                validate_filename(item.proposed, item.current)
        return replace(
            self,
            fields=tuple(replace(item, approved=item.name in selected) for item in self.fields),
            approved_at=datetime.now(UTC).isoformat() if selected else None,
        )

    @property
    def lyric_query_matches(self):
        return normalize(" / ".join(self.field("artist").proposed)) == normalize(
            self.lyric_query_artist
        ) and normalize(" / ".join(self.field("title").proposed)) == normalize(
            self.lyric_query_title
        )

    @property
    def approved_fields(self):
        return tuple(item.name for item in self.fields if item.approved)


def review_context(record, identification=None, lyrics=None):
    return digest(
        [record_key(record), recognition_key(identification), lyrics.id if lyrics else ""]
    )


def build_review(record, identification=None, lyrics=None, *, revision=0):
    fields = []
    for name in FIELD_LABELS:
        if name == "filename":
            current = (Path(record.path).name,)
        elif name in LYRIC_FIELDS:
            attribute = "plain_text" if name == "lyrics" else "synced_text"
            current = tuple(
                text
                for candidate in (lyrics.existing if lyrics else ())
                if (text := getattr(candidate, attribute))
            )
        else:
            current = getattr(record.tags, name)
        proposed, source = current, "preservado"
        if name in ("artist", "title") and identification is not None:
            value = getattr(identification.decision, name)
            if value:
                proposed, source = (value,), "reconhecimento"
        fields.append(FieldChoice(name, current, proposed, source))
    blocked = (
        "Não é possível aprovar um arquivo ilegível. Faça uma nova varredura."
        if (record.status == "error")
        else ""
    )
    if (
        identification
        and identification.decision.status == DecisionStatus.CHANGED
        or (lyrics and lyrics.status == LyricStatus.CHANGED)
    ):
        blocked = "O arquivo mudou. Faça uma nova varredura antes de aprovar."
    draft = ReviewDraft(
        record.id,
        record_key(record),
        review_context(record, identification, lyrics),
        tuple(fields),
        revision=revision,
        has_existing_lyrics=record.tags.has_lyrics or bool(lyrics and lyrics.existing),
        lyric_query_artist=lyrics.artist if lyrics else "",
        lyric_query_title=lyrics.title if lyrics else "",
        blocked_reason=blocked,
    )
    if lyrics and not draft.has_existing_lyrics and lyrics.recommended_key:
        candidate = next(
            (c for c in lyrics.candidates if candidate_key(c) == lyrics.recommended_key), None
        )
        if candidate is not None and draft.lyric_query_matches:
            draft = draft.select_lyrics(candidate)
    return draft


def validate_filename(proposed, current):
    if len(proposed) != 1 or not proposed[0]:
        raise ValueError("Informe somente um nome de arquivo.")
    name = proposed[0]
    if (
        any(char in name for char in '/\\<>:"|?*')
        or any(ord(char) < 32 for char in name)
        or name in (".", "..")
        or name.endswith((".", " "))
        or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0])
        or len(name.encode("utf-8")) > 255
    ):
        raise ValueError("O nome precisa ser válido em macOS e Windows, sem indicar outra pasta.")
    if Path(name).suffix.casefold() != Path(current[0]).suffix.casefold():
        raise ValueError("A aprovação do nome deve preservar a extensão original do áudio.")


def review_from_data(data):
    data = dict(data)
    data["fields"] = tuple(
        FieldChoice(
            item["name"],
            tuple(item["current"]),
            tuple(item["proposed"]),
            item["source"],
            item["approved"],
        )
        for item in data["fields"]
    )
    if tuple(item.name for item in data["fields"]) != tuple(FIELD_LABELS):
        raise ValueError("Campos da revisão inválidos.")
    draft = ReviewDraft(**data)
    # Validation is shared by persisted and new approvals, not trusted blindly.
    draft.approve(draft.approved_fields)
    return draft


def rebase_review(previous, record, identification=None, lyrics=None, *, revision=None):
    """Preserve explicit edits across new evidence, invalidating previous approvals."""
    draft = build_review(
        record,
        identification,
        lyrics,
        revision=(previous.revision if previous else 0) if revision is None else revision,
    )
    if previous is None or previous.snapshot_key != draft.snapshot_key:
        return draft
    if previous.context_key == draft.context_key:
        return replace(previous, revision=draft.revision)
    for item in previous.fields:
        if item.name not in LYRIC_FIELDS and item.source not in ("preservado", "reconhecimento"):
            draft = draft.edit(item.name, item.proposed, item.source)
    if lyrics and not draft.has_existing_lyrics and draft.lyric_query_matches:
        suggested = next(
            (c for c in lyrics.candidates if candidate_key(c) == lyrics.recommended_key), None
        )
        if suggested:
            draft = draft.select_lyrics(suggested)
    known_candidates = {candidate_key(c) for c in lyrics.candidates} if lyrics else set()
    for item in previous.fields:
        if item.name in LYRIC_FIELDS and (
            item.source == "manual" or item.source.partition(":")[2] in known_candidates
        ):
            draft = draft.edit(item.name, item.proposed, item.source)
    return draft
