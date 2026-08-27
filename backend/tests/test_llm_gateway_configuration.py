from pathlib import Path


def _read_env_template():
    path = Path(__file__).resolve().parents[2] / ".env.production.example"
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_text_llm_uses_gateway_while_embedding_stays_local():
    values = _read_env_template()

    assert values["LLM_BASE_URL"] == "http://codex-gateway:8080/v1"
    assert values["LLM_MODEL_NAME"] == values["CODEX_MODEL"]
    assert values["GRAPHITI_LLM_MODEL"] == values["CODEX_MODEL"]
    assert values["GRAPHITI_EMBEDDING_BASE_URL"] == "http://embedding:80/v1"
    assert values["FALLBACK_LLM_BASE_URL"] == "https://api.deepseek.com"


def test_backend_depends_on_healthy_gateway():
    path = Path(__file__).resolve().parents[2] / "docker-compose.production.yml"
    compose = path.read_text()
    backend_section = compose.split("\n  backend:\n", 1)[1].split("\n  neo4j:", 1)[0]

    assert "codex-gateway:" in backend_section
    assert "condition: service_healthy" in backend_section
