from __future__ import annotations

import json
import re
import time
from typing import Any

from .settings import settings

try:
    from app.utils.logger import get_logger
    from app.utils.llm_gate import main_llm_slot
    logger = get_logger("mirofish.local_zep.extraction")
except Exception:  # pragma: no cover - fallback for direct package use
    import logging
    from contextlib import nullcontext
    main_llm_slot = nullcontext
    logger = logging.getLogger(__name__)


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_mapping(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            cleaned = _clean_string(item)
            if cleaned:
                result[str(key)] = cleaned
        return result
    return {}


def _normalize_type_name(value: str) -> str:
    cleaned = _clean_string(value)
    if not cleaned:
        return "Entity"
    return re.sub(r"\s+", "", cleaned)


def _clean_timestamp(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _cleanup_model_json(text: str) -> str:
    cleaned = text or ""
    cleaned = cleaned.replace("\ufeff", "").replace("\u200b", "")
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned).strip()
    cleaned = re.sub(r"^Thinking Process:[\s\S]*?(?=\{|\[)", "", cleaned).strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def _repair_json(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    return repaired


def _balanced_json_objects(text: str) -> list[str]:
    objects: list[str] = []
    start = None
    depth = 0
    in_string = False
    escape = False

    for index, char in enumerate(text or ""):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start:index + 1])
                start = None

    return sorted(objects, key=len, reverse=True)


def _extract_balanced_array_after_key(text: str, key: str) -> list[Any] | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[', text)
    if not match:
        return None

    start = match.end() - 1
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(_repair_json(text[start:index + 1]))
                    return parsed if isinstance(parsed, list) else None
                except json.JSONDecodeError:
                    return None

    return None


def _parse_payload_lenient(text: str) -> dict[str, Any] | None:
    cleaned = _cleanup_model_json(text)
    candidates = [cleaned]
    candidates.extend(_cleanup_model_json(block) for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text or "", flags=re.IGNORECASE))
    candidates.extend(_balanced_json_objects(cleaned))

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start:end + 1])

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(_repair_json(candidate))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    loose: dict[str, Any] = {}
    entities = _extract_balanced_array_after_key(cleaned, "entities")
    edges = _extract_balanced_array_after_key(cleaned, "edges")
    if entities is not None:
        loose["entities"] = entities
    if edges is not None:
        loose["edges"] = edges
    return loose or None


class GraphExtractor:
    """LLM-backed entity and relation extraction constrained by ontology."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model_name = model_name or settings.llm_model_name

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")

        from openai import OpenAI

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def extract(self, text: str, ontology: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
        if not text or not text.strip():
            return {"entities": [], "edges": []}

        ontology = ontology or {"entity_types": [], "edge_types": []}
        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])

        entity_type_names = [item.get("name", "Entity") for item in entity_types]
        edge_type_names = [item.get("name", "RELATED_TO") for item in edge_types]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an information extraction engine for a local temporal knowledge graph. "
                    "Return strict JSON with keys entities and edges. "
                    "Only use ontology entity types and edge types provided by the user. "
                    "Do not invent unsupported types. Keep summaries concise."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract graph updates from the text below.\n\n"
                    "Ontology:\n"
                    f"{ontology}\n\n"
                    "JSON schema:\n"
                    "{\n"
                    '  "entities": [\n'
                    '    {"name": "entity name", "type": "one of ontology entity types", '
                    '"summary": "short summary", "attributes": {"attr": "value"}}\n'
                    "  ],\n"
                    '  "edges": [\n'
                    '    {"name": "one of ontology edge types", "source": "entity name", '
                    '"target": "entity name", "fact": "atomic factual sentence", '
                    '"attributes": {"attr": "value"}, "valid_at": "optional RFC3339 time"}\n'
                    "  ]\n"
                    "}\n\n"
                    "Rules:\n"
                    f"- Allowed entity types: {entity_type_names or ['Entity']}\n"
                    f"- Allowed edge types: {edge_type_names or ['RELATED_TO']}\n"
                    "- Use exact entity names from the text when possible.\n"
                    "- Omit any item you are not reasonably confident about.\n"
                    "- Every edge source and target must reference an entity name.\n\n"
                    "- If a fact includes an explicit real-world start time, put it in valid_at. "
                    "Otherwise omit valid_at and the episode created_at will be used.\n\n"
                    "Text:\n"
                    f"{text}"
                ),
            },
        ]

        payload: dict[str, Any] | None = None
        last_content = ""
        max_retries = max(0, settings.local_zep_extract_max_retries)
        for attempt in range(max_retries + 1):
            attempt_messages = list(messages)
            if attempt > 0:
                attempt_messages.append({
                    "role": "user",
                    "content": (
                        "Retry: return only compact valid JSON with top-level keys entities and edges. "
                        "No markdown, no comments, no thinking text. Keep at most 20 entities and 20 edges."
                    ),
                })

            try:
                with main_llm_slot():
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=attempt_messages,
                        temperature=0.1,
                        max_tokens=settings.local_zep_extract_max_output_tokens,
                        response_format={"type": "json_object"},
                    )
                last_content = response.choices[0].message.content or "{}"
                payload = _parse_payload_lenient(last_content)
                if payload is not None:
                    if attempt > 0:
                        logger.info("Graph extraction JSON recovered after retry %s/%s", attempt, max_retries)
                    break
                logger.warning(
                    "Graph extraction returned invalid JSON on attempt %s/%s: %s",
                    attempt + 1,
                    max_retries + 1,
                    _cleanup_model_json(last_content)[:1000],
                )
            except Exception as exc:
                logger.warning(
                    "Graph extraction LLM call failed on attempt %s/%s: %s",
                    attempt + 1,
                    max_retries + 1,
                    str(exc)[:1000],
                )

            if attempt < max_retries:
                time.sleep(min(2.0, 0.5 * (attempt + 1)))

        if payload is None:
            logger.error(
                "Graph extraction failed after retries; skipping text chunk. Last response: %s",
                _cleanup_model_json(last_content)[:2000],
            )
            return {"entities": [], "edges": []}

        entities = []
        for raw_entity in payload.get("entities", []):
            if not isinstance(raw_entity, dict):
                continue
            name = _clean_string(raw_entity.get("name"))
            entity_type = _normalize_type_name(raw_entity.get("type"))
            if not name:
                continue
            if entity_types and entity_type not in entity_type_names:
                continue
            entities.append(
                {
                    "name": name,
                    "type": entity_type,
                    "summary": _clean_string(raw_entity.get("summary")),
                    "attributes": _coerce_mapping(raw_entity.get("attributes")),
                }
            )

        edges = []
        for raw_edge in payload.get("edges", []):
            if not isinstance(raw_edge, dict):
                continue
            name = _normalize_type_name(raw_edge.get("name"))
            source = _clean_string(raw_edge.get("source"))
            target = _clean_string(raw_edge.get("target"))
            fact = _clean_string(raw_edge.get("fact"))
            if not name or not source or not target:
                continue
            if edge_types and name not in edge_type_names:
                continue
            if not fact:
                fact = f"{source} {name} {target}"
            edges.append(
                {
                    "name": name,
                    "source": source,
                    "target": target,
                    "fact": fact,
                    "attributes": _coerce_mapping(raw_edge.get("attributes")),
                    "valid_at": _clean_timestamp(raw_edge.get("valid_at")),
                }
            )

        return {"entities": entities, "edges": edges}
