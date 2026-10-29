"""Automatic consent is limited to corroborated identity and matching absent lyrics."""

from afinario.change_plan import agreement_allows_rename
from afinario.domain import Status
from afinario.lyrics import LyricStatus, assess, candidate_key, text_key
from afinario.resolver import normalize


def identity_is_valid(record, report, draft):
    return bool(
        agreement_allows_rename(report, draft)
        and all(
            normalize(" / ".join(getattr(record.tags, name)))
            == normalize(getattr(report.decision, name))
            for name in ("artist", "title")
        )
    )


def automatic_fields(record, report, draft, lyrics, *, tags=False, apply_lyrics=False):
    values = {}
    if tags and agreement_allows_rename(report, draft):
        for name in ("artist", "title"):
            proposed = (getattr(report.decision, name),)
            if getattr(record.tags, name) != proposed:
                values[name] = proposed
    if not apply_lyrics or not identity_is_valid(record, report, draft) or record.tags.has_lyrics:
        return values
    if not lyrics or lyrics.status != LyricStatus.FOUND or lyrics.existing:
        return values
    if any(
        draft.field(name).changed and draft.field(name).source == "manual"
        for name in ("lyrics", "synced_lyrics")
    ):
        return values
    if (normalize(lyrics.artist), normalize(lyrics.title)) != (
        normalize(report.decision.artist),
        normalize(report.decision.title),
    ):
        return values
    candidates = [
        c
        for r in lyrics.results
        if r.status == Status.OK
        for c in r.candidates
        if c.artist
        and c.title
        and c.duration is not None
        and normalize(c.artist) == normalize(lyrics.artist)
        and normalize(c.title) == normalize(lyrics.title)
        and assess(c, lyrics.artist, lyrics.title, record.duration).eligible
        and text_key(c)
    ]
    if not candidates or len({text_key(c) for c in candidates}) != 1:
        return values
    candidate = sorted(candidates, key=lambda c: (not bool(c.synced_text), candidate_key(c)))[0]
    # An explicit edit is preserved; automatic suggestions may be superseded by verified evidence.
    for name, text in (("lyrics", candidate.plain_text), ("synced_lyrics", candidate.synced_text)):
        field = draft.field(name)
        if text and not field.current and (not field.changed or field.source.startswith("letra:")):
            values[name] = (text,)
    return values
