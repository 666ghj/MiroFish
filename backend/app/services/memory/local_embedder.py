"""Local sentence-transformers embedder for Graphiti.

Avoids the need for an external embedding API (OpenAI, Voyage, etc).
The default model ``all-MiniLM-L6-v2`` is ~80 MB, produces 384-d
vectors, and runs comfortably on CPU. It is already a transitive
dependency of ``camel-oasis`` so no extra install is required.

The class implements Graphiti's :class:`EmbedderClient` interface so
it is a drop-in replacement for :class:`OpenAIEmbedder` /
:class:`VoyageEmbedder`.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Iterable
from typing import Optional

from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig
from pydantic import Field


DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class LocalEmbedderConfig(EmbedderConfig):
    """Config for :class:`LocalSentenceTransformerEmbedder`."""

    embedding_model: str = Field(default=DEFAULT_LOCAL_MODEL)
    device: Optional[str] = Field(default=None)  # e.g. "cpu", "mps", "cuda"
    # Override the parent's frozen embedding_dim so we can match the
    # actual model's output dimensionality (MiniLM-L6 is 384, not 1024).
    embedding_dim: int = Field(default=384, frozen=False)


class LocalSentenceTransformerEmbedder(EmbedderClient):
    """Embedder backed by a local sentence-transformers model.

    Loads the model lazily on first use so import is cheap. Model
    inference runs on a worker thread (via :func:`asyncio.to_thread`)
    because sentence-transformers is synchronous.
    """

    _MODEL_CACHE: dict[str, object] = {}
    _CACHE_LOCK = threading.Lock()

    def __init__(self, config: Optional[LocalEmbedderConfig] = None) -> None:
        self.config = config or LocalEmbedderConfig()

    def _get_model(self):  # noqa: ANN202 — return type depends on import
        """Load the underlying model once per process, lazily."""
        model_name = self.config.embedding_model
        with LocalSentenceTransformerEmbedder._CACHE_LOCK:
            if model_name not in LocalSentenceTransformerEmbedder._MODEL_CACHE:
                from sentence_transformers import SentenceTransformer

                # HF transformers can spew progress bars on first download;
                # silence that for a clean backend log.
                os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

                LocalSentenceTransformerEmbedder._MODEL_CACHE[model_name] = (
                    SentenceTransformer(model_name, device=self.config.device)
                )
                # Reflect the real output dimensionality on the config
                # so Graphiti's similarity queries get a coherent number.
                model = LocalSentenceTransformerEmbedder._MODEL_CACHE[model_name]
                try:
                    actual_dim = int(model.get_sentence_embedding_dimension())
                    if actual_dim and actual_dim != self.config.embedding_dim:
                        self.config.embedding_dim = actual_dim
                except Exception:
                    pass
        return LocalSentenceTransformerEmbedder._MODEL_CACHE[model_name]

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        """Encode ``input_data`` and return a single embedding vector.

        Graphiti calls this once per text snippet; the contract is
        "first vector of the result". When input is a list, only the
        first item's vector is returned (matches the OpenAI embedder).
        """
        # Normalise to a list of strings.
        if isinstance(input_data, str):
            texts: list[str] = [input_data]
        elif isinstance(input_data, list):
            texts = [item if isinstance(item, str) else str(item) for item in input_data]
        else:  # an iterable of ints / sub-iterables — we only support text
            texts = [str(input_data)]

        model = self._get_model()
        vectors = await asyncio.to_thread(
            model.encode,
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        # encode([text]) returns a 2D numpy array shape (1, dim)
        first = vectors[0]
        # Truncate / pad to the configured dim — Graphiti stores fixed-
        # length vectors so the similarity index keeps working.
        return [float(x) for x in first[: self.config.embedding_dim]]
