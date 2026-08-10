from unittest.mock import MagicMock, patch

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
