from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


@dataclass
class PersonaRecord:
    agent_id: int
    name: str
    persona: str
    profession: Optional[str] = None
    bio: Optional[str] = None


@dataclass
class MemoryDigest:
    text: str
    available: bool = True


class MemoryProvider(Protocol):
    def get_digest(self, agent_id: int, max_chars: int = 2000) -> MemoryDigest: ...


class StakeholderInterviewer:
    def __init__(self, llm, memory: MemoryProvider, language: str = "de"):
        self.llm = llm
        self.memory = memory
        self.language = language

    def _system_prompt(self, persona: PersonaRecord, digest: MemoryDigest, schema_hint: str) -> str:
        memory_block = digest.text if digest.available else "[no simulation memory available]"
        lang_note = "Antworte ausschließlich auf Deutsch." if self.language == "de" else "Answer in English."
        return (
            f"You are {persona.name}. {persona.persona}\n\n"
            "You are answering a survey about the future of German fisheries. "
            "Answer strictly in character based on your background, values, and what you experienced "
            "during the simulated social media discourse summarised below.\n\n"
            f"--- simulation memory digest ---\n{memory_block}\n--- end ---\n\n"
            f"{lang_note} Return JSON ONLY matching this schema:\n{schema_hint}"
        )

    def ask_in_character(
        self,
        persona: PersonaRecord,
        user_prompt: str,
        schema_hint: str,
        *,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        validate: Optional[Callable[[dict], Optional[dict]]] = None,
    ) -> dict:
        digest = self.memory.get_digest(persona.agent_id)
        messages = [
            {"role": "system", "content": self._system_prompt(persona, digest, schema_hint)},
            {"role": "user", "content": user_prompt},
        ]
        out = self.llm.chat_json(messages=messages, temperature=temperature, max_tokens=max_tokens)
        if validate is not None:
            validated = validate(out)
            if validated is not None:
                return validated
            messages.append({"role": "assistant", "content": str(out)})
            messages.append({"role": "user", "content":
                "Your previous response did not match the required schema. "
                f"Return ONLY valid JSON matching: {schema_hint}"})
            out = self.llm.chat_json(messages=messages, temperature=0.0, max_tokens=max_tokens)
            validated = validate(out)
            if validated is None:
                raise ValueError(f"agent {persona.agent_id}: schema violation after retry")
            return validated
        return out
