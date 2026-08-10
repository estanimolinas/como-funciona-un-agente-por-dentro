from coderag_mcp.store.db import get_connection, init_schema
from coderag_mcp.store.repos import create_repo, get_repo_id_by_url


def test_create_and_lookup_repo(tmp_path):
    conn = get_connection(str(tmp_path / "test.db"))
    init_schema(conn, dim=4)

    assert get_repo_id_by_url(conn, "https://github.com/a/b") is None

    repo_id = create_repo(conn, "https://github.com/a/b")
    assert get_repo_id_by_url(conn, "https://github.com/a/b") == repo_id
