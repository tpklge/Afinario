"""Consulta e comparação de letras, preservando texto, contexto e procedência."""

import hashlib
import json
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import mutagen
from mutagen.mp4 import MP4

from afinario.cancellation import check_cancelled
from afinario.domain import LyricCandidate, ProviderResult, Status
from afinario.identification import file_digest
from afinario.inventory import FORMAT_TYPES, InventoryRecord, is_link
from afinario.provider_cache import ProviderCache, cache_key
from afinario.providers import LRCLib, LyricsOVH
from afinario.resolver import normalize
from afinario.transport import Transport

MAX_LYRIC_BYTES = 2_000_000
TIMESTAMP = re.compile(r"\[\d{1,3}:[0-5]\d(?:[.:]\d{1,3})?\]")


def digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def record_key(record: InventoryRecord) -> str:
    return digest(asdict(record))


def recognition_key(report) -> str:
    return digest(asdict(report)) if report else ""


def candidate_key(candidate: LyricCandidate) -> str:
    return digest(asdict(candidate))


class LyricStatus(StrEnum):
    FOUND = "found"
    CONFLICT = "conflict"
    INSTRUMENTAL = "instrumental"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"
    CHANGED = "changed"


LYRIC_LABELS = {
    LyricStatus.FOUND: "Letra encontrada; revisar",
    LyricStatus.CONFLICT: "Letras exigem revisão",
    LyricStatus.INSTRUMENTAL: "Fonte indica instrumental",
    LyricStatus.ABSENT: "Letra não encontrada",
    LyricStatus.UNAVAILABLE: "Consulta incompleta ou indisponível",
    LyricStatus.CHANGED: "Arquivo alterado; refaça a varredura",
}


@dataclass(frozen=True)
class LyricAssessment:
    key: str
    eligible: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LyricReport:
    file_id: str
    path: str
    snapshot_key: str
    recording_key: str
    artist: str
    title: str
    status: LyricStatus
    results: tuple[ProviderResult, ...] = ()
    existing: tuple[LyricCandidate, ...] = ()
    assessments: tuple[LyricAssessment, ...] = ()
    reasons: tuple[str, ...] = ()
    recommended_key: str | None = None
    source_sha256: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def candidates(self) -> tuple[LyricCandidate, ...]:
        return self.existing + tuple(
            candidate
            for result in self.results
            for candidate in result.candidates
            if isinstance(candidate, LyricCandidate)
        )

    def summary(self) -> dict:
        return {
            "file_id": self.file_id,
            "status": self.status.value,
            "artist": self.artist,
            "title": self.title,
            "reasons": self.reasons,
            "results": [result.summary() for result in self.results],
        }


@dataclass(frozen=True)
class LyricOptions:
    lrclib: bool = True
    lyrics_ovh: bool = True
    mode: str = "full"
    refresh: bool = False

    def __post_init__(self):
        if self.mode not in ("full", "quick") or any(
            type(value) is not bool for value in (self.lrclib, self.lyrics_ovh, self.refresh)
        ):
            raise ValueError("Selecione uma fonte e um modo de busca de letras válido.")


def plain_from_lrc(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if TIMESTAMP.search(line):
            value = TIMESTAMP.sub("", line).strip()
            if value:
                lines.append(value)
    return "\n".join(lines)


def text_key(candidate: LyricCandidate) -> str:
    text = candidate.plain_text or plain_from_lrc(candidate.synced_text or "")
    return "\n".join(
        " ".join(unicodedata.normalize("NFC", line).split()).casefold()
        for line in text.splitlines()
        if line.strip()
    )


def assess(candidate: LyricCandidate, artist: str, title: str, duration) -> LyricAssessment:
    reasons = []
    if candidate.artist and normalize(candidate.artist) != normalize(artist):
        reasons.append("Artista diferente do pesquisado.")
    if candidate.title and normalize(candidate.title) != normalize(title):
        reasons.append("Título/versão diferente do pesquisado.")
    if duration is not None and candidate.duration is not None:
        if abs(candidate.duration - duration) > max(3, duration * 0.02):
            reasons.append("Duração incompatível com o arquivo.")
    if not (candidate.plain_text or candidate.synced_text or candidate.instrumental is True):
        reasons.append("Candidato sem texto ou indicação instrumental.")
    return LyricAssessment(candidate_key(candidate), not reasons, tuple(reasons))


def resolve_lyrics(results, artist, title, duration):
    candidates = tuple(
        candidate
        for result in results
        if result.status == Status.OK
        for candidate in result.candidates
        if isinstance(candidate, LyricCandidate)
    )
    assessments = tuple(assess(candidate, artist, title, duration) for candidate in candidates)
    eligible = [c for c, a in zip(candidates, assessments, strict=True) if a.eligible]
    texts = [c for c in eligible if text_key(c)]
    instrumentals = [c for c in eligible if c.instrumental is True]
    reasons = []
    recommended = None
    if len(eligible) != len(candidates):
        reasons.append(
            "Candidatos incompatíveis foram excluídos da sugestão; revise as alternativas."
        )
    if candidates and not eligible:
        status = LyricStatus.CONFLICT
        reasons.append("Há candidatos com título, artista ou duração incompatíveis.")
    elif instrumentals and texts or len({text_key(c) for c in texts}) > 1:
        status = LyricStatus.CONFLICT
        reasons.append("As fontes retornaram textos ou indicações instrumentais diferentes.")
    elif texts:
        status = LyricStatus.FOUND
        recommended = candidate_key(texts[0])
        reasons.append("Confira versão e texto antes de aprovar.")
        if len(texts) > 1:
            reasons.append("Os textos coincidem; lyrics.ovh pode compartilhar o catálogo LRCLIB.")
        if any(c.provider == "lyrics.ovh" for c in texts):
            reasons.append("lyrics.ovh não fornece duração ou identidade na resposta.")
    elif instrumentals:
        status = LyricStatus.INSTRUMENTAL
        reasons.append(
            "A indicação instrumental é uma evidência da fonte, separada da identificação."
        )
    elif results and all(result.status == Status.NOT_FOUND for result in results):
        status = LyricStatus.ABSENT
        reasons.append("Nenhuma das fontes consultadas encontrou letra.")
    else:
        status = LyricStatus.UNAVAILABLE
        reasons.append("Não foi possível concluir a consulta de letras.")
    if any(result.status not in (Status.OK, Status.NOT_FOUND) for result in results):
        reasons.append("Uma fonte falhou ou está indisponível; a confirmação está incompleta.")
    return status, assessments, tuple(reasons), recommended


def embedded_lyrics(path: Path) -> tuple[LyricCandidate, ...]:
    candidates = []
    with path.open("rb") as stream:
        audio = mutagen.File(stream, filename="content", options=list(FORMAT_TYPES))
        tags = audio.tags if audio else None
        if tags is None:
            return ()
        if hasattr(tags, "getall"):
            for frame in tags.getall("USLT"):
                if frame.text.strip():
                    candidates.append(
                        LyricCandidate(
                            "embedded",
                            frame.HashKey,
                            plain_text=frame.text,
                            source=f"Letra embutida ({frame.lang})",
                        )
                    )
            for frame in tags.getall("SYLT"):
                if frame.format == 2 and frame.text:
                    synced = "\n".join(
                        f"[{int(ms) // 60000:02d}:{(int(ms) % 60000) / 1000:05.2f}]{text}"
                        for text, ms in frame.text
                    )
                    candidates.append(
                        LyricCandidate(
                            "embedded",
                            frame.HashKey,
                            synced_text=synced,
                            source="SYLT embutida",
                        )
                    )
        else:
            keys = (
                ("\xa9lyr", "----:com.apple.iTunes:SYNCEDLYRICS")
                if isinstance(audio, MP4)
                else (
                    "lyrics",
                    "unsyncedlyrics",
                    "syncedlyrics",
                    "WM/Lyrics",
                )
            )
            for key in keys:
                values = tags.get(key, [])
                if not isinstance(values, (list, tuple)):
                    values = [values]
                for index, value in enumerate(values):
                    text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
                    if text.strip():
                        is_synced = bool(TIMESTAMP.search(text))
                        candidates.append(
                            LyricCandidate(
                                "embedded",
                                f"{key}:{index}",
                                plain_text=None if is_synced else text,
                                synced_text=text if is_synced else None,
                                source="Letra embutida",
                            )
                        )
    return tuple(candidates)


def local_lyric(text: str, *, synced: bool = False, source: str = "Texto colado") -> LyricCandidate:
    if not text.strip() or len(text.encode("utf-8")) > MAX_LYRIC_BYTES or "\x00" in text:
        raise ValueError("Informe uma letra válida de até 2 MB.")
    if synced and not TIMESTAMP.search(text):
        raise ValueError("O arquivo LRC não contém timestamps válidos.")
    return LyricCandidate(
        "local",
        digest([source, text]),
        plain_text=None if synced else text,
        synced_text=text if synced else None,
        source=source,
    )


def import_lyric(path: Path) -> LyricCandidate:
    if path.suffix.lower() not in (".txt", ".lrc"):
        raise ValueError("Selecione um arquivo TXT ou LRC.")
    with path.open("rb") as stream:
        data = stream.read(MAX_LYRIC_BYTES + 1)
    if len(data) > MAX_LYRIC_BYTES:
        raise ValueError("A letra excede o limite de 2 MB.")
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeError:
        raise ValueError(
            "Salve o arquivo como UTF-8 ou UTF-16 com BOM e importe novamente."
        ) from None
    return local_lyric(text, synced=path.suffix.lower() == ".lrc", source=str(path))


def lyric_report_from_data(data) -> LyricReport:
    data = dict(data)
    results = []
    for result in data["results"]:
        result = dict(result)
        result["status"] = Status(result["status"])
        result["candidates"] = tuple(LyricCandidate(**c) for c in result["candidates"])
        result["releases"] = ()
        results.append(ProviderResult(**result))
    data["results"] = tuple(results)
    data["existing"] = tuple(LyricCandidate(**c) for c in data["existing"])
    data["assessments"] = tuple(
        LyricAssessment(
            a["key"],
            a["eligible"],
            tuple(a["reasons"]),
        )
        for a in data["assessments"]
    )
    data["reasons"] = tuple(data["reasons"])
    data["status"] = LyricStatus(data["status"])
    return LyricReport(**data)


class LyricsService:
    def __init__(self, transport: Transport, cache: ProviderCache, stop=None):
        self.transport, self.cache = transport, cache
        self.stop = stop or threading.Event()

    def query(
        self,
        record,
        artist,
        title,
        recording_context="",
        options=None,
        local=None,
        *,
        read_only=False,
    ):
        options = options or LyricOptions()
        if local is None and not read_only and not (options.lrclib or options.lyrics_ovh):
            raise ValueError("Selecione pelo menos uma fonte de letras.")
        if local is None and not read_only and (not artist.strip() or not title.strip()):
            raise ValueError("Informe artista e título na revisão antes de buscar letras.")
        path = Path(record.path)
        info = path.stat()
        if is_link(path) or (info.st_size, info.st_mtime_ns) != (record.size, record.mtime_ns):
            raise ValueError("O arquivo mudou. Faça uma nova varredura antes de buscar letras.")
        source_hash = file_digest(path, self.stop)
        existing = embedded_lyrics(path)
        results = []
        if read_only:
            pass
        elif local is not None:
            results.append(
                ProviderResult("local", Status.OK, "Letra importada pelo usuário.", (local,))
            )
        else:
            for provider in (LRCLib(self.transport), LyricsOVH(self.transport)):
                if provider.name == "lrclib" and not options.lrclib:
                    continue
                if provider.name == "lyrics.ovh" and not options.lyrics_ovh:
                    continue
                check_cancelled(self.stop)
                key = cache_key(provider.name, "lyrics-v1", artist, title, record.duration)
                result = None if options.refresh else self.cache.get(key, provider.name)
                if result is None:
                    result = provider.search(artist, title)
                    self.cache.put(key, result)
                results.append(result)
                status, _, _, _ = resolve_lyrics(results, artist, title, record.duration)
                if options.mode == "quick" and status in (
                    LyricStatus.FOUND,
                    LyricStatus.INSTRUMENTAL,
                ):
                    break
        status, assessments, reasons, recommended = resolve_lyrics(
            results,
            artist,
            title,
            record.duration,
        )
        if read_only:
            status = LyricStatus.FOUND if existing else LyricStatus.ABSENT
            reasons = ("Letras embutidas lidas sem consulta online.",)
        final = path.stat()
        if (
            is_link(path)
            or (final.st_size, final.st_mtime_ns) != (record.size, record.mtime_ns)
            or (file_digest(path, self.stop) != source_hash)
        ):
            status, recommended = LyricStatus.CHANGED, None
            reasons = ("O arquivo mudou durante a consulta; refaça a varredura.",)
        return LyricReport(
            record.id,
            record.path,
            record_key(record),
            recording_context,
            artist.strip(),
            title.strip(),
            status,
            tuple(results),
            existing,
            assessments,
            reasons,
            recommended,
            source_hash,
        )
