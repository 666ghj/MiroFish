"""Local Chat Completions facade for a Codex CLI proof of concept.

This is limited to non-streaming text and function calls. It uses Codex's saved
ChatGPT login; it does not read, copy, or expose Codex credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


MAX_REQUEST_BYTES = 256 * 1024
TOKEN_ENV = "MIROFISH_CODEX_BRIDGE_TOKEN"
TOOL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments_json": {"type": "string"},
                },
                "required": ["name", "arguments_json"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["content", "tool_calls"],
    "additionalProperties": False,
}


def validate_request(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object")
    if body.get("stream"):
        raise ValueError("Streaming is not supported by this proof of concept")
    if body.get("functions"):
        raise ValueError("Legacy functions are not supported")
    response_format = body.get("response_format")
    if response_format is not None and response_format != {"type": "json_object"}:
        raise ValueError("Only response_format=json_object is supported")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a nonempty array")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {
            "system", "developer", "user", "assistant", "tool"
        }:
            raise ValueError("Unsupported message role")
        if message.get("content") is not None and not isinstance(message["content"], str):
            raise ValueError("Only text message content is supported")
        if message.get("content") is None and not message.get("tool_calls"):
            raise ValueError("A message needs text or tool calls")
    tools = body.get("tools") or []
    if not isinstance(tools, list):
        raise ValueError("tools must be an array")
    for tool in tools:
        if (
            not isinstance(tool, dict)
            or tool.get("type") != "function"
            or not isinstance(tool.get("function"), dict)
            or not isinstance(tool["function"].get("name"), str)
            or not isinstance(tool["function"].get("parameters"), dict)
        ):
            raise ValueError("Only function tools with JSON parameters are supported")
    if tools and response_format is not None:
        raise ValueError("Tool calls and response_format cannot be combined")
    return body


def build_prompt(body: dict[str, Any]) -> str:
    instruction = (
        "Actúa como el modelo de texto de MiroFish. Responde al último mensaje "
        "según la conversación siguiente. Los mensajes pueden describir herramientas "
        "textuales de MiroFish. Si piden un bloque <tool_call>, escríbelo exactamente "
        "como texto: el backend ejecutará esa herramienta y te devolverá el resultado "
        "en un mensaje posterior. No intentes ejecutar herramientas de Codex ni leer "
        "archivos locales. Devuelve únicamente la respuesta destinada a MiroFish."
    )
    if body.get("response_format") == {"type": "json_object"}:
        instruction += " La respuesta debe ser un único objeto JSON válido, sin Markdown."
    if body.get("tools"):
        instruction = (
            "Eres el motor de selección de acciones de MiroFish. Lee la conversación "
            "y las funciones disponibles. NO ejecutes herramientas por tu cuenta. "
            "Devuelve un objeto con content (texto, puede ser vacío) y tool_calls. "
            "Para realizar una acción, elige una función disponible y escribe "
            "sus argumentos como objeto JSON serializado en arguments_json. "
            "Elige exactamente una acción cuando tool_choice sea auto o required. "
            "Si tool_choice es none, devuelve tool_calls vacío. "
            "Respeta los campos obligatorios y tipos de la función."
        )
    payload = {
        "messages": body["messages"],
        "tools": body.get("tools") or [],
        "tool_choice": body.get("tool_choice", "auto"),
    }
    return instruction + "\n\nSolicitud de MiroFish (JSON):\n" + json.dumps(
        payload, ensure_ascii=False
    )


def codex_environment() -> dict[str, str]:
    env = os.environ.copy()
    # A dummy MiroFish key or a separately configured API key must never
    # override the CLI's saved ChatGPT login for this proof of concept.
    for name in (
        "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE_URL",
        "LLM_API_KEY", "LLM_BASE_URL", "LLM_BOOST_API_KEY", "ZEP_API_KEY",
        "MIROFISH_CODEX_BRIDGE_TOKEN",
    ):
        env.pop(name, None)
    return env


def verify_chatgpt_login(codex_binary: str) -> None:
    result = subprocess.run(
        [codex_binary, "login", "status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        env=codex_environment(),
        check=False,
    )
    # Codex CLI versions differ in whether status is written to stdout or stderr.
    status_text = result.stdout + result.stderr
    if result.returncode != 0 or "Logged in using ChatGPT" not in status_text:
        raise RuntimeError("Codex CLI must be signed in with ChatGPT")


def run_codex(
    prompt: str, *, timeout: int, model: str | None = None,
    output_schema: dict[str, Any] | None = None,
) -> str:
    codex_binary = shutil.which("codex")
    if not codex_binary:
        raise RuntimeError("codex CLI was not found")
    command = [
        codex_binary,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
    ]
    if model:
        command.extend(["--model", model])
    with tempfile.TemporaryDirectory(prefix="mirofish-codex-bridge-") as workdir:
        if output_schema is not None:
            schema_path = os.path.join(workdir, "answer.schema.json")
            with open(schema_path, "w", encoding="utf-8") as schema_file:
                json.dump(output_schema, schema_file)
            command.extend(["--output-schema", schema_path])
        command.extend(["--cd", workdir, "-"])
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=workdir,
            env=codex_environment(),
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    if result.returncode != 0:
        raise RuntimeError("Codex CLI did not complete the request")
    answer = result.stdout.strip()
    if not answer:
        raise RuntimeError("Codex CLI returned an empty response")
    return answer


def parse_tool_answer(answer: str, tools: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    try:
        parsed = json.loads(answer)
        content = parsed["content"]
        calls = parsed["tool_calls"]
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError("Codex returned invalid tool selection JSON") from error
    if not isinstance(content, str) or not isinstance(calls, list):
        raise RuntimeError("Codex returned invalid tool selection fields")
    allowed_names = {tool["function"]["name"] for tool in tools}
    normalized = []
    for call in calls:
        if not isinstance(call, dict) or call.get("name") not in allowed_names:
            raise RuntimeError("Codex selected an unavailable function")
        try:
            arguments = json.loads(call["arguments_json"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Codex returned invalid function arguments") from error
        if not isinstance(arguments, dict):
            raise RuntimeError("Function arguments must be a JSON object")
        normalized.append({
            "id": f"call_{uuid.uuid4().hex}",
            "type": "function",
            "function": {"name": call["name"], "arguments": json.dumps(arguments, ensure_ascii=False)},
        })
    return content, normalized


def completion_payload(
    answer: str, model: str, tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content, tool_calls = parse_tool_answer(answer, tools) if tools else (answer, [])
    message: dict[str, Any] = {
        "role": "assistant",
        "content": (content or None) if tool_calls else content,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": f"chatcmpl-codex-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
    }


class BridgeHandler(BaseHTTPRequestHandler):
    token: str = ""
    timeout: int = 240
    codex_model: str | None = None

    def _json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
        if self.path == "/health":
            self._json(200, {"status": "ready", "provider": "codex_cli_chatgpt"})
        else:
            self._json(404, {"error": {"message": "Not found"}})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler interface
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"message": "Not found"}})
            return
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            self._json(401, {"error": {"message": "Unauthorized"}})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_REQUEST_BYTES:
                raise ValueError("Invalid or oversized request")
            body = validate_request(json.loads(self.rfile.read(size)))
            answer = run_codex(
                build_prompt(body), timeout=self.timeout, model=self.codex_model,
                output_schema=TOOL_OUTPUT_SCHEMA if body.get("tools") else None,
            )
            self._json(200, completion_payload(
                answer, str(body.get("model", "codex-bridge")), body.get("tools")
            ))
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": {"message": str(error)}})
        except subprocess.TimeoutExpired:
            self._json(504, {"error": {"message": "Codex CLI timed out"}})
        except RuntimeError as error:
            self._json(502, {"error": {"message": str(error)}})

    def log_message(self, format_string: str, *args: Any) -> None:
        # Avoid recording prompts, authorization headers, or local account data.
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--model", default=None, help="Codex CLI model; default uses CLI selection")
    args = parser.parse_args()
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        parser.error(f"Set {TOKEN_ENV} before starting the bridge")
    if not 1 <= args.port <= 65535 or args.timeout < 1:
        parser.error("port and timeout must be positive")
    codex_binary = shutil.which("codex")
    if not codex_binary:
        parser.error("codex CLI was not found")
    verify_chatgpt_login(codex_binary)
    BridgeHandler.token = token
    BridgeHandler.timeout = args.timeout
    BridgeHandler.codex_model = args.model
    # Both OASIS platforms make concurrent model requests.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), BridgeHandler)
    print(f"Codex bridge listening on http://127.0.0.1:{args.port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
