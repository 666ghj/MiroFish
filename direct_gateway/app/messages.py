from __future__ import annotations

from typing import Any

from .schema import normalize_output_schema


def build_responses_payload(request: dict[str, Any], model: str) -> dict[str, Any]:
    instructions = []
    items = []
    for message in request.get("messages", []):
        role = message.get("role")
        content = message.get("content", "")
        if role in {"system", "developer"}:
            instructions.append(str(content))
        elif role in {"user", "assistant"}:
            items.append({"role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": str(content)}]})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": message.get("tool_call_id", ""), "output": str(content)})
        else:
            raise ValueError(f"unsupported message role: {role}")
    payload = {"model": model, "instructions": "\n\n".join(instructions), "input": items, "store": False, "stream": True}
    response_format = request.get("response_format") or {"type": "text"}
    if response_format.get("type") == "json_object":
        payload["text"] = {"format": {"type": "json_object"}}
    elif response_format.get("type") == "json_schema":
        details = response_format.get("json_schema") or {}
        schema = details.get("schema")
        if not isinstance(schema, dict):
            raise ValueError("json_schema response format requires a schema")
        payload["text"] = {"format": {"type": "json_schema", "name": details.get("name", "response"), "strict": True, "schema": normalize_output_schema(schema)}}
    return payload
