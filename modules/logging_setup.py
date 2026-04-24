"""Structured logging setup.

Two modes:
  * "text"  — human-friendly (default, matches v1/v2 output)
  * "json"  — one JSON object per line for log aggregators (Datadog, Loki, ELK)

Toggle via LOG_FORMAT=json in .env, or pass format= to configure().
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    """Emit each log record as a compact, single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key in ("pathname", "lineno", "funcName"):
            payload[key] = getattr(record, key, None)
        # Merge any extra fields attached via `logger.info(..., extra={...})`.
        standard_keys = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys())
        standard_keys.update({"message", "asctime"})
        for key, value in record.__dict__.items():
            if key not in standard_keys and key not in payload:
                try:
                    json.dumps(value)
                    payload[key] = value
                except TypeError:
                    payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def configure(verbose: bool = False, fmt: str | None = None) -> None:
    """Configure root logger. Safe to call multiple times."""
    fmt = (fmt or os.getenv("LOG_FORMAT", "text")).lower()

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Quiet down chatty third parties.
    for noisy in ("httpx", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
