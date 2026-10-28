"""AudD standard: uma amostra por arquivo e nenhuma repetição HTTP automática."""

import threading
import time

from afinario.domain import ProviderResult, RecordingCandidate, ReleaseCandidate, Status
from afinario.providers import number, text
from afinario.transport import ProviderError, Transport


class AudDBudget:
    def __init__(self, limit: int = 0):
        if type(limit) is not int or limit < 0:
            raise ValueError("Limite AudD inválido.")
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def reserve(self) -> None:
        with self._lock:
            if self._used >= self.limit:
                raise ProviderError(Status.BLOCKED, "Limite AudD desta execução atingido.")
            # Never refund an uncertain delivery: the server may have processed it.
            self._used += 1


class AudD:
    name = "audd"

    def __init__(self, transport: Transport, token: str, budget: AudDBudget):
        self.transport, self.token, self.budget = transport, token, budget

    def recognize(self, sample: bytes) -> ProviderResult:
        start = time.monotonic()
        attempts = 0
        try:
            data, attempts = self.transport.json(
                self.name,
                "POST",
                "https://api.audd.io/",
                max_attempts=1,
                before_send=self.budget.reserve,
                data={"api_token": self.token},
                files={"file": ("sample.wav", sample, "audio/wav")},
            )
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            if data.get("status") == "error":
                code = str(data.get("error", {}).get("error_code", ""))
                status = Status.AUTH if code in ("900", "901") else Status.INVALID
                if code in ("500", "600", "700"):
                    status = Status.AUDIO
                self.transport.record_failure(self.name, status)
                raise ProviderError(
                    status, "AudD recusou a consulta; confira token e configurações.", attempts
                )
            if data.get("status") != "success" or "result" not in data:
                raise ValueError("Invalid result")
            row = data["result"]
            if row is None:
                return ProviderResult(
                    self.name,
                    Status.NOT_FOUND,
                    "AudD não encontrou correspondência.",
                    attempts=attempts,
                    elapsed_seconds=time.monotonic() - start,
                )
            if (
                not isinstance(row, dict)
                or not text(row.get("artist"))
                or not text(row.get("title"))
            ):
                raise ValueError("Missing identification")
            candidate = RecordingCandidate(
                self.name,
                text(row.get("song_link")),
                row["title"],
                row["artist"],
                score=number(row.get("score")),
                isrcs=(row["isrc"].strip().upper(),) if text(row.get("isrc")) else (),
            )
            releases = (
                (ReleaseCandidate(None, row["album"], text(row.get("release_date"))),)
                if (text(row.get("album")))
                else ()
            )
            return ProviderResult(
                self.name,
                Status.OK,
                "Candidato AudD recebido.",
                (candidate,),
                attempts,
                time.monotonic() - start,
                releases,
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
                "Resposta AudD inválida.",
                attempts=attempts,
                elapsed_seconds=time.monotonic() - start,
            )
