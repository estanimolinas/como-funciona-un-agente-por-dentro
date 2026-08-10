from unittest.mock import patch

from fastapi.testclient import TestClient

from coderag_mcp.api.main import app
from coderag_mcp.indexing.models import InvalidRepoURLError


def test_ask_returns_answer_on_success(tmp_path):
    with (
        patch("coderag_mcp.api.ask_route.get_settings") as mock_settings,
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch("coderag_mcp.api.ask_route.run_ask", return_value="the answer"),
    ):
        mock_settings.return_value.sqlite_db_path = str(tmp_path / "test.db")

        client = TestClient(app)
        response = client.post(
            "/ask",
            json={"repo_url": "https://github.com/a/b", "question": "what does this do?"},
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "the answer"}


def test_ask_maps_indexing_error_to_400(tmp_path):
    with (
        patch("coderag_mcp.api.ask_route.get_settings") as mock_settings,
        patch(
            "coderag_mcp.api.ask_route.index_and_store_repo",
            side_effect=InvalidRepoURLError("bad host"),
        ),
    ):
        mock_settings.return_value.sqlite_db_path = str(tmp_path / "test.db")

        client = TestClient(app)
        response = client.post(
            "/ask", json={"repo_url": "https://evil.example/a/b", "question": "?"}
        )

    assert response.status_code == 400
    assert "bad host" in response.json()["detail"]


def test_ask_maps_orchestrator_failure_to_502(tmp_path):
    with (
        patch("coderag_mcp.api.ask_route.get_settings") as mock_settings,
        patch("coderag_mcp.api.ask_route.index_and_store_repo", return_value=1),
        patch(
            "coderag_mcp.api.ask_route.run_ask", side_effect=RuntimeError("sdk exploded")
        ),
    ):
        mock_settings.return_value.sqlite_db_path = str(tmp_path / "test.db")

        client = TestClient(app)
        response = client.post(
            "/ask", json={"repo_url": "https://github.com/a/b", "question": "?"}
        )

    assert response.status_code == 502
