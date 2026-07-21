from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .settings import settings


logger = logging.getLogger("mirofish.local_zep")


class RerankerClient:
    """Small OpenAI/vLLM-friendly reranker client.

    The local graph uses this only for Zep's ``cross_encoder`` reranker. If no
    reranker endpoint is configured, graph search falls back to local hybrid
    ranking rather than failing the application request.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.reranker_api_key or "local-reranker-key"
        self.base_url = (base_url or settings.reranker_base_url or "").rstrip("/")
        self.model_name = (model_name or settings.reranker_model_name or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.model_name)

    def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        if not self.is_configured or not query or not documents:
            return None

        payload = {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }

        for url in self._candidate_urls():
            try:
                response = self._post_json(url, payload)
                scores = self._extract_scores(response, len(documents))
                if scores is not None:
                    return scores
            except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Reranker request failed for %s: %s", url, exc)

        return None

    def _candidate_urls(self) -> list[str]:
        if self.base_url.endswith("/v1"):
            return [f"{self.base_url}/rerank"]
        return [f"{self.base_url}/v1/rerank", f"{self.base_url}/rerank"]

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_scores(self, response: dict[str, Any], expected_count: int) -> list[float] | None:
        if isinstance(response.get("scores"), list):
            scores = [float(value) for value in response["scores"]]
            return scores[:expected_count] + [0.0] * max(0, expected_count - len(scores))

        rows = response.get("results")
        if not isinstance(rows, list):
            rows = response.get("data")
        if not isinstance(rows, list):
            return None

        scores = [0.0] * expected_count
        found = False
        for rank, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            index = item.get("index", item.get("document_index", item.get("documentIndex", rank)))
            try:
                index = int(index)
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= expected_count:
                continue
            score = item.get("relevance_score", item.get("relevanceScore", item.get("score", item.get("relevance"))))
            try:
                scores[index] = float(score)
            except (TypeError, ValueError):
                continue
            found = True

        return scores if found else None
