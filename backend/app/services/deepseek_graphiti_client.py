"""DeepSeek compatibility for Graphiti structured JSON responses."""

from __future__ import annotations

import copy
import json
from typing import Any

from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient


class DeepSeekGraphitiClient(OpenAIGenericClient):
    """Use DeepSeek's JSON Object mode while preserving Graphiti schemas."""

    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[Any] | None = None,
        max_tokens: int = 8192,
        model_size: Any = None,
    ) -> dict[str, Any]:
        compatible_messages = copy.deepcopy(messages)
        if response_model is not None:
            schema = json.dumps(
                response_model.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            compatible_messages[-1].content += (
                "\nReturn valid JSON matching this JSON Schema exactly:\n" + schema
            )

        return await super()._generate_response(
            compatible_messages,
            response_model=None,
            max_tokens=max_tokens,
            model_size=model_size,
        )
