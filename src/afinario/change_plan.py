"""Immutable previews. Names are portable and reservations include existing files."""

import json
import os
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from afinario.file_safety import directory_identity, regular_file
from afinario.identification import file_digest
from afinario.inventory import InventoryRecord
from afinario.library import LibraryError, _record
from afinario.lyrics import digest, recognition_key, record_key
from afinario.resolver import DecisionStatus, normalize, resolve
from afinario.review import validate_filename
from afinario.tag_writer import WRITABLE_FORMATS


def name_key(name):
    return unicodedata.normalize("NFC", name).casefold().rstrip(" .")


def _fit(text, suffix, extension):
    while text and (
        len((text + suffix + extension).encode("utf-8")) > 240
        or len((text + suffix + extension).encode("utf-16-le")) // 2 > 240
    ):
        text = text[:-1]
    return text.rstrip(" .") + suffix + extension


def portable_name(artist, title, extension):
    text = unicodedata.normalize("NFC", f"{artist} - {title}")
    text = re.sub(r'[/\\<>:"|?*\x00-\x1f\x7f]', " - ", text)
    text = " ".join(text.split()).strip(" .")
    if not text:
        raise ValueError("Artista e título não produziram um nome válido.")
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", text.split(".")[0]):
        text = "_" + text
    return _fit(text, "", extension)


def agreement_allows_rename(report, draft):
    if not report or report.decision.status != DecisionStatus.AGREEMENT or not report.source_sha256:
        return False
    # Re-evaluate independent evidence; never trust a label, MusicBrainz or old proposals as votes.
    decision = resolve(report.results, report.duration)
    if decision.status != DecisionStatus.AGREEMENT or not decision.artist or not decision.title:
        return False
    if any(r.provider == "previous" for r in report.results):
        return False
    if (decision.artist, decision.title) != (report.decision.artist, report.decision.title):
        return False
    return all(
        normalize(" / ".join(draft.field(name).proposed)) == normalize(value)
        for name, value in (("artist", decision.artist), ("title", decision.title))
    )


@dataclass(frozen=True)
class PlanItem:
    record: InventoryRecord
    source: str
    destination: str
    source_sha256: str = ""
    directory_id: tuple[int, int] = ()
    file_identity: tuple[int, int] = ()
    changes: dict = field(default_factory=dict, repr=False)
    review_signature: str = ""
    recognition_signature: str = ""
    automatic_name: bool = False
    status: str = "ready"
    message: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    automatic_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChangePlan:
    items: tuple[PlanItem, ...]
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def ready(self):
        return tuple(item for item in self.items if item.status == "ready")


def plan_from_json(payload):
    data = json.loads(payload)
    items = []
    for item in data["items"]:
        item["record"] = _record(json.dumps(item["record"]))
        for key in ("directory_id", "file_identity", "automatic_fields"):
            item.setdefault(key, ())
            item[key] = tuple(item[key])
        item["changes"] = {k: tuple(v) for k, v in item["changes"].items()}
        items.append(PlanItem(**item))
    return ChangePlan(tuple(items), data["id"])


def make_plan(
    library,
    records,
    *,
    consensus_names=True,
    automatic_only=False,
    stop=None,
    auto_tags=False,
    auto_lyrics=False,
):
    from afinario.automation import automatic_fields

    stop = stop or threading.Event()
    reports = {r.file_id: r for r in library.load_identifications(records)}
    reviews = {r.file_id: r for r in library.load_reviews(records)}
    lyrics = {r.file_id: r for r in library.load_lyrics(records)}
    occupied = {}
    items = []
    for record in sorted(records, key=lambda r: (name_key(r.path), r.id)):
        source = Path(record.path).absolute()
        destination = source
        changes = {}
        source_hash = ""
        directory_id = file_id = ()
        automatic = False
        auto_values = {}
        status, message = "ready", ""
        draft, report = reviews[record.id], reports.get(record.id)
        try:
            library.ensure_file_unlocked(record.id)
            if record.status == "error" or draft.blocked_reason:
                raise ValueError(draft.blocked_reason or "Arquivo ilegível.")
            if record_key(record) != draft.snapshot_key:
                raise ValueError("O inventário mudou; gere a prévia novamente.")
            source = source.parent.resolve(strict=True) / source.name
            directory_id = directory_identity(source.parent)
            info = regular_file(source)
            file_id = (info.st_dev, info.st_ino)
            if (info.st_size, info.st_mtime_ns) != (record.size, record.mtime_ns):
                raise ValueError("O arquivo mudou desde a varredura.")
            draft.approve(draft.approved_fields)
            if not automatic_only:
                changes = {
                    f.name: f.proposed
                    for f in draft.fields
                    if f.approved and f.changed and f.name != "filename"
                }
            auto_values = automatic_fields(
                record,
                report,
                draft,
                lyrics.get(record.id),
                tags=auto_tags,
                apply_lyrics=auto_lyrics,
            )
            manual_keys = set(changes)
            changes = {**auto_values, **changes}
            name_field = draft.field("filename")
            explicit_name = name_field.approved and name_field.changed and not automatic_only
            automatic = bool(consensus_names and agreement_allows_rename(report, draft))
            if name_field.changed and not name_field.approved:
                automatic = False
            if explicit_name:
                desired = name_field.proposed[0]
            elif automatic:
                desired = portable_name(
                    report.decision.artist, report.decision.title, source.suffix
                )
            else:
                desired = source.name
            if changes and record.format not in WRITABLE_FORMATS:
                raise ValueError("Tags deste formato ainda não têm escrita validada.")
            if not changes and desired == source.name:
                status, message = "noop", "Sem alterações aprovadas ou concordância suficiente."
            else:
                validate_filename((desired,), (source.name,))
                if source.parent not in occupied:
                    occupied[source.parent] = {}
                    for entry in source.parent.iterdir():
                        occupied[source.parent].setdefault(name_key(entry.name), []).append(
                            entry.name
                        )
                names = occupied[source.parent]
                collisions = [n for n in names.get(name_key(desired), []) if n != source.name]
                if collisions:
                    if explicit_name:
                        raise ValueError(
                            "Nome aprovado já ocupado; revise a colisão ou ciclo de nomes."
                        )
                    stem = Path(desired).stem
                    number = 2
                    while True:
                        available = _fit(stem, f" ({number})", source.suffix)
                        if name_key(available) not in names:
                            desired = available
                            message = "Sufixo reservado para evitar colisão."
                            break
                        number += 1
                destination = source.with_name(desired)
                if os.name == "nt" and len(str(destination)) >= 260:
                    raise ValueError(
                        "O caminho excede o limite portável do Windows; encurte o nome."
                    )
                names.setdefault(name_key(desired), []).append(f"reservation:{record.id}")
                source_hash = file_digest(source, stop)
                if report and report.source_sha256 and source_hash != report.source_sha256:
                    raise ValueError("O conteúdo mudou desde o reconhecimento.")
        except (OSError, ValueError, LibraryError) as exc:
            status, message = "blocked", str(exc)
        items.append(
            PlanItem(
                record,
                str(source),
                str(destination),
                source_hash,
                directory_id,
                file_id,
                changes,
                digest(asdict(draft)),
                recognition_key(report),
                automatic and not explicit_name,
                status,
                message,
                automatic_fields=tuple(k for k in auto_values if k not in manual_keys),
            )
        )
    return ChangePlan(tuple(items))
