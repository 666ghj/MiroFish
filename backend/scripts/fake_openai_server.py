"""
Minimal OpenAI-compatible fake server for local graph E2E tests.

Implements:
- POST /v1/chat/completions
- POST /v1/embeddings
- POST /v1/rerank
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


FIXED_ONTOLOGY = {
    "entity_types": [
        {
            "name": "Journalist",
            "description": "A news reporter or editor active in public discourse.",
            "attributes": [{"name": "role", "type": "text", "description": "Journalism role"}],
            "examples": ["Alice"],
        },
        {
            "name": "MediaOutlet",
            "description": "A media organization publishing reports and commentary.",
            "attributes": [{"name": "org_name", "type": "text", "description": "Media brand"}],
            "examples": ["DailyNews"],
        },
        {
            "name": "Ngo",
            "description": "A civil society or advocacy organization.",
            "attributes": [{"name": "mission", "type": "text", "description": "Primary mission"}],
            "examples": ["GreenFuture"],
        },
        {
            "name": "Company",
            "description": "A commercial company participating in the issue.",
            "attributes": [{"name": "industry", "type": "text", "description": "Industry sector"}],
            "examples": ["PolluteCorp"],
        },
        {
            "name": "Official",
            "description": "A government or public official making responses.",
            "attributes": [{"name": "title", "type": "text", "description": "Official title"}],
            "examples": ["Mayor Lee"],
        },
        {
            "name": "Citizen",
            "description": "A member of the public commenting on the issue.",
            "attributes": [{"name": "location", "type": "text", "description": "Location"}],
            "examples": ["Concerned resident"],
        },
        {
            "name": "Expert",
            "description": "An expert or scholar adding analysis.",
            "attributes": [{"name": "specialty", "type": "text", "description": "Area of expertise"}],
            "examples": ["Policy researcher"],
        },
        {
            "name": "CommunityGroup",
            "description": "A community or activist group involved in the issue.",
            "attributes": [{"name": "focus", "type": "text", "description": "Group focus"}],
            "examples": ["Local advocates"],
        },
        {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [{"name": "full_name", "type": "text", "description": "Full name"}],
            "examples": ["ordinary citizen"],
        },
        {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [{"name": "org_name", "type": "text", "description": "Organization name"}],
            "examples": ["generic organization"],
        },
    ],
    "edge_types": [
        {
            "name": "WORKS_FOR",
            "description": "Employment or affiliation relation.",
            "source_targets": [{"source": "Journalist", "target": "MediaOutlet"}],
            "attributes": [],
        },
        {
            "name": "REPORTS_ON",
            "description": "Coverage relation for public reporting.",
            "source_targets": [
                {"source": "MediaOutlet", "target": "Ngo"},
                {"source": "MediaOutlet", "target": "Company"},
                {"source": "Journalist", "target": "Ngo"},
            ],
            "attributes": [],
        },
        {
            "name": "SUPPORTS",
            "description": "Supportive stance relation.",
            "source_targets": [
                {"source": "Journalist", "target": "Ngo"},
                {"source": "Citizen", "target": "Ngo"},
                {"source": "Official", "target": "Organization"},
            ],
            "attributes": [],
        },
        {
            "name": "OPPOSES",
            "description": "Opposing stance relation.",
            "source_targets": [
                {"source": "Company", "target": "Ngo"},
                {"source": "Organization", "target": "Organization"},
            ],
            "attributes": [],
        },
        {
            "name": "RESPONDS_TO",
            "description": "A public response to another actor.",
            "source_targets": [
                {"source": "Official", "target": "Journalist"},
                {"source": "Organization", "target": "MediaOutlet"},
            ],
            "attributes": [],
        },
        {
            "name": "COLLABORATES_WITH",
            "description": "Cooperation relation between actors.",
            "source_targets": [
                {"source": "Organization", "target": "Organization"},
                {"source": "Ngo", "target": "CommunityGroup"},
            ],
            "attributes": [],
        },
    ],
    "analysis_summary": "Fake ontology for local graph integration testing.",
}


def _embedding_for_text(text: str) -> list[float]:
    digest = hashlib.sha256((text or "").encode("utf-8")).digest()
    values = []
    for index in range(8):
        chunk = digest[index * 4:(index + 1) * 4]
        raw = int.from_bytes(chunk, "big")
        values.append((raw % 1000) / 1000.0)
    return values


def _rerank_score(query: str, document: str) -> float:
    query_tokens = set((query or "").lower().replace(".", " ").replace(",", " ").split())
    document_tokens = set((document or "").lower().replace(".", " ").replace(",", " ").split())
    if not query_tokens or not document_tokens:
        return 0.0
    overlap = len(query_tokens.intersection(document_tokens)) / len(query_tokens)
    exact_bonus = 0.4 if (query or "").lower() in (document or "").lower() else 0.0
    return min(1.0, overlap + exact_bonus)


def _build_extraction_payload(text: str) -> dict:
    normalized = (text or "").lower()
    entities = []
    edges = []

    if "alice" in normalized:
        entities.append({
            "name": "Alice",
            "type": "Journalist",
            "summary": "Journalist covering the environmental dispute.",
            "attributes": {"role": "journalist"},
        })
    if "dailynews" in normalized:
        entities.append({
            "name": "DailyNews",
            "type": "MediaOutlet",
            "summary": "Media outlet reporting on the issue.",
            "attributes": {"org_name": "DailyNews"},
        })
    if "greenfuture" in normalized:
        entities.append({
            "name": "GreenFuture",
            "type": "Ngo",
            "summary": "Environmental organization active in the conflict.",
            "attributes": {"mission": "environmental advocacy"},
        })
    if "pollutecorp" in normalized:
        entities.append({
            "name": "PolluteCorp",
            "type": "Company",
            "summary": "Company opposing GreenFuture's campaign.",
            "attributes": {"industry": "manufacturing"},
        })
    if "mayor lee" in normalized:
        entities.append({
            "name": "Mayor Lee",
            "type": "Official",
            "summary": "Public official responding to media coverage.",
            "attributes": {"title": "Mayor"},
        })

    if {"alice", "dailynews"} <= set(normalized.replace(".", " ").replace(",", " ").split()):
        edges.append({
            "name": "WORKS_FOR",
            "source": "Alice",
            "target": "DailyNews",
            "fact": "Alice works for DailyNews.",
            "attributes": {},
        })
    if "dailynews" in normalized and "greenfuture" in normalized:
        edges.append({
            "name": "REPORTS_ON",
            "source": "DailyNews",
            "target": "GreenFuture",
            "fact": "DailyNews reports on GreenFuture.",
            "attributes": {},
        })
    if "alice supports greenfuture" in normalized or ("alice" in normalized and "supports greenfuture" in normalized):
        edges.append({
            "name": "SUPPORTS",
            "source": "Alice",
            "target": "GreenFuture",
            "fact": "Alice supports GreenFuture.",
            "attributes": {},
        })
    if "alice opposes greenfuture" in normalized:
        edges.append({
            "name": "OPPOSES",
            "source": "Alice",
            "target": "GreenFuture",
            "fact": "Alice opposes GreenFuture.",
            "attributes": {},
        })
    if "pollutecorp opposes greenfuture" in normalized or ("pollutecorp" in normalized and "opposes greenfuture" in normalized):
        edges.append({
            "name": "OPPOSES",
            "source": "PolluteCorp",
            "target": "GreenFuture",
            "fact": "PolluteCorp opposes GreenFuture.",
            "attributes": {},
        })
    if "mayor lee responds to alice" in normalized or ("mayor lee" in normalized and "responds to alice" in normalized):
        edges.append({
            "name": "RESPONDS_TO",
            "source": "Mayor Lee",
            "target": "Alice",
            "fact": "Mayor Lee responds to Alice.",
            "attributes": {},
        })

    return {"entities": entities, "edges": edges}


def _chat_response(messages: list[dict]) -> str:
    system = "\n".join(message.get("content", "") for message in messages if message.get("role") == "system")
    user = "\n".join(message.get("content", "") for message in messages if message.get("role") == "user")

    if "本体设计专家" in system or "正好输出10个实体类型" in user:
        return json.dumps(FIXED_ONTOLOGY, ensure_ascii=False)

    if "Extract graph updates from the text below" in user:
        return json.dumps(_build_extraction_payload(user), ensure_ascii=False)

    return json.dumps({"message": "fake-server-default-response"}, ensure_ascii=False)


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    server_version = "FakeOpenAI/0.1"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        if self.path == "/v1/chat/completions":
            response = {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": _chat_response(payload.get("messages", [])),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
            self._write_json(200, response)
            return

        if self.path == "/v1/embeddings":
            inputs = payload.get("input", [])
            if not isinstance(inputs, list):
                inputs = [inputs]
            response = {
                "object": "list",
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": _embedding_for_text(text),
                    }
                    for index, text in enumerate(inputs)
                ],
                "model": payload.get("model", "fake-embedding-model"),
            }
            self._write_json(200, response)
            return

        if self.path == "/v1/rerank":
            documents = payload.get("documents", [])
            if not isinstance(documents, list):
                documents = [str(documents)]
            query = payload.get("query", "")
            scored = [
                {
                    "index": index,
                    "relevance_score": _rerank_score(query, document),
                }
                for index, document in enumerate(documents)
            ]
            scored.sort(key=lambda item: item["relevance_score"], reverse=True)
            response = {
                "model": payload.get("model", "fake-reranker-model"),
                "results": scored[: int(payload.get("top_n") or len(scored))],
            }
            self._write_json(200, response)
            return

        self._write_json(404, {"error": f"Unknown path: {self.path}"})

    def log_message(self, format, *args):  # noqa: A003
        return

    def _write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(host: str = "127.0.0.1", port: int = 18080) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_server(server: ThreadingHTTPServer, thread: threading.Thread | None = None) -> None:
    server.shutdown()
    server.server_close()
    if thread is not None:
        thread.join(timeout=2)


if __name__ == "__main__":
    httpd, worker = start_server()
    print("fake_openai_server listening on http://127.0.0.1:18080/v1")
    try:
        worker.join()
    except KeyboardInterrupt:
        stop_server(httpd, worker)
