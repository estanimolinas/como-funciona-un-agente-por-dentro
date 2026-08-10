"""Structured JSON logging, installed once at process startup.

Standard-library `logging` only - no new dependency. `JSONFormatter` emits one
JSON object per log line (timestamp, level, logger name, message, plus any
`extra=` fields the caller passed), which is far easier to grep/parse than
free-text log lines once this project's `except Exception` blocks and
external-API call sites (Voyage, the orchestrator) start actually logging.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

# The set of attributes every LogRecord carries regardless of what was logged -
# used to separate "extra" fields (anything the caller passed via `extra={...}`)
# from LogRecord's own bookkeeping attributes. Confirmed against a real
# LogRecord's __dict__ keys while writing this plan, not guessed.
_STANDARD_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Install JSON-formatted logging on the root logger. Call once, at startup -
    safe to call more than once (e.g. once from api/main.py's create_app() and
    once from mcp_server/server.py's _lifespan in the same process): each call
    clears and reinstalls the same handler, so it's idempotent, not additive."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
