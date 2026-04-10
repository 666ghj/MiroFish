"""
Reranker client wrappers for common HTTP rerank APIs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib import error, request


@dataclass
class RerankerRequestSpec:
    provider: str
    path: str
    body: dict


class RerankerClient:
    """Thin wrapper around HTTP rerank endpoints."""

    def __init__(
        self,
        base_url: str,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: str = "auto",
        timeout: float = 20.0,
    ):
        if not base_url:
            raise ValueError("Reranker base_url 未配置")

        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or None
        self.provider = (provider or "auto").strip().lower() or "auto"
        self.timeout = max(1.0, float(timeout))

    def rerank(self, query: str, documents: List[str]) -> Dict[int, float]:
        """Return index -> score for the supplied candidate documents."""
        if not documents:
            return {}

        last_error: Optional[Exception] = None
        for spec in self._build_request_specs(query, documents):
            try:
                return self._execute_request(spec)
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise RuntimeError("没有可用的 reranker provider")

    def _build_request_specs(self, query: str, documents: List[str]) -> List[RerankerRequestSpec]:
        providers = [self.provider]
        if self.provider == "auto":
            providers = ["tei", "jina", "cohere", "vllm", "infinity"]

        specs: List[RerankerRequestSpec] = []
        for provider in providers:
            if provider == "tei":
                specs.append(
                    RerankerRequestSpec(
                        provider=provider,
                        path="/rerank",
                        body={
                            "query": query,
                            "texts": documents,
                            "truncate": True,
                            "raw_scores": False,
                        },
                    )
                )
            elif provider in {"jina", "vllm", "infinity"}:
                body = {
                    "query": query,
                    "documents": documents,
                    "top_n": len(documents),
                    "return_documents": False,
                }
                if self.model:
                    body["model"] = self.model
                specs.append(
                    RerankerRequestSpec(
                        provider=provider,
                        path="/v1/rerank",
                        body=body,
                    )
                )
            elif provider == "cohere":
                body = {
                    "query": query,
                    "documents": documents,
                    "top_n": len(documents),
                    "return_documents": False,
                }
                if self.model:
                    body["model"] = self.model
                specs.append(
                    RerankerRequestSpec(
                        provider=provider,
                        path="/v2/rerank",
                        body=body,
                    )
                )

        return specs

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _execute_request(self, spec: RerankerRequestSpec) -> Dict[int, float]:
        payload = json.dumps(spec.body).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{spec.path}",
            data=payload,
            headers=self._headers(),
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{spec.provider} rerank 请求失败: HTTP {exc.code}: {detail[:300]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"{spec.provider} rerank 请求失败: {exc.reason}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{spec.provider} rerank 返回非 JSON 响应") from exc

        scores = self._parse_scores(spec.provider, data)
        if not scores:
            raise RuntimeError(f"{spec.provider} rerank 未返回有效分数")
        return scores

    def _parse_scores(self, provider: str, payload: object) -> Dict[int, float]:
        if provider == "tei":
            if not isinstance(payload, list):
                raise RuntimeError("TEI rerank 响应格式异常")

            scores: Dict[int, float] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                score = item.get("score")
                if isinstance(index, int) and score is not None:
                    scores[index] = float(score)
            return scores

        if not isinstance(payload, dict):
            raise RuntimeError("rerank 响应格式异常")

        results = payload.get("results") or payload.get("data") or []
        scores: Dict[int, float] = {}
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                score = item.get("relevance_score")
                if score is None:
                    score = item.get("score")
                if isinstance(index, int) and score is not None:
                    scores[index] = float(score)
        return scores
