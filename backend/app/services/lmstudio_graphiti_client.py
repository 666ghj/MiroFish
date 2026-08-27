"""LM Studio structured-output compatibility for reasoning models."""

from __future__ import annotations

import json
from typing import Any

from graphiti_core.llm_client.openai_generic_client import DEFAULT_MODEL, OpenAIGenericClient


class LMStudioGraphitiClient(OpenAIGenericClient):
    """Disable reasoning only for Graphiti JSON extraction requests."""

    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[Any] | None = None,
        max_tokens: int = 16384,
        model_size: Any = None,
    ) -> dict[str, Any]:
        openai_messages = []
        for message in messages:
            content = self._clean_input(message.content)
            if message.role in {"user", "system"}:
                openai_messages.append({"role": message.role, "content": content})

        response_format: dict[str, Any] = {"type": "json_object"}
        if response_model is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": getattr(response_model, "__name__", "structured_response"),
                    "schema": response_model.model_json_schema(),
                },
            }
        response = await self.client.chat.completions.create(
            model=self.model or DEFAULT_MODEL,
            messages=openai_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=response_format,
            reasoning_effort="none",
        )
        result = response.choices[0].message.content or ""
        return json.loads(result)
