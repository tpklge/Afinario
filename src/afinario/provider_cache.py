"""Cache versionado de respostas normalizadas. Não armazena segredos nem fingerprints."""

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

from afinario.domain import (
    LyricCandidate,
    ProviderResult,
    RecordingCandidate,
    ReleaseCandidate,
    Status,
)


def cache_key(provider: str, *query_parts) -> str:
    query = json.dumps(
        ["recognition-v1", provider, *query_parts], ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(query.encode()).hexdigest()


class ProviderCache:
    def __init__(self, path: Path | None = None):
        self._lock = threading.RLock()
        self._query_locks: dict[str, threading.Lock] = {}
        self.memory: dict[str, tuple[float, ProviderResult]] = {}
        self.connection: sqlite3.Connection | None = None
        self.persistent_available = False
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.connection = sqlite3.connect(path, timeout=5, check_same_thread=False)
                self.connection.execute("PRAGMA journal_mode=WAL")
                self.connection.execute(
                    "CREATE TABLE IF NOT EXISTS provider_cache "
                    "(key TEXT PRIMARY KEY, expires REAL NOT NULL, payload TEXT NOT NULL)"
                )
                self.connection.commit()
                self.persistent_available = True
            except (OSError, sqlite3.Error):
                self.close()

    def close(self) -> None:
        with self._lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None

    def query_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._query_locks.setdefault(key, threading.Lock())

    def get(self, key: str, provider: str) -> ProviderResult | None:
        with self._lock:
            return self._get(key, provider)

    def _get(self, key: str, provider: str) -> ProviderResult | None:
        now = time.time()
        entry = self.memory.get(key)
        if entry is not None and entry[0] > now and entry[1].provider == provider:
            return replace(entry[1], cached=True, attempts=0, elapsed_seconds=0)
        if self.connection is None:
            return None
        try:
            row = self.connection.execute(
                "SELECT expires, payload FROM provider_cache WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None or row[0] <= now:
                return None
            data = json.loads(row[1])
            if data["provider"] != provider or data["status"] not in ("ok", "not_found"):
                return None
            candidates = []
            for value in data["candidates"]:
                kind = value.pop("candidate_type", "recording")
                if kind == "lyric":
                    candidate = LyricCandidate(**value)
                elif kind == "recording":
                    for name in ("title_aliases", "artist_aliases", "isrcs"):
                        value[name] = tuple(value.get(name, []))
                    candidate = RecordingCandidate(**value)
                else:
                    return None
                if candidate.provider != provider or (
                    candidate.external_id is not None and not isinstance(candidate.external_id, str)
                ):
                    return None
                candidates.append(candidate)
            releases = tuple(ReleaseCandidate(**value) for value in data.get("releases", []))
            return ProviderResult(
                provider,
                Status(data["status"]),
                "Resposta reutilizada do cache.",
                tuple(candidates),
                releases=releases,
                cached=True,
            )
        except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
            return None

    def put(self, key: str, result: ProviderResult) -> None:
        with self._lock:
            self._put(key, result)

    def _put(self, key: str, result: ProviderResult) -> None:
        if result.status not in (Status.OK, Status.NOT_FOUND):
            return
        if any(
            not isinstance(candidate, (RecordingCandidate, LyricCandidate))
            for candidate in result.candidates
        ):
            return
        expires = time.time() + (30 * 86400 if result.status == Status.OK else 86400)
        self.memory[key] = (expires, result)
        if self.connection is not None:
            try:
                payload = json.dumps(
                    {
                        "provider": result.provider,
                        "status": result.status.value,
                        "candidates": [
                            {
                                **asdict(candidate),
                                "candidate_type": (
                                    "lyric"
                                    if isinstance(candidate, LyricCandidate)
                                    else "recording"
                                ),
                            }
                            for candidate in result.candidates
                        ],
                        "releases": [asdict(release) for release in result.releases],
                    },
                    ensure_ascii=True,
                )
                self.connection.execute(
                    "INSERT OR REPLACE INTO provider_cache (key, expires, payload) "
                    "VALUES (?, ?, ?)",
                    (key, expires, payload),
                )
                self.connection.commit()
            except (sqlite3.Error, TypeError, ValueError):
                self.persistent_available = False
