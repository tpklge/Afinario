"""CSV/JSON audit exports without credentials, audio, fingerprints or full lyrics."""

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path

from afinario.batches import batches
from afinario.library import _now
from afinario.logging_config import RedactSecrets
from afinario.review import LYRIC_FIELDS


def change_value(name, values):
    if name in LYRIC_FIELDS:
        return {"characters": sum(len(v) for v in values), "present": bool(values)}
    return list(values)


def build_report(library, *, file_ids=None, secrets=()):
    state = library.load()
    wanted = set(file_ids) if file_ids is not None else None
    identifications = {r.file_id: r for r in state.identifications}
    lyrics = {r.file_id: r for r in state.lyrics}
    reviews = {r.file_id: r for r in state.reviews}
    files = []
    for record in state.records:
        if wanted is not None and record.id not in wanted:
            continue
        report, lyric, draft = (
            identifications.get(record.id),
            lyrics.get(record.id),
            reviews.get(record.id),
        )
        files.append(
            {
                "file_id": record.id,
                "path": record.path,
                "format": record.format,
                "inventory_status": record.status,
                "current_tags": asdict(record.tags),
                "identification": report.summary() if report else None,
                "lyrics": None
                if lyric is None
                else {
                    "status": lyric.status,
                    "artist": lyric.artist,
                    "title": lyric.title,
                    "reasons": lyric.reasons,
                    "sources": [r.summary() for r in lyric.results],
                },
                "review": []
                if draft is None
                else [
                    {
                        "field": f.name,
                        "current": change_value(f.name, f.current),
                        "proposed": change_value(f.name, f.proposed),
                        "approved": f.approved,
                        "source": f.source,
                    }
                    for f in draft.fields
                    if f.changed
                ],
            }
        )
    operations = []
    for row in library.connection.execute("SELECT * FROM file_operations ORDER BY rowid"):
        if wanted is not None and row["file_id"] not in wanted:
            continue
        payload = json.loads(row["payload_json"])
        item = payload["item"]
        operations.append(
            {
                "id": row["id"],
                "file_id": row["file_id"],
                "kind": row["kind"],
                "state": row["state"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message": row["message"],
                "source": item["source"],
                "destination": item["destination"],
                "backup": payload["backup"],
                "changes": {k: change_value(k, v) for k, v in item["changes"].items()},
                "automatic_fields": item.get("automatic_fields", []),
                "automatic_name": item["automatic_name"],
                "before_tags": item["record"]["tags"],
                "evidence": payload.get("evidence"),
            }
        )
    jobs = []
    for batch in batches(library):
        items = [
            dict(r)
            for r in library.connection.execute(
                "SELECT item_key,state,message FROM task_items WHERE batch_id=? ORDER BY ordinal",
                (batch["id"],),
            )
            if wanted is None or r["item_key"] in wanted
        ]
        if wanted is not None and not items:
            continue
        jobs.append(
            {
                k: batch[k]
                for k in ("id", "kind", "state", "created_at", "updated_at", "audd_used", "message")
            }
            | {
                "items": items,
                "total": len(items),
                "completed": sum(i["state"] == "completed" for i in items),
            }
        )
    data = {
        "schema_version": 1,
        "generated_at": _now(),
        "files": files,
        "operations": operations,
        "batches": jobs,
    }
    redactor = RedactSecrets(tuple(secrets))

    def redact(value):
        if isinstance(value, str):
            entry = logging.LogRecord("afinario", 20, "", 0, value, (), None)
            redactor.filter(entry)
            return entry.getMessage()
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [redact(v) for v in value]
        return value

    return redact(data)


def safe_cell(value):
    text = str(value)
    return "'" + text if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else text


def export_report(library, destination, *, file_ids=None, secrets=()):
    path = Path(destination)
    if path.suffix.casefold() not in (".csv", ".json"):
        raise ValueError("Escolha um arquivo CSV ou JSON.")
    data = build_report(library, file_ids=file_ids, secrets=secrets)
    with path.open(
        "x", encoding="utf-8-sig" if path.suffix.casefold() == ".csv" else "utf-8", newline=""
    ) as stream:
        if path.suffix.casefold() == ".json":
            json.dump(data, stream, ensure_ascii=False, indent=2)
        else:
            columns = (
                "tipo",
                "id",
                "arquivo",
                "situacao",
                "artista",
                "titulo",
                "letras",
                "fontes_letras",
                "fontes",
                "alteracoes",
                "backup",
                "motivo",
            )
            writer = csv.writer(stream)
            writer.writerow(columns)
            for item in data["files"]:
                report = item["identification"] or {}
                decision = report.get("decision", {})
                writer.writerow(
                    map(
                        safe_cell,
                        (
                            "musica",
                            item["file_id"],
                            item["path"],
                            decision.get("status", item["inventory_status"]),
                            "; ".join(item["current_tags"]["artist"]),
                            "; ".join(item["current_tags"]["title"]),
                            (item["lyrics"] or {}).get("status", ""),
                            json.dumps(
                                (item["lyrics"] or {}).get("sources", []), ensure_ascii=False
                            ),
                            json.dumps(report.get("results", []), ensure_ascii=False),
                            json.dumps(item["review"], ensure_ascii=False),
                            "",
                            "; ".join(decision.get("reasons", [])),
                        ),
                    )
                )
            for item in data["operations"]:
                writer.writerow(
                    map(
                        safe_cell,
                        (
                            "operacao",
                            item["id"],
                            item["source"],
                            item["state"],
                            "",
                            "",
                            "",
                            "",
                            json.dumps(item.get("evidence") or {}, ensure_ascii=False),
                            json.dumps(
                                {"destination": item["destination"], "changes": item["changes"]},
                                ensure_ascii=False,
                            ),
                            item["backup"],
                            item["message"],
                        ),
                    )
                )
            for item in data["batches"]:
                writer.writerow(
                    map(
                        safe_cell,
                        (
                            "lote",
                            item["id"],
                            item["kind"],
                            item["state"],
                            "",
                            "",
                            "",
                            "",
                            "",
                            json.dumps(item["items"], ensure_ascii=False),
                            "",
                            item["message"],
                        ),
                    )
                )
    return len(data["files"])
