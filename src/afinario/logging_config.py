import logging
import re


class RedactSecrets(logging.Filter):
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[redacted]")
        message = re.sub(
            r"(?i)(client|api_key|api_token|token|authorization)([=:]\s*)[^\s&]+",
            r"\1\2[redacted]",
            message,
        )
        record.msg, record.args = message, ()
        return True


def configure_logging(secret: str | None = None, *extra_secrets: str | None) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactSecrets(tuple(value for value in (secret, *extra_secrets) if value)))
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("afinario")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # HTTP clients may include URLs and credentials in debug logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
