"""Processo isolado para limitar inclusive travamentos na extensão nativa do ShazamIO."""

import asyncio
import json
import sys

from afinario.config import Settings
from afinario.domain import Status
from afinario.transport import ProviderError, Transport


async def recognize(path: str) -> dict:
    from shazamio import Shazam
    from shazamio.interfaces.client import HTTPClientInterface

    # Do not inherit ShazamIO's default twenty HTTP attempts. Reuse our bounded,
    # categorized transport; the parent process enforces a total wall-clock limit.
    transport = Transport(Settings(attempts=1))

    class ProbeHTTPClient(HTTPClientInterface):
        async def request(self, method: str, url: str, **kwargs):
            kwargs.pop("proxy", None)
            data, _ = await asyncio.to_thread(transport.json, "shazamio", method, url, **kwargs)
            return data

        async def request_text(self, url: str, *, content_type: str, **kwargs):
            raise ProviderError(
                Status.INVALID, "Consulta textual não faz parte da prova de reconhecimento."
            )

    try:
        async with Shazam(http_client=ProbeHTTPClient()) as client:
            return await client.recognize(path)
    finally:
        transport.close()


def main() -> int:
    try:
        data = asyncio.run(recognize(sys.argv[1]))
        if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
            result = {"status": "invalid_response"}
        elif not data["matches"]:
            result = {"status": "not_found"}
        else:
            track = data.get("track")
            if not isinstance(track, dict) or not track.get("key"):
                result = {"status": "invalid_response"}
            else:
                result = {
                    "status": "ok",
                    "key": str(track["key"]),
                    "title": track.get("title"),
                    "artist": track.get("subtitle"),
                    "isrcs": [track["isrc"].strip().upper()]
                    if isinstance(track.get("isrc"), str) and track["isrc"].strip()
                    else [],
                }
    except ImportError:
        result = {"status": "blocked"}
    except ProviderError as exc:
        result = {"status": exc.status.value, "retry_after_seconds": exc.retry_after_seconds}
    except Exception as exc:
        # Third-party exception messages may embed URLs, headers or credentials.
        code = getattr(exc, "status", None)
        status = "unavailable"
        if code in (401, 403):
            status = "authentication_error"
        elif code == 429:
            status = "rate_limited"
        elif isinstance(exc, (OSError, TimeoutError)):
            status = "network_error"
        result = {"status": status}
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
