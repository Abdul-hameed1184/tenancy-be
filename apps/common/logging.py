"""
Logging building blocks: request ids, secret redaction and a JSON formatter.

Redaction runs as a handler-level filter, so it applies to every record from any library,
however carelessly a value was logged. Sensitive keys are dropped from structured `extra`
fields and from dict arguments, and "Bearer <token>" is masked in message text.
"""

import contextvars
import json
import logging
import re
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

SENSITIVE = re.compile(r"pass(word)?|token|secret|authori[sz]ation|ticket|cookie|api[_-]?key", re.I)
BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.I)
REDACTED = "[REDACTED]"

# Attributes every LogRecord has; anything else came from `extra=` and is structured data.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "request_id",
}


def _scrub(value):
    if isinstance(value, dict):
        return {k: (REDACTED if SENSITIVE.search(str(k)) else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_scrub(v) for v in value)
    if isinstance(value, str):
        return BEARER.sub(r"\1" + REDACTED, value)
    return value


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = BEARER.sub(r"\1" + REDACTED, record.msg)
        if isinstance(record.args, dict):
            record.args = _scrub(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_scrub(a) for a in record.args)
        for key in list(record.__dict__):
            if key in _STANDARD_ATTRS:
                continue
            if SENSITIVE.search(key):
                record.__dict__[key] = REDACTED
            else:
                record.__dict__[key] = _scrub(record.__dict__[key])
        return True


class JSONFormatter(logging.Formatter):
    """One JSON object per line, for log shippers (Loki, CloudWatch, Datadog...)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
