"""Convert OpenAI chat messages into one isolated Codex turn."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CodexInput:
    base_instructions: str | None
    developer_instructions: str | None
    turn_text: str


def build_codex_input(messages: list[dict[str, Any]]) -> CodexInput:
    system_parts: list[str] = []
    developer_parts: list[str] = []
    conversation: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(str(content))
        elif role == "developer":
            developer_parts.append(str(content))
        elif role in {"user", "assistant", "tool"}:
            item = {"role": role, "content": content}
            if role == "tool" and message.get("tool_call_id"):
                item["tool_call_id"] = message["tool_call_id"]
            conversation.append(item)
        else:
            raise ValueError(f"unsupported message role: {role}")

    payload = {
        "instruction": "Respond to the conversation below. Return only the final answer.",
        "messages": conversation,
    }
    return CodexInput(
        base_instructions="\n\n".join(system_parts) or None,
        developer_instructions="\n\n".join(developer_parts) or None,
        turn_text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
