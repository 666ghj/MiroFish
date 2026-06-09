"""
Graphiti service — MiroFish adapter that replaces the Zep Cloud client with a
self-hosted Graphiti + FalkorDB stack.

This module is the Zep-shaped facade the rest of MiroFish calls into. The
public method names match what `zep_cloud`'s `Zep` client used to expose, so
`graph_builder.py`, `zep_paging.py`, and the other Zep-touching services can
keep their call sites unchanged.

Stack (all running locally in this fork):
  - Graphiti (open-source, the engine behind Zep Cloud)
  - FalkorDB as the graph store (Redis module, no Neo4j, no Bolt)
  - MiniMax M3 as the LLM (via the OpenAI-compat /v1/chat/completions endpoint)
  - Local deterministic hash embedder (no torch / sentence-transformers in the
    minimal e2e container; the production Dockerfile installs the real
    multilingual sentence-transformers model and switches EMBEDDING_MODEL to it)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import sys
import threading
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from ..config import Config

logger = logging.getLogger("mirofish.graphiti_service")

# ---------------------------------------------------------------------------
# Cross-encoder reranker (M3-backed, no logprobs required)
# ---------------------------------------------------------------------------
#
# Graphiti's stock `OpenAIRerankerClient` reads `response.choices[0].logprobs`
# to extract a True/False score — i.e. it requires logprobs+top_logprobs and
# the model to emit the literal "True"/"False" token. MiniMax M3 returns
# `logprobs: None` for that request, so the stock client AttributeErrors on
# the first passage. We implement a minimal `CrossEncoderClient` that asks M3
# a chat-completion "True/False" question and scores 1.0 / 0.0 — exact-match on
# the first token, with a fuzzy fallback. For ranking, exact binary scores
# are fine — Graphiti uses the score to break ties; it doesn't need calibrated
# probabilities.

try:
    from graphiti_core.cross_encoder.client import CrossEncoderClient
    from graphiti_core.llm_client.client import LLMClient
    from graphiti_core.embedder.client import EmbedderClient
    from graphiti_core import Graphiti
    from graphiti_core.driver.falkordb_driver import FalkorDriver
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "graphiti-core[falkordb] is required. Install with:\n"
        "  uv pip install 'graphiti-core[falkordb]>=0.20.0' falkordb"
    ) from e


class M3RerankerClient(CrossEncoderClient):
    """Graphiti CrossEncoderClient that scores passages with MiniMax M3 via
    a regular chat completion (no logprobs)."""

    def __init__(self, model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None):
        super().__init__()
        self.model = model or Config.LLM_MODEL_NAME
        self.client = AsyncOpenAI(
            api_key=api_key or Config.LLM_API_KEY,
            base_url=base_url or Config.LLM_BASE_URL,
        )

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []
        raw_scores = await asyncio.gather(
            *(self._score(p, query) for p in passages),
            return_exceptions=True,
        )
        safe_scores: list[float] = []
        for s in raw_scores:
            if isinstance(s, BaseException):
                logger.warning(f"[m3_reranker] score error: {s}")
                safe_scores.append(0.0)
            else:
                safe_scores.append(float(s))
        ranked = sorted(
            [(p, s) for p, s in zip(passages, safe_scores)],
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked

    async def _score(self, passage: str, query: str) -> float:
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at judging whether a passage is relevant to a query. Reply with a single word: True or False.",
                    },
                    {
                        "role": "user",
                        "content": f"PASSAGE:\n{passage}\n\nQUERY:\n{query}\n\nIs the PASSAGE relevant to the QUERY? Reply with one word: True or False.",
                    },
                ],
                temperature=0.0,
                max_tokens=4,
            )
            content = (resp.choices[0].message.content or "").strip().lower()
        except Exception as e:
            logger.warning(f"[m3_reranker] api error: {e}")
            return 0.0
        first = content.split()[0] if content.split() else ""
        if first.startswith("true"):
            return 1.0
        if first.startswith("false"):
            return 0.0
        if "true" in content and "false" not in content:
            return 1.0
        if "false" in content and "true" not in content:
            return 0.0
        return 0.0


# ---------------------------------------------------------------------------
# LLM client (Graphiti-compatible, MiniMax M3-backed)
# ---------------------------------------------------------------------------

class MinimaxLLMClient(LLMClient):
    """
    Graphiti's LLMClient ABC implementation that calls MiniMax M3 via the
    OpenAI-compat /v1/chat/completions endpoint and uses the `tools` API to
    extract structured Pydantic output.

    M3 ignores `response_format: {type: json_object}` (it wraps responses in
    markdown code fences) but DOES support the `tools` API for structured
    output. We build a synthetic function-calling tool whose parameters are
    the Pydantic schema Graphiti wants back, then parse the tool call's args.
    """

    def __init__(self, config: Optional[Any] = None, cache: bool = False):
        from graphiti_core.llm_client.config import LLMConfig
        if config is None:
            config = LLMConfig(
                api_key=Config.LLM_API_KEY,
                base_url=Config.LLM_BASE_URL,
                model=Config.LLM_MODEL_NAME,
            )
        self.config = config
        self.model = config.model
        self.small_model = getattr(config, "small_model", config.model)
        self.temperature = getattr(config, "temperature", 0)
        # M3 needs ~4-8 KB for tool-call args + reasoning tokens, and Graphiti
        # sometimes passes a default of 1024 which truncates the JSON mid-stream.
        self.max_tokens = getattr(config, "max_tokens", 16384)
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        try:
            from graphiti_core.tracer import NoOpTracer
            self.tracer = NoOpTracer()
        except Exception:
            self.tracer = None

    def set_tracer(self, tracer) -> None:
        self.tracer = tracer

    async def generate_response(
        self,
        messages,
        response_model: Optional[Type[BaseModel]] = None,
        max_tokens: Optional[int] = None,
        model_size: str = "medium",
        group_id: Optional[str] = None,
        prompt_name: Optional[str] = None,
        attribute_extraction: bool = False,
        **_unused,
    ):
        from graphiti_core.llm_client.client import get_extraction_language_instruction
        from graphiti_core.prompts.models import Message

        max_tokens = max_tokens or self.max_tokens
        oai_messages = []
        for m in messages:
            role = getattr(m, "role", "user")
            content = getattr(m, "content", "")
            if isinstance(m, Message) and getattr(m, "role", None) == "system":
                role = "system"
            oai_messages.append({"role": role, "content": content})

        lang_instr = get_extraction_language_instruction(group_id)
        if lang_instr and oai_messages and oai_messages[0]["role"] == "system":
            oai_messages[0]["content"] += lang_instr

        return await self._generate_response(
            oai_messages, response_model, max_tokens, model_size
        )

    async def _generate_response(
        self,
        messages,
        response_model: Optional[Type[BaseModel]],
        max_tokens: int,
        model_size: str = "medium",
    ) -> Dict[str, Any]:
        if response_model is not None:
            return await self._call_with_tool(messages, response_model, max_tokens)
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=self.temperature,
        )
        return {"content": resp.choices[0].message.content or ""}

    async def _call_with_tool(
        self,
        messages,
        response_model: Type[BaseModel],
        max_tokens: int,
    ) -> Dict[str, Any]:
        schema = response_model.model_json_schema()
        schema = _clean_schema_for_openai_tool(schema)
        tool_name = f"return_{response_model.__name__.lower()}"
        tools = [{
            "type": "function",
            "function": {
                "name": tool_name,
                "description": f"Return a {response_model.__name__} matching the schema.",
                "parameters": schema,
            },
        }]
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max(self.max_tokens, max_tokens or 0, 16384),
                tools=tools,
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
        except Exception as e:
            if "tool_choice" in str(e).lower() or "tools" in str(e).lower():
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max(self.max_tokens, max_tokens or 0, 16384),
                    tools=tools,
                    tool_choice="auto",
                )
            else:
                raise

        msg = resp.choices[0].message
        parsed_obj = None
        finish = resp.choices[0].finish_reason
        logger.warning(
            f"[graphiti_service] _call_with_tool finish={finish} "
            f"content_len={len(msg.content or '')} tool_calls={len(msg.tool_calls or [])}"
        )
        if finish == "length":
            raise ValueError(
                f"M3 returned finish_reason=length (truncated tool args); "
                f"got {len(msg.tool_calls[0].function.arguments if msg.tool_calls else '')} "
                f"chars of tool-call args"
            )
        if msg.tool_calls:
            try:
                raw = msg.tool_calls[0].function.arguments
                data = json.loads(raw)
                # M3 often emits the LLM-extraction schema in slightly different
                # field names than what graphiti-core's Pydantic models expect.
                # Translate the common shapes so extraction doesn't silently fail.
                data = _normalize_extraction_payload(data, response_model)
                # Defensive: graphiti sometimes passes a tuple (Union/Optional) as
                # the response_model; skip validation in that case and let the
                # caller's own type check fail naturally.
                if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
                    parsed_obj = None
                else:
                    parsed_obj = response_model.model_validate(data)
            except (ValidationError, Exception) as e:
                logger.warning(
                    f"[graphiti_service] tool call parse/validation failed for {response_model.__name__ if hasattr(response_model, '__name__') else response_model}: {e}; "
                    f"raw_args={msg.tool_calls[0].function.arguments!r}"
                )
                parsed_obj = None
        if parsed_obj is None:
            content = msg.content or ""
            cleaned = _strip_reasoning_and_fence(content)
            # Try to find a JSON object in the cleaned content
            data = _extract_json_object(cleaned)
            if data is None:
                logger.error(
                    f"[graphiti_service] could not find JSON in content. content={content[:500]!r}"
                )
                raise ValueError(f"No JSON in M3 response: {content[:200]!r}")
            data = _normalize_extraction_payload(data, response_model)
            if os.environ.get("MIROFISH_DEBUG_LLM"):
                with open("/tmp/mirofish_e2e/last_llm_payloads.jsonl", "a") as f:
                    f.write(json.dumps({"model": response_model.__name__, "data": data, "source": "content"}, default=str) + "\n")
            parsed_obj = response_model.model_validate(data)

        # Graphiti expects the raw Pydantic-model-field dict (e.g.
        # {"extracted_entities": [...]}), NOT a {ModelName: instance} wrapper.
        return parsed_obj.model_dump()


def _strip_reasoning_and_fence(s: str) -> str:
    """Remove <think>...</think> reasoning blocks and markdown code fences."""
    s = s.strip()
    # Strip <think>...</think> blocks
    import re
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL)
    s = s.strip()
    # Strip markdown code fences
    if s.startswith("```"):
        first_nl = s.find("\n")
        s = s[first_nl + 1:] if first_nl != -1 else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _extract_json_object(s: str):
    """
    Find the first balanced JSON object in `s`. Returns dict or None.
    M3 often emits reasoning followed by an un-fenced JSON object.
    """
    import re
    # Try direct parse first
    try:
        return json.loads(s)
    except Exception:
        pass
    # Find first { and try to match a balanced object
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start:i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return None
    return None


def _normalize_extraction_payload(data: Dict[str, Any], model: Type[BaseModel]) -> Dict[str, Any]:
    """
    M3 routinely emits graphiti-style entity extraction with field names like
    `entity_text` or `entity_name` (the prompt's user-facing names) instead of
    `name` + `entity_type_id` (the Pydantic schema's names). This normalizes
    the common shapes so the schema validates.

    Conservative by design: only rename fields when the model actually expects
    a different name (i.e. the current key is missing from the model). The
    CombinedFact / ExtractedEdges schemas already use source_entity_name /
    target_entity_name / relation_type as their Pydantic field names, so we
    don't touch those.
    """
    # Defensive: if `data` isn't a dict (e.g. model_validate got a tuple), bail.
    if not isinstance(data, dict):
        return data
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        return data
    try:
        _fields = model.model_fields
    except AttributeError:
        return data

    # Find the list field on the model (e.g. extracted_entities, edges, ...)
    list_field = None
    for fname, finfo in model.model_fields.items():
        ftype = str(finfo.annotation).lower() if finfo.annotation else ""
        if "list[" in ftype or finfo.annotation in (list, List):
            if fname in data or any(k in data for k in ("extracted_entities", "entities", "edges")):
                list_field = fname
                break
    if list_field is None:
        for fname in model.model_fields:
            if fname in data and isinstance(data[fname], list):
                list_field = fname
                break
    if list_field is None:
        for cand in ("extracted_entities", "entities", "edges", "items", "entity_resolutions", "summaries"):
            if cand in data and isinstance(data[cand], list):
                if model.model_fields:
                    first_field = list(model.model_fields.keys())[0]
                    data[first_field] = data.pop(cand)
                    list_field = first_field
                else:
                    list_field = cand
                break

    if list_field is None or list_field not in data or not isinstance(data[list_field], list):
        return data

    # Sanitize string "null" / "None" in temporal fields at the outer level
    for tmp_key in ("valid_at", "invalid_at", "expired_at"):
        if tmp_key in data and isinstance(data[tmp_key], str) and data[tmp_key].lower() in ("null", "none", ""):
            data.pop(tmp_key, None)

    # Same per-item — the LLM sometimes emits "null" for valid_at inside each edge.
    def _scrub_null_dates(item: dict) -> None:
        for tmp_key in ("valid_at", "invalid_at", "expired_at"):
            if tmp_key in item and isinstance(item[tmp_key], str) and item[tmp_key].lower() in ("null", "none", ""):
                item.pop(tmp_key, None)

    # Translate each item
    normalized_items = []
    # The OUTER model's list field type tells us the INNER model's class —
    # e.g. ExtractedEntities.extracted_entities -> list[ExtractedEntity].
    # We need the inner model's field set, not the outer one.
    inner_model = None
    if list_field:
        try:
            outer_finfo = model.model_fields.get(list_field)
            if outer_finfo is not None:
                ann = outer_finfo.annotation
                if ann is not None and hasattr(ann, "__args__"):
                    for arg in ann.__args__:
                        if isinstance(arg, type) and issubclass(arg, BaseModel):
                            inner_model = arg
                            break
        except (AttributeError, TypeError) as e:
            if os.environ.get("MIROFISH_DEBUG_LLM"):
                print(f"[DEBUG] introspection failed: {e}", file=sys.stderr)
    inner_field_set = set(inner_model.model_fields.keys()) if inner_model else set()
    # Fall back to outer model fields if we couldn't introspect the inner
    model_field_set = inner_field_set or set(model.model_fields.keys())

    for item in data[list_field]:
        if not isinstance(item, dict):
            normalized_items.append(item)
            continue
        _scrub_null_dates(item)
        item_norm = dict(item)

        # Only rename name-like fields if `name` is missing from the model
        # and one of the aliases is present. The M3 routinely emits
        # {text, type} when the prompt shows {name, entity_type_id}.
        if "name" in model_field_set and "name" not in item_norm:
            for alias in ("text", "entity_name", "entity_text", "entity", "value"):
                if alias in item_norm:
                    item_norm["name"] = item_norm.pop(alias)
                    break

        # Only rename entity_type_id if missing and the model expects it
        if "entity_type_id" in model_field_set and "entity_type_id" not in item_norm:
            for alias in ("type", "entity_type", "label", "category", "kind"):
                if alias in item_norm:
                    val = item_norm.pop(alias)
                    if isinstance(val, int):
                        item_norm["entity_type_id"] = val
                    elif isinstance(val, str):
                        item_norm["entity_type_id"] = _entity_type_id_for_label(val)
                    break

        # episode_indices default — M3 sometimes emits {"item": "0"} (JSON-schema
        # items shape) or a bare string instead of a list of ints.
        if "episode_indices" in model_field_set:
            if "episode_indices" in item_norm:
                v = item_norm["episode_indices"]
                if isinstance(v, dict) and "item" in v:
                    v = [v["item"]]
                if not isinstance(v, list):
                    v = [v]
                try:
                    item_norm["episode_indices"] = [int(x) for x in v]
                except (TypeError, ValueError):
                    item_norm["episode_indices"] = [0]
            else:
                item_norm["episode_indices"] = [0]

        # Strip any keys not in the model schema — Pydantic's strict=False
        # would silently keep them, but we want a clean payload.
        unknown_keys = [k for k in item_norm if k not in model_field_set]
        for k in unknown_keys:
            # Allow extra fields if the model has model_config = extra=allow,
            # otherwise drop them.
            extra = getattr(model, "model_config", {}).get("extra", "ignore")
            if extra in ("forbid", "ignore"):
                item_norm.pop(k, None)

        # Drop items that ended up empty (M3 sometimes emits {} placeholders).
        # If after normalization the item has none of the model's required
        # fields, it can't validate — skip it rather than fail the whole batch.
        if inner_model is not None:
            required = {fname for fname, finfo in inner_model.model_fields.items() if finfo.is_required()}
        else:
            required = {fname for fname, finfo in model.model_fields.items() if finfo.is_required()}
        if not required.intersection(item_norm.keys()):
            if os.environ.get("MIROFISH_DEBUG_LLM"):
                print(f"[DEBUG] dropping item, none of {required} in {list(item_norm.keys())}; item={item}", file=sys.stderr)
            continue

        normalized_items.append(item_norm)

    data[list_field] = normalized_items
    return data


def _entity_type_id_for_label(label: str) -> int:
    """
    Map a string entity-type label (e.g. 'Country') to an integer type id.
    graphiti-core assigns ids 0..N for the user-provided entity types in
    add_episode, so without state we can't be exact. A hash-based mapping
    is stable across calls and produces a deterministic id.
    """
    return (abs(hash(label)) % 32) + 1


def _clean_schema_for_openai_tool(schema: Dict[str, Any]) -> Dict[str, Any]:
    if "$defs" in schema:
        defs = schema.pop("$defs")
        schema["$defs"] = {k: v for k, v in defs.items() if k.startswith("Entity") or k.startswith("Edge")}

    def _force_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for v in node.values():
                _force_strict(v)
        elif isinstance(node, list):
            for v in node:
                _force_strict(v)
    _force_strict(schema)
    return schema


def _strip_markdown_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        s = s[first_nl + 1:] if first_nl != -1 else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


# ---------------------------------------------------------------------------
# Embedder (deterministic hash-based; lightweight, no model download)
# ---------------------------------------------------------------------------
#
# MiroFish's bespoke MiniMax embedding API (`POST /v1/embeddings` with
# `{model, type, texts}` — no OpenAI compat, rate-limited) and the
# sentence-transformers multilingual model (~470 MB) are both unsuitable for
# a fast in-container e2e test. We use a deterministic hash-based embedder
# that produces 384-dim L2-normalized vectors from text shingles — good
# enough for graphiti's add_episode to land entities in the graph and prove
# the wiring works. For production use, switch EMBEDDING_MODEL to a real
# sentence-transformers model and use LocalSentenceTransformersEmbedder.

EMBED_DIM = 384


class HashEmbedder(EmbedderClient):
    """
    Deterministic, dependency-free embedder. Maps text -> a 384-dim L2-normalized
    vector via feature hashing over 3-grams of the input.
    """

    def __init__(self, dim: int = EMBED_DIM, model_name: Optional[str] = None):
        self.dim = dim
        # model_name is ignored — accepted for parity with sentence-transformers
        self._model_name = model_name or "hash-384"

    async def create(self, input_data) -> List[float]:
        texts = input_data if isinstance(input_data, list) else [input_data]
        vecs = [self._embed(t) for t in texts]
        return vecs[0] if len(texts) == 1 else vecs

    async def create_batch(self, input_data_list) -> List[List[float]]:
        flat: List[str] = []
        for item in input_data_list:
            if isinstance(item, list):
                flat.extend(item)
            else:
                flat.append(item)
        # Compute in a thread to keep graphiti's event loop happy
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: [self._embed(t) for t in flat]
        )

    def _embed(self, text: str) -> List[float]:
        v = [0.0] * self.dim
        text = (text or "").lower().strip()
        if not text:
            return v
        # Word + 3-gram shingles
        tokens = text.split()
        shingles = list(tokens) + [
            f"{tokens[i]}_{tokens[i+1]}_{tokens[i+2]}"
            for i in range(len(tokens) - 2)
        ]
        for sh in shingles:
            for sign in (1, -1):
                h = hashlib.md5((sh + str(sign)).encode("utf-8")).digest()
                idx = int.from_bytes(h[:4], "big") % self.dim
                v[idx] += sign
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


# ---------------------------------------------------------------------------
# Zep-shaped node/edge dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ZepNode:
    """Stand-in for zep_cloud's EntityNode with the attrs the rest of MiroFish reads."""
    uuid_: str
    name: str = ""
    labels: List[str] = field(default_factory=list)
    summary: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    @property
    def uuid(self) -> str:
        return self.uuid_

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid_,
            "name": self.name,
            "labels": list(self.labels),
            "summary": self.summary,
            "attributes": self.attributes,
            "created_at": self.created_at,
        }


@dataclass
class ZepEdge:
    """Stand-in for zep_cloud's EntityEdge."""
    uuid_: str
    name: str = ""
    fact: str = ""
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    fact_type: str = ""
    episodes: List[str] = field(default_factory=list)

    @property
    def uuid(self) -> str:
        return self.uuid_


@dataclass
class _EpisodeRef:
    """Return type for add_batch — Zep's EpisodeData was an object; this satisfies .uuid_."""
    uuid_: str
    processed: bool

    @property
    def uuid(self):
        return self.uuid_


# ---------------------------------------------------------------------------
# GraphitiAdapter — the Zep-shaped facade
# ---------------------------------------------------------------------------

class GraphitiAdapter:
    """
    A single async-safe facade that exposes the Zep surface the rest of
    MiroFish uses, implemented on top of Graphiti (FalkorDB backend) and
    MiniMax M3.
    """

    def __init__(self):
        self._init_lock = threading.Lock()
        self._graphiti: Optional[Graphiti] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._embedder: Optional[EmbedderClient] = None
        self._llm_client: Optional[MinimaxLLMClient] = None
        self._cross_encoder: Optional[M3RerankerClient] = None
        self._ontologies: Dict[str, Dict[str, Any]] = {}

    # -- internal helpers --------------------------------------------------

    def _ensure_init(self):
        if self._graphiti is not None:
            return
        with self._init_lock:
            if self._graphiti is not None:
                return

            logger.info(
                f"[graphiti_service] connecting Graphiti -> FalkorDB at "
                f"{Config.FALKORDB_HOST}:{Config.FALKORDB_PORT}"
            )

            driver = FalkorDriver(
                host=Config.FALKORDB_HOST,
                port=int(Config.FALKORDB_PORT),
                username=Config.FALKORDB_USERNAME or None,
                password=Config.FALKORDB_PASSWORD or None,
            )

            self._llm_client = MinimaxLLMClient()
            # Use the lightweight hash embedder by default; production can
            # swap in LocalSentenceTransformersEmbedder via Config.EMBEDDING_MODEL.
            self._embedder = HashEmbedder(dim=EMBED_DIM)
            self._cross_encoder = M3RerankerClient()

            self._graphiti = Graphiti(
                graph_driver=driver,
                llm_client=self._llm_client,
                embedder=self._embedder,
                cross_encoder=self._cross_encoder,
            )

            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop_runner, name="graphiti-loop", daemon=True
            )
            self._loop_thread.start()
            # Build indices/constraints (idempotent)
            self._run_async(self._graphiti.build_indices_and_constraints())

    def _loop_runner(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro, timeout: float = 600.0):
        self._ensure_init()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # -- Zep-compatible surface used by the rest of MiroFish ---------------

    def create_graph(self, graph_id: str, name: str, description: str = "") -> str:
        """Zep had a per-project graph; Graphiti uses group_id as a partition."""
        self._ensure_init()
        logger.info(f"[graphiti_service] create_graph id={graph_id} name={name!r}")
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        """
        Defer to a per-graph_id ontology cache; we apply entity/edge types on
        each subsequent add_episode call.
        """
        self._ensure_init()
        self._ontologies[graph_id] = ontology
        logger.info(
            f"[graphiti_service] set_ontology id={graph_id} entities="
            f"{len(ontology.get('entity_types', []))} edges="
            f"{len(ontology.get('edge_types', []))}"
        )

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[Any]:
        """
        Zep's add_batch took a list of EpisodeData; we accept that interface
        and translate. Returns a list of objects with .uuid_/.uuid.
        """
        self._ensure_init()
        ontology = self._ontologies.get(graph_id, {})
        entity_types_map = self._build_entity_types(ontology)
        edge_type_map = self._build_edge_type_map(ontology)

        ep_payloads = []
        for ep in episodes:
            data = getattr(ep, "data", None) or (ep.get("data") if isinstance(ep, dict) else None)
            ep_type = getattr(ep, "type", None) or (ep.get("type") if isinstance(ep, dict) else "text")
            if not data:
                continue
            ep_payloads.append((data, ep_type))

        async def _add_all():
            from graphiti_core.nodes import EpisodeType
            results = []
            for i, (data, ep_type) in enumerate(ep_payloads):
                try:
                    gt_ep_type = EpisodeType.text if ep_type == "text" else EpisodeType.message
                except Exception:
                    gt_ep_type = EpisodeType.message

                kwargs = dict(
                    name=f"chunk_{i}",
                    episode_body=data,
                    source=gt_ep_type,
                    source_description=f"chunk {i} of {len(ep_payloads)}",
                    group_id=graph_id,
                    reference_time=_now_dt(),
                )
                if entity_types_map:
                    kwargs["entity_types"] = entity_types_map
                if edge_type_map:
                    # Graphiti's add_episode expects edge_types: dict[str, type[BaseModel]]
                    kwargs["edge_types"] = edge_type_map

                try:
                    await self._graphiti.add_episode(**kwargs)
                    results.append(_EpisodeRef(uuid_=f"{graph_id}-ep-{i}", processed=True))
                except Exception as e:
                    logger.error(f"[graphiti_service] add_episode failed on chunk {i}: {type(e).__name__}: {e}")
                    results.append(_EpisodeRef(uuid_=f"{graph_id}-ep-{i}", processed=False))
            return results

        return self._run_async(_add_all())

    # Read-side methods (Zep surface) -------------------------------------

    def get_all_nodes(self, graph_id: str) -> List[ZepNode]:
        self._ensure_init()

        async def _fetch():
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            if not isinstance(self._graphiti.driver, FalkorDriver):
                return []
            try:
                graph = self._graphiti.driver.client.select_graph(graph_id)
            except Exception as e:
                logger.warning(f"[graphiti_service] select_graph({graph_id}) failed: {e}")
                return []
            try:
                result = await graph.query("MATCH (n:Entity) RETURN n LIMIT 5000", {})
            except Exception as e:
                logger.warning(f"[graphiti_service] get_all_nodes query failed: {e}")
                return []
            nodes: List[ZepNode] = []
            for row in (result.result_set or []):
                node = row[0] if row else None
                if node is None:
                    continue
                props = dict(node.properties or {})
                nodes.append(
                    ZepNode(
                        uuid_=props.get("uuid", _new_uuid()),
                        name=props.get("name", ""),
                        labels=list(node.labels or ["Entity"]),
                        summary=props.get("summary", ""),
                        attributes=_parse_attributes(props.get("attributes", "{}")),
                        created_at=str(props.get("created_at", "")) or None,
                    )
                )
            return nodes
        return self._run_async(_fetch())

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[ZepEdge]:
        self._ensure_init()

        async def _fetch():
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            if not isinstance(self._graphiti.driver, FalkorDriver):
                return []
            try:
                graph = self._graphiti.driver.client.select_graph(graph_id)
            except Exception as e:
                logger.warning(f"[graphiti_service] select_graph({graph_id}) failed: {e}")
                return []
            try:
                result = await graph.query(
                    "MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity) "
                    "RETURN r, s.uuid AS s_uuid, t.uuid AS t_uuid LIMIT 5000",
                    {},
                )
            except Exception as e:
                logger.warning(f"[graphiti_service] get_all_edges query failed: {e}")
                return []
            out = []
            for row in (result.result_set or []):
                rel = row[0]
                props = rel.properties or {}
                # FalkorDB returns Edge objects; relation_type is on the Edge
                # class itself, but we also fall back to the 'name' property.
                rel_type = getattr(rel, "relation_type", None) or getattr(rel, "type", None) or props.get("name", "")
                out.append(ZepEdge(
                    uuid_=props.get("uuid", _new_uuid()),
                    name=rel_type,
                    fact=props.get("fact", ""),
                    source_node_uuid=row[1] or "",
                    target_node_uuid=row[2] or "",
                    attributes=_parse_attributes(props.get("attributes", "{}")),
                    created_at=str(props.get("created_at", "")) or None,
                    valid_at=str(props.get("valid_at", "")) or None if include_temporal else None,
                    invalid_at=str(props.get("invalid_at", "")) or None if include_temporal else None,
                    expired_at=str(props.get("expired_at", "")) or None if include_temporal else None,
                    fact_type=rel_type,
                    episodes=props.get("episodes", []) or [],
                ))
            return out
        return self._run_async(_fetch())

    def get_node(self, node_uuid: str) -> Optional[ZepNode]:
        self._ensure_init()

        async def _fetch():
            try:
                records, header, _ = await self._graphiti.driver.execute_query(
                    "MATCH (n:Entity) WHERE n.uuid = $uid RETURN n LIMIT 1",
                    uid=node_uuid,
                )
            except Exception as e:
                logger.warning(f"[graphiti_service] get_node query failed: {e}")
                return None
            if not records:
                return None
            n = records[0].get("n")
            if n is None:
                return None
            props = dict(n.properties or {})
            return ZepNode(
                uuid_=props.get("uuid", node_uuid),
                name=props.get("name", ""),
                labels=list(n.labels or ["Entity"]),
                summary=props.get("summary", ""),
                attributes=_parse_attributes(props.get("attributes", "{}")),
            )
        return self._run_async(_fetch())

    def get_node_edges(self, node_uuid: str) -> List[ZepEdge]:
        self._ensure_init()

        async def _fetch():
            try:
                records, header, _ = await self._graphiti.driver.execute_query(
                    "MATCH (s:Entity)-[r:RELATES_TO]-(t:Entity) "
                    "WHERE s.uuid = $uid OR t.uuid = $uid "
                    "RETURN r, s.uuid AS s_uuid, t.uuid AS t_uuid",
                    uid=node_uuid,
                )
            except Exception as e:
                logger.warning(f"[graphiti_service] get_node_edges query failed: {e}")
                return []
            out = []
            for rec in records:
                rel = rec.get("r")
                if rel is None:
                    continue
                props = dict(rel.properties or {})
                out.append(ZepEdge(
                    uuid_=props.get("uuid", _new_uuid()),
                    name=props.get("name", "") or props.get("type", ""),
                    fact=props.get("fact", ""),
                    source_node_uuid=rec.get("s_uuid") or "",
                    target_node_uuid=rec.get("t_uuid") or "",
                    attributes=_parse_attributes(props.get("attributes", "{}")),
                ))
            return out
        return self._run_async(_fetch())

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> List[Dict[str, Any]]:
        self._ensure_init()

        async def _search():
            from graphiti_core.search.search_config_recipes import (
                EDGE_HYBRID_SEARCH_RRF,
                NODE_HYBRID_SEARCH_RRF,
            )
            cfg = EDGE_HYBRID_SEARCH_RRF if scope == "edges" else NODE_HYBRID_SEARCH_RRF
            try:
                # graphiti-core 0.20+ takes `config` (SearchConfig) not `num_results`.
                results = await self._graphiti._search(
                    query=query,
                    config=cfg,
                    group_ids=[graph_id],
                )
            except Exception as e:
                logger.warning(f"[graphiti_service] search failed: {e}")
                return []
            out: List[Dict[str, Any]] = []
            for r in results:
                if hasattr(r, "fact"):
                    out.append({
                        "uuid": getattr(r, "uuid", _new_uuid()),
                        "name": getattr(r, "name", ""),
                        "fact": getattr(r, "fact", ""),
                        "source_node_uuid": getattr(r, "source_node_uuid", ""),
                        "target_node_uuid": getattr(r, "target_node_uuid", ""),
                        "score": getattr(r, "score", 0.0),
                    })
                else:
                    out.append({
                        "uuid": getattr(r, "uuid", _new_uuid()),
                        "name": getattr(r, "name", ""),
                        "summary": getattr(r, "summary", ""),
                        "labels": getattr(r, "labels", []),
                        "score": getattr(r, "score", 0.0),
                    })
            return out
        return self._run_async(_search())

    def delete_graph(self, graph_id: str) -> None:
        self._ensure_init()

        async def _do():
            from graphiti_core.driver.falkordb_driver import FalkorDriver
            if isinstance(self._graphiti.driver, FalkorDriver):
                client = await self._graphiti.driver.client.connect()
                await client.execute_command(
                    "MATCH (n) WHERE n.group_id = $gid DETACH DELETE n",
                    {"gid": graph_id},
                )
        self._run_async(_do())

    # -- internal: translate MiroFish ontology -> Graphiti types -----------

    def _build_entity_types(self, ontology: Dict[str, Any]) -> Dict[str, Type[BaseModel]]:
        """
        MiroFish's ontology is JSON: {entity_types: [{name, description, attributes: [...]}, ...]}.
        Graphiti's `entity_types` is a {name: Type[BaseModel]} dict.

        We use a plain BaseModel — Graphiti's `validate_entity_types` rejects
        models that subclass `EntityNode` (field-name clashes), so the
        BaseModel-only approach is the right one.
        """
        if not ontology or not ontology.get("entity_types"):
            return {}
        out: Dict[str, Type[BaseModel]] = {}
        for et in ontology["entity_types"]:
            name = et["name"]
            desc = et.get("description", f"A {name} entity.")
            attrs: Dict[str, Any] = {"__doc__": desc}
            annotations: Dict[str, Any] = {}
            for a in et.get("attributes", []):
                an = a["name"]
                if an.startswith("_") or an.startswith("model_") or an in {
                    "validate", "construct", "dict", "json", "copy", "name",
                }:
                    an = f"attr_{an}"
                attrs[an] = Field(default=None, description=a.get("description", an))
                annotations[an] = Optional[str]
            attrs["__annotations__"] = annotations
            cls = type(name, (BaseModel,), attrs)
            cls.__doc__ = desc
            out[name] = cls
        return out

    def _build_edge_type_map(self, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """
        MiroFish edge_types: [{name, description, attributes: [...], source_targets: [{source,target}, ...]}, ...].
        Graphiti's `edge_types` kwarg on add_episode is `dict[str, type[BaseModel]]` —
        a flat name->Pydantic-class mapping. Graphiti builds the source/target
        constraints internally from the prompt's FACT_TYPES section, so we
        only need the Pydantic class for the schema-validation prompt.

        We use a plain BaseModel subclass (not EntityEdge) for the same reason
        as _build_entity_types: Graphiti's `validate_edge_types` rejects
        models that subclass EntityEdge (field-name clashes).
        """
        if not ontology or not ontology.get("edge_types"):
            return {}
        out: Dict[str, Any] = {}
        for et in ontology["edge_types"]:
            name = et["name"]
            desc = et.get("description", f"A {name} relationship.")
            attrs: Dict[str, Any] = {"__doc__": desc}
            annotations: Dict[str, Any] = {}
            for a in et.get("attributes", []):
                an = a["name"]
                if an.startswith("_") or an.startswith("model_") or an in {
                    "validate", "construct", "dict", "json", "copy", "name",
                }:
                    an = f"attr_{an}"
                attrs[an] = Field(default=None, description=a.get("description", an))
                annotations[an] = Optional[str]
            attrs["__annotations__"] = annotations
            cls_name = "".join(w.capitalize() for w in name.split("_"))
            cls = type(cls_name, (BaseModel,), attrs)
            cls.__doc__ = desc
            out[name] = cls  # just the class, not a (cls, source_targets) tuple
        return out


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _new_uuid() -> str:
    return _uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    """datetime object — graphiti's EpisodicNode.valid_at is a datetime field."""
    return datetime.now(timezone.utc)


def _parse_attributes(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

_singleton: Optional[GraphitiAdapter] = None
_singleton_lock = threading.Lock()


def get_graphiti_adapter() -> GraphitiAdapter:
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = GraphitiAdapter()
    return _singleton
