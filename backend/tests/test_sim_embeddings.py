import types

import numpy as np
import pytest

import sim_embeddings


class FakeClient:
    """An OpenAI-style client whose ``embeddings.create`` answers from a function (or raises what it is given)."""

    def __init__(self, vector_of=None, fail=None):
        self.calls = []
        self.vector_of = vector_of or (lambda text: [float(len(text)), 1.0, 0.5])
        self.fail = list(fail or [])
        self.embeddings = types.SimpleNamespace(create=self._create)

    def _create(self, model, input, encoding_format):
        self.calls.append(list(input))
        if self.fail:
            error = self.fail.pop(0)
            if error is not None:
                raise error
        # answer out of order, as a server may: the client must sort by index
        data = [types.SimpleNamespace(index=i, embedding=self.vector_of(text)) for i, text in enumerate(input)]
        return types.SimpleNamespace(data=list(reversed(data)))


def embedder(client, **kwargs):
    return sim_embeddings.RemoteEmbedder("http://x/v1", "k", client=client, sleep=lambda _s: None, **kwargs)


class Boom(Exception):
    status_code = None


class Refused(Exception):
    status_code = 401


def test_vectors_come_back_in_the_order_of_the_texts():
    out = embedder(FakeClient()).embed(["a", "bbb", "cc"])
    assert out.shape == (3, 3)
    assert out[:, 0].tolist() == [1.0, 3.0, 2.0]


def test_a_text_is_only_ever_sent_once():
    client = FakeClient()
    e = embedder(client)
    e.embed(["a", "b", "a"])                       # a duplicate inside one call
    e.embed(["b", "c", "a"])                       # one new text; the other two are cached
    assert client.calls == [["a", "b"], ["c"]]
    e.embed(["a", "b", "c"])                       # nothing new: no request at all
    assert len(client.calls) == 2


def test_texts_go_out_in_batches():
    client = FakeClient()
    embedder(client, batch_size=2).embed(["a", "b", "c", "d", "e"])
    assert [len(c) for c in client.calls] == [2, 2, 1]


def test_an_empty_or_missing_text_is_embedded_as_a_space():
    client = FakeClient()
    out = embedder(client).embed(["", None, "x"])
    assert client.calls == [[" ", "x"]]
    assert out.shape[0] == 3


def test_a_failed_request_is_retried_then_succeeds():
    client = FakeClient(fail=[Boom("down"), Boom("down"), None])
    out = embedder(client).embed(["a"])
    assert len(client.calls) == 3 and out.shape == (1, 3)


def test_a_refused_request_is_not_retried_and_the_round_uses_the_local_fallback():
    lines = []
    client = FakeClient(fail=[Refused("bad token")])
    e = embedder(client)
    e.log = lines.append
    out = e.embed(["alpha beta", "beta gamma"])
    assert len(client.calls) == 1                                   # 401 will not get better
    assert out.shape == (2, sim_embeddings.FALLBACK_DIMENSION)
    assert e.fallbacks == 1 and "Refused" in lines[0]
    assert e.cache == {}                                            # fallback vectors are never cached


def test_after_retries_run_out_the_fallback_is_used_and_the_next_call_recovers():
    client = FakeClient(fail=[Boom("x")] * 4)
    e = embedder(client)
    assert e.embed(["a"]).shape[1] == sim_embeddings.FALLBACK_DIMENSION
    assert e.embed(["a"]).shape == (1, 3)                           # the endpoint is back: real vectors again


def test_a_changed_embedding_size_is_an_error_not_a_mixed_matrix():
    sizes = iter([[1.0, 2.0], [1.0, 2.0, 3.0]])
    client = FakeClient(vector_of=lambda text: next(sizes))
    e = embedder(client, batch_size=1)
    assert e.embed(["a", "b"]).shape[1] == sim_embeddings.FALLBACK_DIMENSION
    assert e.fallbacks == 1


def test_the_hash_fallback_is_normalised_deterministic_and_similar_for_similar_text():
    v = sim_embeddings.hashed_vectors(["sebi settlement news", "sebi settlement news", "mango pickle recipe", ""])
    assert np.allclose(np.linalg.norm(v[:3], axis=1), 1.0) and not v[3].any()
    assert np.array_equal(v[0], v[1])
    assert float(v[0] @ v[1]) > float(v[0] @ v[2])


def test_settings_need_a_base_url_and_read_the_rest_from_the_environment():
    assert sim_embeddings.settings({}) is None
    assert sim_embeddings.settings({"LLM_EMBEDDING_BASE_URL": "  "}) is None
    got = sim_embeddings.settings({
        "LLM_EMBEDDING_BASE_URL": "https://x/v1", "LLM_EMBEDDING_API_KEY": "k",
        "LLM_EMBEDDING_MODEL_NAME": "bge", "LLM_EMBEDDING_TIMEOUT": "30", "LLM_EMBEDDING_BATCH": "oops",
    })
    assert sim_embeddings.settings({"LLM_EMBEDDING_BASE_URL": "https://x.modal.run"})["base_url"] == "https://x.modal.run/v1"
    assert sim_embeddings.settings({"LLM_EMBEDDING_BASE_URL": "https://x.modal.run/"})["base_url"] == "https://x.modal.run/v1"
    assert sim_embeddings.settings({"LLM_EMBEDDING_BASE_URL": "https://api.x.com/client/v4/ai/v1"})["base_url"] == "https://api.x.com/client/v4/ai/v1"
    assert got == {"base_url": "https://x/v1", "api_key": "k", "model": "bge", "timeout": 30.0,
                   "batch_size": sim_embeddings.DEFAULT_BATCH}


def test_with_no_endpoint_configured_nothing_is_changed():
    from oasis.social_platform import recsys

    before = recsys.get_recsys_model, recsys.generate_post_vector
    assert sim_embeddings.install_remote_embeddings({}) is None
    assert (recsys.get_recsys_model, recsys.generate_post_vector) == before


def test_installed_oasis_never_loads_twhin_and_embeds_through_the_endpoint():
    from oasis.social_platform import recsys

    client = FakeClient()
    original_get, original_generate = recsys.get_recsys_model, recsys.generate_post_vector
    try:
        e = embedder(client)
        assert sim_embeddings.install_remote_embeddings({}, embedder=e) is e
        model, tokenizer = recsys.get_recsys_model(recsys_type="twhin-bert")   # no 0.5 GB model is loaded
        vectors = recsys.generate_post_vector(model, tokenizer, ["hello", "world!"], batch_size=1000)
        assert vectors.shape == (2, 3) and client.calls == [["hello", "world!"]]
        assert sim_embeddings.install_remote_embeddings({}, embedder=embedder(FakeClient())) is e   # idempotent
    finally:
        sim_embeddings.uninstall_remote_embeddings()
    assert (recsys.get_recsys_model, recsys.generate_post_vector) == (original_get, original_generate)
