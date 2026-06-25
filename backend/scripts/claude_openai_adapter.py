"""
Claude Code -> OpenAI-compatible adapter.

Exposes a minimal OpenAI Chat Completions API (`POST /v1/chat/completions`,
`GET /v1/models`) that fulfils each request by shelling out to the local
`claude` CLI in headless print mode (`claude -p ... --output-format json`).

This lets any OpenAI-SDK client (MiroFish, OASIS, etc.) "use Claude Code as the
LLM" without an external API key — it reuses the CLI's own credentials.

Usage:
    python claude_openai_adapter.py --port 8787 --model claude-opus-4-8

Then point the client at:
    LLM_BASE_URL=http://127.0.0.1:8787/v1
    LLM_API_KEY=sk-anything            # ignored, just must be non-empty
    LLM_MODEL_NAME=claude-opus-4-8

Notes:
  * temperature / max_tokens are accepted but not forwarded (the headless CLI
    does not expose them); they are ignored.
  * response_format={"type":"json_object"} is honoured by instructing the model
    to emit raw JSON only.
  * Stdlib only — no extra dependencies.
"""

import argparse
import json
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "claude-opus-4-8"
CLAUDE_TIMEOUT_S = 600


def _flatten_messages(messages, force_json):
    """Turn OpenAI chat messages into (system_prompt, user_prompt)."""
    system_parts, convo_parts = [], []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):  # OpenAI content-parts form
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            convo_parts.append(f"[assistant]\n{content}")
        else:
            convo_parts.append(content)

    system_prompt = "\n\n".join(p for p in system_parts if p).strip()
    user_prompt = "\n\n".join(p for p in convo_parts if p).strip()
    if force_json:
        user_prompt += (
            "\n\nIMPORTANT: Respond with ONLY a single valid JSON object. "
            "No markdown, no code fences, no commentary."
        )
    return system_prompt, user_prompt


def _call_claude(system_prompt, user_prompt, model):
    cmd = ["claude", "-p", "--output-format", "json", "--model", model]
    if system_prompt:
        # Replace the default agent system prompt with the caller's role prompt.
        cmd += ["--system-prompt", system_prompt]
    proc = subprocess.run(
        cmd,
        input=user_prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({proc.returncode}): {proc.stderr[:2000]}")
    payload = json.loads(proc.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude error: {payload.get('result')}")
    return payload.get("result", ""), payload.get("usage", {})


class Handler(BaseHTTPRequestHandler):
    server_version = "ClaudeOpenAIAdapter/1.0"
    default_model = DEFAULT_MODEL

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter logging
        print("[adapter] " + (fmt % args))

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {
                "object": "list",
                "data": [{"id": self.default_model, "object": "model", "owned_by": "claude-code"}],
            })
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
            messages = req.get("messages", [])
            model = req.get("model") or self.default_model
            force_json = (req.get("response_format") or {}).get("type") == "json_object"
            system_prompt, user_prompt = _flatten_messages(messages, force_json)
            text, usage = _call_claude(system_prompt, user_prompt, model)
        except Exception as e:  # noqa: BLE001 - surface as OpenAI-style error
            self._send(500, {"error": {"message": str(e), "type": "adapter_error"}})
            return

        self._send(200, {
            "id": "chatcmpl-" + uuid.uuid4().hex[:24],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    Handler.default_model = args.model
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[adapter] Claude->OpenAI adapter on http://{args.host}:{args.port}/v1 (model={args.model})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
