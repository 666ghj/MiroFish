"""Send one short MiroFish LLMClient request through the local Codex bridge."""

from __future__ import annotations

import os

from app.utils.llm_client import LLMClient


def main() -> None:
    token = os.environ.get("MIROFISH_CODEX_BRIDGE_TOKEN")
    if not token:
        raise SystemExit("MIROFISH_CODEX_BRIDGE_TOKEN is required")
    client = LLMClient(
        api_key=token,
        base_url="http://127.0.0.1:8765/v1",
        model="codex-bridge",
    )
    answer = client.chat(
        [{"role": "user", "content": "Responde exactamente en español: puente funcionando"}],
        temperature=0,
        max_tokens=50,
    )
    if not answer:
        raise SystemExit("MiroFish received an empty answer")
    print(f"MiroFish LLMClient recibió: {answer}")


if __name__ == "__main__":
    main()
