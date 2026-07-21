from __future__ import annotations

import math
from typing import Iterable

from .settings import settings


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    return dot / (left_norm * right_norm)


class EmbeddingClient:
    """OpenAI-compatible embeddings client with vLLM-friendly defaults."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.embedding_api_key or "local-embedding-key"
        self.base_url = (base_url or settings.embedding_base_url or "").strip()
        self.model_name = (model_name or settings.embedding_model_name or "").strip()

        if not self.base_url:
            raise ValueError("EMBEDDING_BASE_URL 未配置")
        if not self.model_name:
            raise ValueError("EMBEDDING_MODEL_NAME 未配置")

        from openai import OpenAI

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def embed_texts(self, texts: Iterable[str], batch_size: int = 32) -> list[list[float]]:
        normalized = [text.strip() if text else "" for text in texts]
        if not normalized:
            return []

        results: list[list[float]] = []
        for start in range(0, len(normalized), batch_size):
            batch = normalized[start:start + batch_size]
            response = self.client.embeddings.create(
                model=self.model_name,
                input=batch,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            results.extend([list(item.embedding) for item in ordered])
        return results

    def embed_text(self, text: str) -> list[float]:
        embeddings = self.embed_texts([text])
        return embeddings[0] if embeddings else []
