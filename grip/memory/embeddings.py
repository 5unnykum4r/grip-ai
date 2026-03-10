"""Async embedding generation via litellm.

Uses litellm.aembedding() which supports OpenAI, Voyage, Ollama, and
any OpenAI-compatible embedding endpoint.
"""

from __future__ import annotations

import numpy as np
from litellm import aembedding
from loguru import logger


class EmbeddingService:
    """Generates normalized text embeddings using litellm's unified API."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        api_key: str = "",
        api_base: str = "",
    ) -> None:
        self._model = model
        self._dims = dimensions
        self._api_key = api_key
        self._api_base = api_base

    def _call_kwargs(self) -> dict:
        """Build extra kwargs (api_key, api_base) for litellm.aembedding()."""
        kwargs: dict = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        return kwargs

    @staticmethod
    def _extract_vector(item) -> list[float]:
        """Extract the raw embedding list from a response item (dict or object)."""
        if isinstance(item, dict):
            return item["embedding"]
        return item.embedding

    async def embed(self, text: str) -> np.ndarray | None:
        """Generate a normalized embedding for a single text. Returns None on failure."""
        try:
            response = await aembedding(model=self._model, input=[text], **self._call_kwargs())
            vec = np.array(self._extract_vector(response.data[0]), dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            return vec
        except Exception as exc:
            logger.warning("Embedding failed for text ({}... chars): {}", len(text), exc)
            return None

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray | None]:
        """Generate embeddings for multiple texts in a single API call."""
        if not texts:
            return []
        try:
            response = await aembedding(model=self._model, input=texts, **self._call_kwargs())
            results: list[np.ndarray | None] = []
            for item in response.data:
                vec = np.array(self._extract_vector(item), dtype=np.float32)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec /= norm
                results.append(vec)
            return results
        except Exception as exc:
            logger.warning("Batch embedding failed ({} texts): {}", len(texts), exc)
            return [None] * len(texts)
