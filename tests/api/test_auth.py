from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.auth import validate_api_key
from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.main import app
from coderag_mcp.config import Settings
from coderag_mcp.store.db import get_connection, init_schema


def _settings(key: str) -> Settings:
    return Settings(api_key=key)


def test_validate_api_key_allows_anything_when_unset():
    with patch("coderag_mcp.api.auth.get_settings", return_value=_settings("")):
        assert validate_api_key(None) is True
        assert validate_api_key("anything") is True


def test_validate_api_key_requires_exact_match_when_set():
    with patch("coderag_mcp.api.auth.get_settings", return_value=_settings("secret123")):
        assert validate_api_key("secret123") is True
        assert validate_api_key("wrong") is False
        assert validate_api_key(None) is False


@pytest.fixture()
def client_with_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "coderag_mcp.api.auth.get_settings", lambda: Settings(api_key="secret123")
    )
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)
    app.dependency_overrides[get_db_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_db_conn]
        conn.close()


def test_ask_rejects_missing_key(client_with_key):
    response = client_with_key.post(
        "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
    )
    assert response.status_code == 401


def test_ask_rejects_wrong_key(client_with_key):
    response = client_with_key.post(
        "/ask",
        json={"repo_url": "https://github.com/a/b", "question": "?"},
        headers={"X-API-Key": "wrong"},
    )
    assert response.status_code == 401


def test_ask_accepts_correct_key(client_with_key):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo_async", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", return_value="the answer"),
    ):
        response = client_with_key.post(
            "/ask",
            json={"repo_url": "https://github.com/a/b", "question": "?"},
            headers={"X-API-Key": "secret123"},
        )
    assert response.status_code == 200
