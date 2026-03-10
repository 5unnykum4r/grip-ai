"""Tests for the embedding service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from grip.memory.embeddings import EmbeddingService


@pytest.fixture
def embed_svc() -> EmbeddingService:
    return EmbeddingService(model="text-embedding-3-small", dimensions=8)


class TestEmbeddingService:
    @pytest.mark.asyncio
    async def test_embed_returns_numpy_array(self, embed_svc: EmbeddingService):
        fake_embedding = [0.1] * 8
        mock_response = AsyncMock()
        mock_response.data = [AsyncMock(embedding=fake_embedding)]

        with patch("grip.memory.embeddings.aembedding", return_value=mock_response):
            result = await embed_svc.embed("hello world")
            assert isinstance(result, np.ndarray)
            assert result.dtype == np.float32
            assert len(result) == 8

    @pytest.mark.asyncio
    async def test_embed_batch_returns_list_of_arrays(self, embed_svc: EmbeddingService):
        fake_data = [AsyncMock(embedding=[0.1] * 8), AsyncMock(embedding=[0.2] * 8)]
        mock_response = AsyncMock()
        mock_response.data = fake_data

        with patch("grip.memory.embeddings.aembedding", return_value=mock_response):
            results = await embed_svc.embed_batch(["hello", "world"])
            assert len(results) == 2
            assert all(isinstance(r, np.ndarray) for r in results)

    @pytest.mark.asyncio
    async def test_embed_normalizes_to_unit_vector(self, embed_svc: EmbeddingService):
        fake_embedding = [3.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        mock_response = AsyncMock()
        mock_response.data = [AsyncMock(embedding=fake_embedding)]

        with patch("grip.memory.embeddings.aembedding", return_value=mock_response):
            result = await embed_svc.embed("test")
            norm = np.linalg.norm(result)
            assert abs(norm - 1.0) < 1e-5

    @pytest.mark.asyncio
    async def test_embed_returns_none_on_failure(self, embed_svc: EmbeddingService):
        with patch("grip.memory.embeddings.aembedding", side_effect=Exception("API down")):
            result = await embed_svc.embed("test")
            assert result is None
