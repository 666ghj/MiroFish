"""
Embedding client wrapper for OpenAI-compatible embedding APIs.
"""

from __future__ import annotations

from typing import List, Optional

from openai import OpenAI


class EmbeddingClient:
    """Thin wrapper around OpenAI-compatible embedding endpoints."""

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str,
        model: str,
        batch_size: int = 32,
    ):
        if not base_url:
            raise ValueError("Embedding base_url 未配置")
        if not model:
            raise ValueError("Embedding model 未配置")

        self.api_key = api_key or 'ollama'
        self.base_url = base_url
        self.model = model
        self.batch_size = max(1, int(batch_size))
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed texts in batches while preserving input order."""
        if not texts:
            return []

        embeddings: List[List[float]] = []
        normalized_inputs = [str(text or ' ').strip() or ' ' for text in texts]

        for start in range(0, len(normalized_inputs), self.batch_size):
            batch = normalized_inputs[start:start + self.batch_size]
            response = self.client.embeddings.create(model=self.model, input=batch)
            data = sorted(response.data, key=lambda item: item.index)
            embeddings.extend(item.embedding for item in data)

        return embeddings
