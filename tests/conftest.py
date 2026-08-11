"""Shared pytest fixtures."""
from __future__ import annotations

import os

# Tests never make a real Voyage API call (voyageai.Client is always mocked),
# so they don't need a real key - but api.main.create_app() now calls
# validate_settings(), which raises if VOYAGE_API_KEY is unset. setdefault()
# only takes effect if the var isn't already a real exported shell env var,
# so a developer's real key (if actually exported, not just in .env) still wins.
# Note: pydantic-settings ranks real environment variables above .env file
# contents, so a real key that only lives in .env (which is exactly what the
# README's quickstart tells every user to set up) is silently shadowed by this
# dummy value - a future contributor adding a real-API integration test needs
# to export VOYAGE_API_KEY in their shell, not just set it in .env, or this
# fixture will quietly override it.
os.environ.setdefault("VOYAGE_API_KEY", "test-voyage-key-not-a-real-key")

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)
