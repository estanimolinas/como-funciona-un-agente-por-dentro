from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from coderag_mcp.api.deps import get_db_conn
from coderag_mcp.api.main import app
from coderag_mcp.indexing.models import CloneTimeoutError, InvalidRepoURLError
from coderag_mcp.store.db import get_connection, init_schema


@pytest.fixture()
def client(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn)
    app.dependency_overrides[get_db_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        del app.dependency_overrides[get_db_conn]
        conn.close()


def test_ask_returns_answer_on_success(client):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo_async", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", return_value="the answer"),
    ):
        response = client.post(
            "/ask",
            json={"repo_url": "https://github.com/a/b", "question": "what does this do?"},
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "the answer"}


def test_ask_maps_indexing_error_to_400(client):
    with patch(
        "coderag_mcp.api.ask_route.index_and_store_repo_async",
        side_effect=InvalidRepoURLError("bad host"),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://evil.example/a/b", "question": "?"}
        )

    assert response.status_code == 400
    assert "bad host" in response.json()["detail"]


def test_ask_maps_non_indexing_failure_during_indexing_to_502(client):
    with patch(
        "coderag_mcp.api.ask_route.index_and_store_repo_async",
        side_effect=RuntimeError("voyage api key invalid"),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not index the repository."


def test_ask_maps_indexing_error_from_run_ask_to_400(client):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo_async", return_value=1),
        patch(
            "coderag_mcp.api.ask_route.run_ask",
            side_effect=CloneTimeoutError("clone took too long"),
        ),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 400
    assert "clone took too long" in response.json()["detail"]


def test_ask_maps_orchestrator_failure_to_502(client):
    with (
        patch("coderag_mcp.api.ask_route.index_and_store_repo_async", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", side_effect=RuntimeError("sdk exploded")),
    ):
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 502
