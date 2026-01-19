"""
Local vector store (Qdrant)

Stores chunk embeddings and metadata, isolated by project_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient

logger = get_logger("mirofish.local_vector_store")


def _now_iso() -> str:
    return datetime.now().isoformat()


class QdrantChunkStore:
    def __init__(self, llm: Optional[LLMClient] = None):
        self._client = QdrantClient(
            url=Config.QDRANT_URL,
            api_key=Config.QDRANT_API_KEY,
            timeout=30.0,
        )
        self._collection = Config.QDRANT_COLLECTION_CHUNKS
        self._llm = llm or LLMClient(
            api_key=Config.EMBEDDING_API_KEY,
            base_url=Config.EMBEDDING_BASE_URL,
            model=Config.LLM_MODEL_NAME,
        )
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            existing = self._client.get_collection(self._collection)
            _ = existing  # silence lint
            return
        except Exception:
            pass

        # We need to know vector size. Use a one-off embedding.
        try:
            vec = self._llm.embed_texts(["ping"], model=Config.EMBEDDING_MODEL_NAME)[0]
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize embeddings for Qdrant collection. "
                f"Check EMBEDDING_* settings or set VECTOR_BACKEND=none. err={e}"
            ) from e

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=len(vec),
                distance=qmodels.Distance.COSINE,
            ),
        )
        logger.info(f"Created Qdrant collection: {self._collection} size={len(vec)}")

    def add_chunk(
        self,
        project_id: str,
        graph_id: str,
        chunk_id: str,
        text: str,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        point_id = uuid.uuid4().hex
        vectors = self._llm.embed_texts([text], model=Config.EMBEDDING_MODEL_NAME)[0]

        payload: Dict[str, Any] = {
            "project_id": project_id,
            "graph_id": graph_id,
            "chunk_id": chunk_id,
            "text": text,
            "created_at": _now_iso(),
        }
        if extra_payload:
            payload.update(extra_payload)

        self._client.upsert(
            collection_name=self._collection,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector=vectors,
                    payload=payload,
                )
            ],
        )
        return point_id

    def search_chunks(
        self,
        project_id: Optional[str],
        graph_id: Optional[str],
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        query_vector = self._llm.embed_texts([query], model=Config.EMBEDDING_MODEL_NAME)[0]

        must = []
        if project_id:
            must.append(qmodels.FieldCondition(key="project_id", match=qmodels.MatchValue(value=project_id)))
        if graph_id:
            must.append(qmodels.FieldCondition(key="graph_id", match=qmodels.MatchValue(value=graph_id)))

        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=limit,
            query_filter=qmodels.Filter(must=must) if must else None,
            with_payload=True,
        )

        items: List[Dict[str, Any]] = []
        for r in results:
            payload = r.payload or {}
            items.append(
                {
                    "score": float(r.score),
                    "chunk_id": payload.get("chunk_id"),
                    "text": payload.get("text", ""),
                    "graph_id": payload.get("graph_id"),
                    "created_at": payload.get("created_at"),
                    "payload": payload,
                }
            )
        return items
