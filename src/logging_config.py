from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bot\d{5,}:[A-Za-z0-9_-]{20,})"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~-]+"),
    re.compile(r"(?i)(https?://[^\s]+(?:sub|subscription|token)[^\s]+)"),
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub("[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
