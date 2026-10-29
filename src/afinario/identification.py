"""Análise de áudio + provedores + metadados + decisão por arquivo, sem escrita musical."""

import hashlib
import importlib.util
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from afinario.audd import AudD, AudDBudget
from afinario.audio import audio_duration, extract_sample, fingerprint
from afinario.cancellation import AnalysisCancelled, check_cancelled
from afinario.config import Settings
from afinario.domain import ProviderResult, RecordingCandidate, ReleaseCandidate, Status
from afinario.inventory import InventoryRecord, is_link
from afinario.metadata import MusicBrainz
from afinario.probe import shazam_sample
from afinario.provider_cache import ProviderCache, cache_key
from afinario.providers import AcoustID
from afinario.resolver import Decision, DecisionStatus, normalize, resolve
from afinario.transport import ProviderError, Transport


@dataclass(frozen=True)
class RecognitionOptions:
    acoustid: bool = True
    shazamio: bool = False
    musicbrainz: bool = True
    refresh: bool = False
    audd: bool = False


@dataclass(frozen=True)
class IdentificationReport:
    file_id: str
    path: str
    decision: Decision
    results: tuple[ProviderResult, ...] = ()
    source_sha256: str | None = None
    duration: float | None = None

    def summary(self) -> dict:
        return {
            "file_id": self.file_id,
            "path": self.path,
            "decision": asdict(self.decision),
            "results": [result.summary() for result in self.results],
            "source_sha256": self.source_sha256,
            "duration": self.duration,
        }


def report_from_data(data):
    data = dict(data)
    decision = dict(data["decision"])
    decision["status"] = DecisionStatus(decision["status"])
    for key in ("reasons", "proposed_fields"):
        decision[key] = tuple(decision[key])
    results = []
    for item in data["results"]:
        item = dict(item)
        item["status"] = Status(item["status"])
        candidates = []
        for value in item["candidates"]:
            value = dict(value)
            for key in ("title_aliases", "artist_aliases", "isrcs"):
                value[key] = tuple(value.get(key, ()))
            candidates.append(RecordingCandidate(**value))
        item["candidates"] = tuple(candidates)
        item["releases"] = tuple(ReleaseCandidate(**v) for v in item["releases"])
        results.append(ProviderResult(**item))
    return IdentificationReport(
        **{**data, "decision": Decision(**decision), "results": tuple(results)}
    )


def compare_history(report: IdentificationReport, history: list[IdentificationReport]):
    """A changed remote answer is evidence to review, never a silent replacement."""
    decision = report.decision
    if not report.source_sha256 or not decision.artist or not decision.title:
        return report
    previous = {}
    for old in history:
        value = old.decision
        if old.source_sha256 != report.source_sha256 or not value.artist or not value.title:
            continue
        # Changes in typography/accents alone do not create a new identity.
        same_names = (normalize(value.artist), normalize(value.title)) == (
            normalize(decision.artist),
            normalize(decision.title),
        )
        same_recording = not (
            value.recording_id
            and decision.recording_id
            and value.recording_id != decision.recording_id
        )
        if same_names and same_recording:
            continue
        key = (normalize(value.artist), normalize(value.title), value.recording_id)
        previous[key] = RecordingCandidate(
            "previous", None, value.title, value.artist, recording_id=value.recording_id
        )
    if not previous:
        return report
    reasons = (
        "O mesmo áudio recebeu identificações diferentes entre consultas. "
        "Ouça a faixa e escolha a identificação em Revisar e aprovar.",
        *(f"Anterior: {item.artist} — {item.title}" for item in previous.values()),
        f"Nesta consulta: {decision.artist} — {decision.title}",
    )
    return replace(
        report,
        decision=Decision(DecisionStatus.CONFLICT, reasons=reasons),
        results=(
            *report.results,
            ProviderResult(
                "previous",
                Status.OK,
                "Propostas anteriores para este áudio; não contam como confirmação independente.",
                tuple(previous.values()),
            ),
        ),
    )


def file_digest(path: Path, stop: threading.Event) -> str:
    check_cancelled(stop)
    if is_link(path):
        raise OSError("Link não permitido")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancelled(stop)
            digest.update(chunk)
    return digest.hexdigest()


class IdentificationService:
    def __init__(
        self,
        settings: Settings,
        transport: Transport,
        cache: ProviderCache,
        stop: threading.Event | None = None,
        audd_budget: AudDBudget | None = None,
    ):
        self.settings, self.transport, self.cache = settings, transport, cache
        self.stop = stop or threading.Event()
        self.audd_budget = audd_budget if audd_budget is not None else AudDBudget(0)

    def _cached(
        self, provider: str, key: str, query: Callable[[], ProviderResult], *, refresh: bool = False
    ) -> ProviderResult:
        lock = self.cache.query_lock(key)
        while not lock.acquire(timeout=0.1):
            check_cancelled(self.stop)
        try:
            check_cancelled(self.stop)
            result = None if refresh else self.cache.get(key, provider)
            if result is None:
                try:
                    result = query()
                except AnalysisCancelled:
                    raise
                except ProviderError as exc:
                    result = ProviderResult(provider, exc.status, str(exc), attempts=exc.attempts)
                except Exception:
                    result = ProviderResult(
                        provider,
                        Status.UNAVAILABLE,
                        "Falha ao consultar este serviço. As outras fontes continuam disponíveis.",
                    )
                check_cancelled(self.stop)
                self.cache.put(key, result)
        finally:
            lock.release()
        self.transport.record_failure(provider, result.status, result.retry_after_seconds)
        if not result.cached and result.status in (Status.OK, Status.NOT_FOUND):
            self.transport.record_success(provider)
        return result

    def _shazam(self, path: Path, duration: float | None) -> ProviderResult:
        if importlib.util.find_spec("shazamio") is None:
            return ProviderResult(
                "shazamio", Status.BLOCKED, "Instale o extra recognition para usar ShazamIO."
            )
        try:
            if duration is None:
                duration = audio_duration(path, self.settings.ffprobe, cancelled=self.stop)
            offsets = list(
                dict.fromkeys([min(30, max(0, duration - 12)), max(0, duration / 2 - 6)])
            )
            with tempfile.TemporaryDirectory(prefix="afinario-identify-") as temporary:
                for index, offset in enumerate(offsets):
                    check_cancelled(self.stop)
                    sample = Path(temporary) / f"sample-{index}.wav"
                    extract_sample(path, sample, offset, self.settings.ffmpeg, cancelled=self.stop)
                    with self.transport.provider_slot("shazamio"):
                        result = shazam_sample(sample, self.settings.timeout_seconds, self.stop)
                        self.transport.record_failure(
                            "shazamio", result.status, result.retry_after_seconds
                        )
                    if result.status != Status.NOT_FOUND:
                        return replace(result, attempts=index + 1)
                return replace(result, attempts=len(offsets))
        except ProviderError as exc:
            return ProviderResult(
                "shazamio",
                exc.status,
                str(exc),
                attempts=exc.attempts,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return ProviderResult("shazamio", Status.AUDIO, "Não foi possível preparar a amostra.")

    def _audd(self, path: Path, duration: float | None) -> ProviderResult:
        if not self.settings.audd_token:
            return ProviderResult(
                "audd", Status.BLOCKED, "Configure o token AudD em Serviços e ferramentas."
            )
        if self.audd_budget.used >= self.audd_budget.limit:
            return ProviderResult("audd", Status.BLOCKED, "Limite AudD desta execução atingido.")
        try:
            check_cancelled(self.stop)
            if duration is None:
                duration = audio_duration(path, self.settings.ffprobe, cancelled=self.stop)
            with tempfile.TemporaryDirectory(prefix="afinario-audd-") as temporary:
                sample = Path(temporary) / "sample.wav"
                extract_sample(
                    path,
                    sample,
                    min(30, max(0, duration - 12)),
                    self.settings.ffmpeg,
                    cancelled=self.stop,
                )
                return AudD(self.transport, self.settings.audd_token, self.audd_budget).recognize(
                    sample.read_bytes()
                )
        except ProviderError as exc:
            return ProviderResult("audd", exc.status, str(exc))
        except (OSError, ValueError, TypeError, KeyError):
            return ProviderResult("audd", Status.AUDIO, "Não foi possível preparar a amostra AudD.")

    def _acoustid_and_metadata(
        self,
        path: Path,
        source_hash: str,
        duration: float | None,
        options: RecognitionOptions,
        stage: Callable[[str], None],
    ):
        results = []
        check_cancelled(self.stop)
        stage("Consultando AcoustID")
        key = cache_key("acoustid", source_hash)
        cached = None if options.refresh else self.cache.get(key, "acoustid")
        if cached is not None:
            results.append(cached)
        elif not self.settings.acoustid_key:
            results.append(
                ProviderResult(
                    "acoustid", Status.BLOCKED, "Configure a chave de aplicação AcoustID."
                )
            )
        else:
            try:
                value, total = fingerprint(path, self.settings.fpcalc, cancelled=self.stop)
                duration = total
                results.append(
                    self._cached(
                        "acoustid",
                        key,
                        lambda: AcoustID(self.transport, self.settings.acoustid_key).lookup(
                            value, total
                        ),
                        refresh=options.refresh,
                    )
                )
            except ProviderError as exc:
                results.append(ProviderResult("acoustid", exc.status, str(exc)))
            except (OSError, ValueError, TypeError, KeyError):
                results.append(
                    ProviderResult("acoustid", Status.AUDIO, "Fingerprint local inválido.")
                )
        if options.musicbrainz:
            candidates = [
                item
                for result in results
                for item in result.candidates
                if isinstance(item, RecordingCandidate)
            ]
            candidates.sort(key=lambda item: item.score or 0, reverse=True)
            ids = list(
                dict.fromkeys(item.recording_id for item in candidates if item.recording_id)
            )[:3]
            for recording_id in ids:
                check_cancelled(self.stop)
                stage("Consultando metadados MusicBrainz")
                results.append(
                    self._cached(
                        "musicbrainz",
                        cache_key("musicbrainz", recording_id),
                        lambda recording_id=recording_id: MusicBrainz(self.transport).recording(
                            recording_id
                        ),
                        refresh=options.refresh,
                    )
                )
        return results, duration

    def identify(
        self,
        record: InventoryRecord,
        options: RecognitionOptions,
        stage: Callable[[str], None] = lambda _: None,
    ) -> IdentificationReport:
        if not (options.acoustid or options.shazamio or options.audd):
            raise ValueError("Selecione pelo menos um reconhecedor.")
        check_cancelled(self.stop)
        path = Path(record.path)
        results: list[ProviderResult] = []
        duration = record.duration
        source_hash = None
        try:
            info = path.stat()
            if (
                record.status == "error"
                or is_link(path)
                or (info.st_size, info.st_mtime_ns) != (record.size, record.mtime_ns)
            ):
                return IdentificationReport(
                    record.id,
                    record.path,
                    Decision(
                        DecisionStatus.CHANGED,
                        reasons=("O arquivo mudou ou precisa de nova varredura.",),
                    ),
                )
            stage("Verificando arquivo")
            source_hash = file_digest(path, self.stop)
            # Independent audio recognizers overlap. MusicBrainz follows AcoustID
            # as soon as MBIDs arrive, without waiting for ShazamIO.
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="afinario-provider") as pool:
                acoustid_future = (
                    pool.submit(
                        self._acoustid_and_metadata, path, source_hash, duration, options, stage
                    )
                    if options.acoustid
                    else None
                )
                shazam_future = (
                    pool.submit(
                        self._cached,
                        "shazamio",
                        cache_key("shazamio", source_hash),
                        lambda: self._shazam(path, record.duration),
                        refresh=options.refresh,
                    )
                    if options.shazamio
                    else None
                )
                audd_future = (
                    pool.submit(
                        self._cached,
                        "audd",
                        cache_key("audd", "standard-12s-v1", source_hash),
                        lambda: self._audd(path, record.duration),
                        refresh=options.refresh,
                    )
                    if options.audd
                    else None
                )
                audio_results = []
                metadata_results = []
                if acoustid_future is not None:
                    branch, duration = acoustid_future.result()
                    audio_results.extend(item for item in branch if item.provider == "acoustid")
                    metadata_results.extend(item for item in branch if item.provider != "acoustid")
                if shazam_future is not None:
                    stage("Aguardando resultado ShazamIO (experimental)")
                    audio_results.append(shazam_future.result())
                if audd_future is not None:
                    stage("Aguardando resultado AudD")
                    audio_results.append(audd_future.result())
                results = [*audio_results, *metadata_results]
            check_cancelled(self.stop)
            stage("Comparando fontes e verificando integridade")
            final = path.stat()
            if (final.st_size, final.st_mtime_ns) != (record.size, record.mtime_ns) or (
                file_digest(path, self.stop) != source_hash
            ):
                decision = Decision(
                    DecisionStatus.CHANGED,
                    reasons=("O arquivo mudou durante a análise; refaça a varredura.",),
                )
            else:
                decision = resolve(tuple(results), duration)
            return IdentificationReport(
                record.id, record.path, decision, tuple(results), source_hash, duration
            )
        except AnalysisCancelled:
            raise
        except OSError:
            return IdentificationReport(
                record.id,
                record.path,
                Decision(
                    DecisionStatus.PENDING,
                    reasons=("O arquivo ficou inacessível durante a análise.",),
                ),
                tuple(results),
                source_hash,
                duration,
            )
