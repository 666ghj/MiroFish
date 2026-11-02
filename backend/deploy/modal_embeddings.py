"""Twitter's ``twhin-bert-base`` behind an OpenAI-style ``/v1/embeddings`` endpoint, hosted on Modal.

OASIS ranks the Twitter feed by embedding every post and every agent profile with this model and comparing the
vectors. Run locally that is heavy (about 1 GB of RAM and most of both CPU cores). This app does the same work on
Modal: the vector is the model's ``pooler_output``, exactly what
``oasis.social_platform.process_recsys_posts.generate_post_vector`` returns, and the laptop only sends text.

One thing about that vector: the twhin-bert-base checkpoint has no pooler layer, so transformers creates a randomly
initialised one every time the model is loaded (the "pooler.dense.* newly initialized" warning). OASIS therefore
ranks with a different random projection in every process. Here the initialisation is seeded (``POOLER_SEED``), so
the vectors are the same in every container: a container that restarts in the middle of a run cannot change the
projection under vectors the client has already cached.

Deploy (see docs/behavior-and-ensembles.md, "Hosting the Twitter feed ranker"):

    modal secret create mirofish-embeddings EMBEDDING_API_TOKEN=<a long random string>
    modal deploy backend/deploy/modal_embeddings.py

then set ``LLM_EMBEDDING_BASE_URL`` (the printed URL + ``/v1``), ``LLM_EMBEDDING_API_KEY`` (the same token) and
``LLM_EMBEDDING_MODEL_NAME=twhin-bert-base`` in ``.env``. Stop it with ``modal app stop mirofish-embeddings``.

Cost: one CPU container (4 cores, 8 GiB, about $0.25 per active hour) that scales to zero two minutes after the last
request and never runs more than one copy, so a simulation costs roughly $0.15-0.30 and an idle day costs nothing.
"""

import base64
import hmac
import os
import threading
from typing import List, Union

import modal

APP_NAME = "mirofish-embeddings"
MODEL_ID = "Twitter/twhin-bert-base"
MODEL_ALIAS = "twhin-bert-base"
MAX_TEXTS_PER_REQUEST = 256
MAX_TOKENS = 512        # the tokenizer reports no maximum length, so a very long text would otherwise crash the model
POOLER_SEED = 0         # seeds the random pooler layer (see the module docstring)
CPU_CORES = 4

app = modal.App(APP_NAME)


def _download_model() -> None:
    """Runs once while the image is built, so the weights are part of the image and a cold start only loads them."""
    from transformers import AutoModel, AutoTokenizer

    AutoTokenizer.from_pretrained(MODEL_ID)
    AutoModel.from_pretrained(MODEL_ID)


# the versions the backend runs, so the tokenizer and the model behave exactly as they do in OASIS
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.9.1",
        "transformers==4.57.3",
        "tokenizers==0.22.1",
        "numpy==2.3.5",
        "fastapi==0.115.6",
        extra_index_url="https://download.pytorch.org/whl/cpu",
    )
    .run_function(_download_model)
)


@app.cls(
    image=image,
    cpu=CPU_CORES,
    memory=8192,
    timeout=600,  # one request, not the container's lifetime
    scaledown_window=120,  # a simulation round is ~40 s, so the container stays warm for the whole run
    max_containers=1,  # a bug or a runaway client can never fan out into many billed containers
    secrets=[modal.Secret.from_name("mirofish-embeddings")],
)
class Embeddings:
    @modal.enter()
    def load(self) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(CPU_CORES)
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        torch.manual_seed(POOLER_SEED)   # the pooler layer is initialised here, not read from the checkpoint
        self.model = AutoModel.from_pretrained(MODEL_ID).eval()
        self.lock = threading.Lock()  # one forward pass at a time: the cores are the limit, not the queue

    def embed(self, texts: List[str], batch_size: int = 32):
        """``pooler_output`` of each text, as in OASIS's ``generate_post_vector`` (padding and truncation included)."""
        vectors = []
        with self.lock, self.torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = texts[start:start + batch_size]
                inputs = self.tokenizer(
                    batch, return_tensors="pt", padding=True, truncation=True, max_length=MAX_TOKENS
                )
                vectors.append(self.model(**inputs).pooler_output)
        return self.torch.cat(vectors, dim=0).cpu().numpy().astype("float32")

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, Header, HTTPException

        api = FastAPI(title=APP_NAME)
        token = os.environ["EMBEDDING_API_TOKEN"]

        def authorize(authorization: str) -> None:
            if not hmac.compare_digest((authorization or "").removeprefix("Bearer ").strip(), token):
                raise HTTPException(status_code=401, detail="invalid token")

        @api.get("/health")
        def health():
            return {"status": "ok", "model": MODEL_ALIAS}

        @api.post("/v1/embeddings")
        def embeddings(body: dict, authorization: str = Header(default="")):
            authorize(authorization)
            texts: Union[str, List[str], None] = body.get("input")
            if isinstance(texts, str):
                texts = [texts]
            if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
                raise HTTPException(status_code=400, detail="input must be a string or a non-empty list of strings")
            if len(texts) > MAX_TEXTS_PER_REQUEST:
                raise HTTPException(status_code=400, detail=f"at most {MAX_TEXTS_PER_REQUEST} texts per request")
            # an empty string would tokenize to nothing but the special tokens; embed a space instead of failing
            vectors = self.embed([t if t.strip() else " " for t in texts])
            as_base64 = body.get("encoding_format") == "base64"
            return {
                "object": "list",
                "model": MODEL_ALIAS,
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": base64.b64encode(vector.tobytes()).decode() if as_base64 else vector.tolist(),
                    }
                    for index, vector in enumerate(vectors)
                ],
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            }

        return api
