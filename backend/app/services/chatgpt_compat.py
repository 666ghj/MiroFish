"""Translate local Chat Completions calls into ChatGPT-plan Responses calls."""

from __future__ import annotations

import json
import time
import uuid

import httpx

from . import chatgpt_signin


def _input_messages(messages: list[dict]) -> list[dict]:
    result = []
    for message in messages:
        role = message.get("role")
        if role in {"system", "developer", "user", "assistant"}:
            if role == "system":
                role = "developer"
            if message.get("content") is not None:
                result.append({"role": role, "content": message["content"]})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                result.append({
                    "type": "function_call", "call_id": call["id"],
                    "name": f"mirofish.{function['name']}",
                    "arguments": function["arguments"],
                })
        elif role == "tool":
            result.append({
                "type": "function_call_output", "call_id": message["tool_call_id"],
                "output": message.get("content") or "",
            })
        else:
            raise ValueError("Rol de mensaje no compatible")
    return result


def _tools(tools: list[dict]) -> list[dict]:
    if not tools:
        return []
    functions = []
    for tool in tools:
        if tool.get("type") != "function" or not isinstance(tool.get("function"), dict):
            raise ValueError("Solo se admiten herramientas de función")
        item = tool["function"]
        functions.append({
            "type": "function", "name": item["name"],
            "description": item.get("description", ""),
            "parameters": item.get("parameters", {"type": "object", "properties": {}}),
        })
    return [{"type": "namespace", "name": "mirofish", "description": "Acciones de la simulación MiroFish", "tools": functions}]


def _payload(body: dict) -> dict:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("Se requiere una lista de mensajes")
    if body.get("stream"):
        raise ValueError("El cliente local debe solicitar respuesta sin streaming")
    prompt = _input_messages(messages)
    if body.get("response_format") == {"type": "json_object"}:
        prompt.insert(0, {"role": "developer", "content": "Responde únicamente con un objeto JSON válido."})
    tools = _tools(body.get("tools") or [])
    payload = {
        "model": body["model"], "input": prompt, "store": False, "stream": True,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = body.get("tool_choice", "auto")
    return payload


def _completed_response(events: list[dict]) -> dict:
    for event in reversed(events):
        if event.get("type") == "response.completed":
            return event["response"]
        if event.get("type") in {"response.failed", "response.incomplete"}:
            code = (event.get("response", {}).get("error") or {}).get("code", "incomplete")
            raise RuntimeError(f"La respuesta de ChatGPT no se completó ({code})")
    raise RuntimeError("La transmisión de ChatGPT terminó sin confirmación")


def _chat_completion(response: dict, model: str) -> dict:
    texts = []
    calls = []
    for item in response.get("output", []):
        if item.get("type") == "message":
            texts.extend(part.get("text", "") for part in item.get("content", []) if part.get("type") == "output_text")
        elif item.get("type") == "function_call":
            name = item.get("name", "")
            if name.startswith("mirofish."):
                name = name[len("mirofish."):]
            calls.append({
                "id": item["call_id"], "type": "function",
                "function": {"name": name, "arguments": item.get("arguments", "{}")},
            })
    message = {"role": "assistant", "content": "".join(texts) or None}
    if calls:
        message["tool_calls"] = calls
    if not calls and message["content"] is None:
        raise RuntimeError("ChatGPT devolvió una respuesta vacía")
    return {
        "id": f"chatcmpl-siwc-{uuid.uuid4().hex}", "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
    }


def complete(body: dict) -> dict:
    payload = _payload(body)
    token = chatgpt_signin.access_token()
    events = []
    try:
        with httpx.Client(timeout=240, follow_redirects=False) as client:
            with client.stream(
                "POST", f"{chatgpt_signin.RESOURCE}/responses",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"ChatGPT rechazó la solicitud (HTTP {response.status_code})")
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data != "[DONE]":
                            event = json.loads(data)
                            if event.get("type") in {"response.completed", "response.failed", "response.incomplete"}:
                                events.append(event)
    except (httpx.HTTPError, json.JSONDecodeError) as error:
        raise RuntimeError("Se interrumpió la respuesta de ChatGPT") from error
    return _chat_completion(_completed_response(events), payload["model"])
