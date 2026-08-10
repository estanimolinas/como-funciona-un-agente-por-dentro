from unittest.mock import MagicMock, patch

import pytest
import voyageai.error

from coderag_mcp.embeddings.voyage import embed_batch


def test_embed_batch_calls_voyage_with_code3_model():
    fake_result = MagicMock(embeddings=[[0.1, 0.2], [0.3, 0.4]])
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.return_value = fake_result

        result = embed_batch(["def a(): pass", "def b(): pass"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]
        mock_client_cls.return_value.embed.assert_called_once_with(
            ["def a(): pass", "def b(): pass"],
            model="voyage-code-3",
            input_type="document",
        )


def test_embed_batch_uses_query_input_type_when_requested():
    fake_result = MagicMock(embeddings=[[0.1, 0.2]])
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.return_value = fake_result

        embed_batch(["how does auth work?"], input_type="query")

        mock_client_cls.return_value.embed.assert_called_once_with(
            ["how does auth work?"],
            model="voyage-code-3",
            input_type="query",
        )


def test_embed_batch_reuses_client_across_calls():
    fake_result = MagicMock(embeddings=[[0.1, 0.2]])
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.return_value = fake_result

        embed_batch(["a"], input_type="document")
        embed_batch(["b"], input_type="document")

        mock_client_cls.assert_called_once()


@pytest.mark.parametrize(
    "error_cls",
    [
        voyageai.error.APIConnectionError,
        voyageai.error.RateLimitError,
        voyageai.error.ServerError,
        voyageai.error.ServiceUnavailableError,
        voyageai.error.Timeout,
        voyageai.error.TryAgain,
    ],
)
def test_embed_batch_retries_transient_errors_and_succeeds(error_cls, monkeypatch):
    fake_result = MagicMock(embeddings=[[0.1, 0.2]])
    call_count = {"n": 0}

    def flaky_embed(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise error_cls(message="transient failure")
        return fake_result

    monkeypatch.setattr("coderag_mcp.embeddings.voyage.time.sleep", lambda _: None)
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.side_effect = flaky_embed

        result = embed_batch(["a"], input_type="document")

    assert result == [[0.1, 0.2]]
    assert call_count["n"] == 3


@pytest.mark.parametrize(
    "error_cls",
    [
        voyageai.error.AuthenticationError,
        voyageai.error.InvalidRequestError,
        voyageai.error.MalformedRequestError,
        voyageai.error.APIError,
    ],
)
def test_embed_batch_does_not_retry_non_transient_errors(error_cls, monkeypatch):
    call_count = {"n": 0}

    def always_fails(*args, **kwargs):
        call_count["n"] += 1
        raise error_cls(message="not retryable")

    monkeypatch.setattr("coderag_mcp.embeddings.voyage.time.sleep", lambda _: None)
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.side_effect = always_fails

        with pytest.raises(error_cls):
            embed_batch(["a"], input_type="document")

    assert call_count["n"] == 1


def test_embed_batch_raises_after_exhausting_all_retries(monkeypatch):
    call_count = {"n": 0}

    def always_times_out(*args, **kwargs):
        call_count["n"] += 1
        raise voyageai.error.Timeout(message="still timing out")

    monkeypatch.setattr("coderag_mcp.embeddings.voyage.time.sleep", lambda _: None)
    with patch("coderag_mcp.embeddings.voyage.voyageai.Client") as mock_client_cls:
        mock_client_cls.return_value.embed.side_effect = always_times_out

        with pytest.raises(voyageai.error.Timeout):
            embed_batch(["a"], input_type="document")

    assert call_count["n"] == 3
