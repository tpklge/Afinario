"""Durable item checkpoints. Pause drains in-flight work and resume is explicit."""

import json
import sqlite3
import sys
import threading
from contextlib import contextmanager
from uuid import uuid4

from afinario.file_safety import operation_lock
from afinario.library import LibraryError, _json, _now


class BatchSession:
    def __init__(self, library, kind, payload=None, items=(), *, batch_id=None):
        self.library = library
        self.id = batch_id or str(uuid4())
        if batch_id is None:
            with library._transaction() as db:
                db.execute(
                    "INSERT INTO task_batches VALUES (?, ?, 'running', ?, ?, ?, 0, '')",
                    (self.id, kind, _now(), _now(), _json(payload)),
                )
                for ordinal, (key, data) in enumerate(items):
                    db.execute(
                        "INSERT INTO task_items VALUES (?, ?, ?, 'queued', ?, '')",
                        (self.id, key, ordinal, _json(data)),
                    )
        self.row = library.connection.execute(
            "SELECT * FROM task_batches WHERE id=?", (self.id,)
        ).fetchone()
        if not self.row or self.row["kind"] != kind:
            raise LibraryError("Lote não encontrado ou incompatível.")
        self.payload = json.loads(self.row["payload_json"])

    @contextmanager
    def running(self):
        with operation_lock(self.library.path.parent / f".afinario-batch-{self.id}.lock"):
            if self.row["state"] in ("completed", "cancelled"):
                raise LibraryError("Este lote já foi encerrado.")
            self.finish("running")
            yield self

    def items(self):
        return [
            dict(r)
            for r in self.library.connection.execute(
                "SELECT * FROM task_items WHERE batch_id=? ORDER BY ordinal", (self.id,)
            )
        ]

    def mark(self, key, state, message=""):
        with self.library._transaction() as db:
            db.execute(
                "UPDATE task_items SET state=?,message=? WHERE batch_id=? AND item_key=?",
                (state, message, self.id, key),
            )

    def finish(self, state, message=""):
        with self.library._transaction() as db:
            db.execute(
                "UPDATE task_batches SET state=?,updated_at=?,message=? WHERE id=?",
                (state, _now(), message, self.id),
            )

    def reserve_audd(self, used):
        # Called by provider threads, each with its own short-lived SQLite connection.
        with sqlite3.connect(self.library.path, timeout=10) as db:
            if sys.platform == "darwin":
                db.execute("PRAGMA fullfsync=ON")
            db.execute(
                "UPDATE task_batches SET audd_used=MAX(audd_used,?),updated_at=? WHERE id=?",
                (used, _now(), self.id),
            )


def batches(library):
    return [
        dict(r)
        for r in library.connection.execute(
            "SELECT b.*,COUNT(i.item_key) AS total, "
            "SUM(i.state='completed') AS completed, SUM(i.state='failed') AS failed "
            "FROM task_batches b "
            "LEFT JOIN task_items i ON i.batch_id=b.id GROUP BY b.id ORDER BY b.created_at DESC"
        )
    ]


class PauseRequest:
    def __init__(self):
        self.requested = threading.Event()

    def pause(self):
        self.requested.set()


def fail_batch(path, batch_id, message):
    try:
        with sqlite3.connect(path, timeout=10) as db:
            db.execute(
                "UPDATE task_batches SET state='failed',updated_at=?,message=? WHERE id=?",
                (_now(), message, batch_id),
            )
    except sqlite3.Error:
        pass
