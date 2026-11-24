"""
Idea Studio chat: builds the model conversation and streams the co-founder's reply.

PROVISIONAL: the system prompt below is a placeholder so the streaming plumbing can be
exercised end to end. The real question strategy, panel extraction, and evidence rules
will be set from the Idea Studio deep research (deep_researchs/*.md).
"""

from typing import Any, Dict, Iterator, List, Optional

from ..utils.llm_client import LLMClient

HISTORY_LIMIT = 30   # most recent messages sent to the model

SYSTEM_PROMPT = """You are an experienced startup co-founder helping an early-stage founder think through
an idea. Be warm but honest. Ask one focused question at a time, push back on weak assumptions
with reasons, and never invent competitors, numbers, or facts; say when you are unsure.
Keep replies short (under 150 words). Never use em dashes."""


def build_messages(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    recent = [m for m in history if m.get('role') in ('user', 'assistant')][-HISTORY_LIMIT:]
    return [{'role': 'system', 'content': SYSTEM_PROMPT}] + [
        {'role': m['role'], 'content': m['content']} for m in recent
    ]


def stream_reply(history: List[Dict[str, Any]], llm: Optional[LLMClient] = None) -> Iterator[str]:
    """Yield the assistant reply in text chunks. Raises if the LLM is unavailable."""
    client = llm or LLMClient()
    yield from client.chat_stream(build_messages(history), temperature=0.6, max_tokens=600)
