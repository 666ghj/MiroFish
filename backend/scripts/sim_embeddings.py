"""Send the Twitter feed ranker's embeddings to a hosted endpoint instead of running twhin-bert on this machine.

OASIS ranks the Twitter feed (``recsys_type="twhin-bert"``) by embedding every post and every agent profile with
Twitter's ``twhin-bert-base`` on the local CPU, every round, and loads the 0.5 GB model on the first ranking call.
With ``LLM_EMBEDDING_BASE_URL`` set, ``install_remote_embeddings`` replaces just that step: the ranking itself
(similarity, recency, follower weighting) stays OASIS's. Texts are embedded once and cached, so a round only sends
the posts and the changed profiles it has not seen.

The endpoint is any OpenAI-style ``/embeddings`` server. ``backend/deploy/modal_embeddings.py`` hosts the same
``twhin-bert-base`` on Modal, which keeps the ranking identical to a local run. A different embedding model works,
but ranks differently, so runs are not comparable with ones that used twhin-bert.

If a request fails after its retries, that round's ranking uses a cheap local word-hash vector for every text of the
call (never a mix of the two kinds), so a network problem costs ranking quality for a round, not the run.
"""

import time
import zlib
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np

DEFAULT_MODEL = "twhin-bert-base"
DEFAULT_TIMEOUT = 120.0   # a cold container loads the model before it answers
DEFAULT_BATCH = 64
RETRY_DELAYS = (1.0, 3.0, 8.0)
FALLBACK_DIMENSION = 256


def hashed_vectors(texts: Sequence[str], dimension: int = FALLBACK_DIMENSION) -> np.ndarray:
    """A bag-of-words vector per text (the hashing trick, L2-normalised): no model, no network, deterministic."""
    vectors = np.zeros((len(texts), dimension), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in str(text or "").lower().split():
            vectors[row, zlib.crc32(word.encode("utf-8")) % dimension] += 1.0
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


class RemoteEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        batch_size: int = DEFAULT_BATCH,
        log: Optional[Callable[[str], None]] = None,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=base_url, api_key=api_key or "none", timeout=timeout, max_retries=0)
        self.client, self.model, self.batch_size = client, model, max(1, int(batch_size))
        self.log, self.sleep = log or (lambda _message: None), sleep
        self.cache: Dict[str, np.ndarray] = {}
        self.requests = 0
        self.fallbacks = 0

    def embed(self, texts: Sequence[str]) -> Any:
        """A ``(len(texts), dimension)`` float tensor, in the order of ``texts``."""
        import torch

        cleaned = [t if isinstance(t, str) and t.strip() else " " for t in texts]
        missing = list(dict.fromkeys(t for t in cleaned if t not in self.cache))
        started = time.time()
        try:
            fetched = self._fetch(missing) if missing else {}
        except Exception as error:  # noqa: BLE001 - whatever went wrong, the round must still be ranked
            self.fallbacks += 1
            self.log(
                f"远程嵌入失败，本轮改用本地词哈希向量 ({type(error).__name__}: {str(error)[:160]})"
                f" / remote embeddings failed, ranking this round with local word-hash vectors"
            )
            return torch.from_numpy(hashed_vectors(cleaned))
        self.cache.update(fetched)
        if missing:
            self.log(f"远程嵌入: 新增 {len(missing)} 条文本，耗时 {time.time() - started:.1f}秒 (缓存 {len(self.cache)} 条)")
        return torch.from_numpy(np.stack([self.cache[t] for t in cleaned]))

    def _fetch(self, texts: List[str]) -> Dict[str, np.ndarray]:
        found: Dict[str, np.ndarray] = {}
        dimension = len(next(iter(self.cache.values()))) if self.cache else None
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            vectors = self._request(batch)
            if len(vectors) != len(batch):
                raise ValueError(f"asked for {len(batch)} embeddings, got {len(vectors)}")
            for text, vector in zip(batch, vectors):
                dimension = dimension or len(vector)
                if len(vector) != dimension:
                    raise ValueError(f"embedding size changed from {dimension} to {len(vector)}")
                found[text] = vector
        return found

    def _request(self, batch: List[str]) -> List[np.ndarray]:
        last_error: Optional[BaseException] = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                self.requests += 1
                response = self.client.embeddings.create(model=self.model, input=batch, encoding_format="float")
                ordered = sorted(response.data, key=lambda item: item.index)
                return [np.asarray(item.embedding, dtype=np.float32) for item in ordered]
            except Exception as error:  # noqa: BLE001
                last_error = error
                status = getattr(error, "status_code", None)
                if status in (400, 401, 403, 404, 422):
                    break  # a request the server will refuse again
                if attempt < len(RETRY_DELAYS):
                    self.sleep(RETRY_DELAYS[attempt])
        assert last_error is not None
        raise last_error


def settings(environ: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """The embedding endpoint from the environment, or None when ``LLM_EMBEDDING_BASE_URL`` is not set."""
    base_url = (environ.get("LLM_EMBEDDING_BASE_URL") or "").strip()
    if not base_url:
        return None
    if urlparse(base_url).path in ("", "/"):
        base_url = base_url.rstrip("/") + "/v1"      # a bare host (what ``modal deploy`` prints): the API lives under /v1

    def number(name: str, default: float) -> float:
        try:
            value = float(environ.get(name) or 0)
        except ValueError:
            value = 0.0
        return value if value > 0 else default

    return {
        "base_url": base_url,
        "api_key": (environ.get("LLM_EMBEDDING_API_KEY") or "").strip(),
        "model": (environ.get("LLM_EMBEDDING_MODEL_NAME") or DEFAULT_MODEL).strip(),
        "timeout": number("LLM_EMBEDDING_TIMEOUT", DEFAULT_TIMEOUT),
        "batch_size": int(number("LLM_EMBEDDING_BATCH", DEFAULT_BATCH)),
    }


_INSTALLED: Dict[str, Any] = {}


def install_remote_embeddings(
    environ: Mapping[str, str],
    log: Optional[Callable[[str], None]] = None,
    embedder: Optional[RemoteEmbedder] = None,
) -> Optional[RemoteEmbedder]:
    """Make OASIS's twhin-bert ranker embed through the configured endpoint. Returns the embedder, or None when
    no endpoint is configured (then nothing is changed and the ranker runs locally as before). Safe to call again."""
    if _INSTALLED:
        return _INSTALLED["embedder"]
    config = settings(environ)
    if config is None and embedder is None:
        return None
    if embedder is None:
        embedder = RemoteEmbedder(log=log, **config)

    from oasis.social_platform import recsys

    original_get, original_generate = recsys.get_recsys_model, recsys.generate_post_vector
    placeholder = object()   # stands for the model and the tokenizer: the real ones are never loaded

    def get_recsys_model(recsys_type: str = None):
        if recsys_type == "twhin-bert":
            return placeholder, placeholder
        return original_get(recsys_type)

    def generate_post_vector(model, tokenizer, texts, batch_size):
        if model is placeholder:
            return embedder.embed(texts)
        return original_generate(model, tokenizer, texts, batch_size)

    recsys.get_recsys_model, recsys.generate_post_vector = get_recsys_model, generate_post_vector
    _INSTALLED.update(embedder=embedder, originals=(original_get, original_generate))
    if log:
        log(f"Twitter 推荐系统的嵌入改用远程接口: model={embedder.model} (本机不加载 twhin-bert)")
    return embedder


def uninstall_remote_embeddings() -> None:
    """Put OASIS's own functions back (used by tests)."""
    if not _INSTALLED:
        return
    from oasis.social_platform import recsys

    recsys.get_recsys_model, recsys.generate_post_vector = _INSTALLED["originals"]
    _INSTALLED.clear()
