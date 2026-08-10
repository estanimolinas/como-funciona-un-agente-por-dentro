"""Tests for coderag_mcp.logging_config."""
from __future__ import annotations

import json
import logging

from coderag_mcp.logging_config import configure_logging


def test_configure_logging_emits_one_json_object_per_line(capsys):
    configure_logging()
    logger = logging.getLogger("test.logging_config")

    logger.info("hello world", extra={"repo_url": "https://github.com/a/b"})

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logging_config"
    assert payload["repo_url"] == "https://github.com/a/b"
    assert "timestamp" in payload


def test_configure_logging_includes_exception_traceback(capsys):
    configure_logging()
    logger = logging.getLogger("test.logging_config.exc")

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("something failed")

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert "ValueError: boom" in payload["exception"]
