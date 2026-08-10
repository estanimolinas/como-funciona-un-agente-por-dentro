"""Tests for coderag_mcp.config.validate_settings."""
from __future__ import annotations

import pytest

from coderag_mcp.config import Settings, validate_settings


def test_validate_settings_raises_when_voyage_api_key_missing():
    settings = Settings(voyage_api_key="")
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        validate_settings(settings)


def test_validate_settings_passes_when_voyage_api_key_set():
    settings = Settings(voyage_api_key="test-key")
    validate_settings(settings)  # must not raise


def test_validate_settings_does_not_require_coderag_api_key():
    """CODERAG_API_KEY empty/unset is a supported dev-mode value, not a
    misconfiguration - validate_settings must not raise on it being empty."""
    settings = Settings(voyage_api_key="test-key", api_key="")
    validate_settings(settings)  # must not raise
