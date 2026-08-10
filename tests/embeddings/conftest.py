import pytest

from coderag_mcp.embeddings import voyage


@pytest.fixture(autouse=True)
def _reset_voyage_client():
    voyage._client = None
    yield
    voyage._client = None
