"""
Zero-dependency end-to-end test for the local graph replacement.

This test:
1. Starts a fake OpenAI-compatible server
2. Injects minimal runtime shims for missing third-party packages
3. Runs ontology generation -> graph build -> entity read -> graph search
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import types
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from fake_openai_server import start_server, stop_server


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
APP_ROOT = BACKEND_ROOT / "app"

SAMPLE_TEXT = (
    "Alice is a journalist at DailyNews. "
    "DailyNews reports on GreenFuture, an environmental organization. "
    "Alice supports GreenFuture. "
    "PolluteCorp opposes GreenFuture. "
    "Mayor Lee responds to Alice."
)


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _to_namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_to_namespace(item) for item in value]
    return value


def install_runtime_shims() -> None:
    flask_module = types.ModuleType("flask")
    flask_module.request = SimpleNamespace(headers={})
    flask_module.has_request_context = lambda: False
    flask_module.Flask = type("Flask", (), {})
    sys.modules["flask"] = flask_module

    flask_cors_module = types.ModuleType("flask_cors")
    flask_cors_module.CORS = lambda *args, **kwargs: None
    sys.modules["flask_cors"] = flask_cors_module

    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = dotenv_module

    pydantic_module = types.ModuleType("pydantic")

    class FieldInfo:
        def __init__(self, default=None, description=None):
            self.default = default
            self.description = description

    def Field(*, default=None, description=None):
        return FieldInfo(default=default, description=description)

    class ConfigDict(dict):
        pass

    class BaseModel:
        model_fields = {}

        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)
            annotations = getattr(cls, "__annotations__", {})
            model_fields = {}
            for name in annotations:
                value = getattr(cls, name, None)
                if isinstance(value, FieldInfo):
                    model_fields[name] = value
            cls.model_fields = model_fields

    pydantic_module.Field = Field
    pydantic_module.BaseModel = BaseModel
    pydantic_module.ConfigDict = ConfigDict
    sys.modules["pydantic"] = pydantic_module

    openai_module = types.ModuleType("openai")

    class _ChatCompletions:
        def __init__(self, client):
            self.client = client

        def create(self, **kwargs):
            return self.client._post("/chat/completions", kwargs)

    class _Embeddings:
        def __init__(self, client):
            self.client = client

        def create(self, **kwargs):
            return self.client._post("/embeddings", kwargs)

    class OpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.api_key = api_key or ""
            self.base_url = (base_url or "").rstrip("/")
            self.chat = SimpleNamespace(completions=_ChatCompletions(self))
            self.embeddings = _Embeddings(self)

        def _post(self, path: str, payload: dict):
            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self.base_url + path,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            return _to_namespace(data)

    openai_module.OpenAI = OpenAI
    sys.modules["openai"] = openai_module


def ensure_package(name: str, path: Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_backend_modules(temp_upload_root: Path):
    sys.path.insert(0, str(BACKEND_ROOT))

    ensure_package("app", APP_ROOT)
    ensure_package("app.utils", APP_ROOT / "utils")
    ensure_package("app.models", APP_ROOT / "models")
    ensure_package("app.services", APP_ROOT / "services")

    config_module = load_module("app.config", APP_ROOT / "config.py")
    config_module.Config.UPLOAD_FOLDER = str(temp_upload_root)
    config_module.Config.OASIS_SIMULATION_DATA_DIR = str(temp_upload_root / "simulations")

    load_module("app.utils.logger", APP_ROOT / "utils" / "logger.py")
    load_module("app.utils.locale", APP_ROOT / "utils" / "locale.py")
    load_module("app.utils.file_parser", APP_ROOT / "utils" / "file_parser.py")
    load_module("app.utils.llm_client", APP_ROOT / "utils" / "llm_client.py")
    load_module("app.utils.zep_paging", APP_ROOT / "utils" / "zep_paging.py")
    load_module("app.models.task", APP_ROOT / "models" / "task.py")
    load_module("app.models.project", APP_ROOT / "models" / "project.py")
    load_module("app.services.text_processor", APP_ROOT / "services" / "text_processor.py")
    load_module("app.services.ontology_generator", APP_ROOT / "services" / "ontology_generator.py")
    load_module("app.services.graph_builder", APP_ROOT / "services" / "graph_builder.py")
    load_module("app.services.zep_entity_reader", APP_ROOT / "services" / "zep_entity_reader.py")
    load_module("app.services.zep_tools", APP_ROOT / "services" / "zep_tools.py")

    return {
        "config": sys.modules["app.config"],
        "file_parser": sys.modules["app.utils.file_parser"],
        "project": sys.modules["app.models.project"],
        "task": sys.modules["app.models.task"],
        "text_processor": sys.modules["app.services.text_processor"],
        "ontology": sys.modules["app.services.ontology_generator"],
        "graph_builder": sys.modules["app.services.graph_builder"],
        "entity_reader": sys.modules["app.services.zep_entity_reader"],
        "zep_tools": sys.modules["app.services.zep_tools"],
    }


def wait_for_task(task_manager, task_id: str, timeout: int = 20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = task_manager.get_task(task_id)
        if task and task.status.value in {"completed", "failed"}:
            return task
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for task {task_id}")


class FakeFileStorage:
    def __init__(self, source_path: Path):
        self.source_path = source_path

    def save(self, destination: str) -> None:
        shutil.copyfile(self.source_path, destination)


def run_e2e() -> dict:
    with tempfile.TemporaryDirectory(prefix="mirofish-local-zep-") as temp_dir:
        temp_root = Path(temp_dir)
        upload_root = temp_root / "uploads"
        sample_path = temp_root / "seed.txt"
        db_path = temp_root / "local_zep.sqlite3"
        sample_path.write_text(SAMPLE_TEXT, encoding="utf-8")

        os.environ["LLM_API_KEY"] = "fake-key"
        os.environ["LLM_BASE_URL"] = "http://127.0.0.1:18080/v1"
        os.environ["LLM_MODEL_NAME"] = "fake-chat-model"
        os.environ["EMBEDDING_API_KEY"] = "fake-key"
        os.environ["EMBEDDING_BASE_URL"] = "http://127.0.0.1:18080/v1"
        os.environ["EMBEDDING_MODEL_NAME"] = "fake-embedding-model"
        os.environ["RERANKER_API_KEY"] = "fake-key"
        os.environ["RERANKER_BASE_URL"] = "http://127.0.0.1:18080/v1"
        os.environ["RERANKER_MODEL_NAME"] = "fake-reranker-model"
        os.environ["LOCAL_ZEP_DB_PATH"] = str(db_path)

        install_runtime_shims()
        modules = load_backend_modules(upload_root)

        ProjectManager = modules["project"].ProjectManager
        OntologyGenerator = modules["ontology"].OntologyGenerator
        GraphBuilderService = modules["graph_builder"].GraphBuilderService
        ZepEntityReader = modules["entity_reader"].ZepEntityReader
        ZepToolsService = modules["zep_tools"].ZepToolsService
        TaskManager = modules["task"].TaskManager
        FileParser = modules["file_parser"].FileParser
        TextProcessor = modules["text_processor"].TextProcessor

        project = ProjectManager.create_project(name="Local Zep E2E")
        project.simulation_requirement = "Simulate public sentiment around the GreenFuture environmental campaign."

        file_info = ProjectManager.save_file_to_project(
            project.project_id,
            FakeFileStorage(sample_path),
            "seed.txt",
        )
        project.files.append({"filename": file_info["original_filename"], "size": file_info["size"]})

        extracted_text = TextProcessor.preprocess_text(FileParser.extract_text(file_info["path"]))
        ProjectManager.save_extracted_text(project.project_id, extracted_text)
        project.total_text_length = len(extracted_text)
        ProjectManager.save_project(project)

        ontology_generator = OntologyGenerator()
        ontology = ontology_generator.generate(
            document_texts=[extracted_text],
            simulation_requirement=project.simulation_requirement,
            additional_context=None,
        )
        assert len(ontology["entity_types"]) == 10, ontology["entity_types"]
        assert any(item["name"] == "Person" for item in ontology["entity_types"])
        assert any(item["name"] == "Organization" for item in ontology["entity_types"])

        project.ontology = {
            "entity_types": ontology["entity_types"],
            "edge_types": ontology["edge_types"],
        }
        ProjectManager.save_project(project)

        builder = GraphBuilderService(api_key="ignored-for-local")
        task_id = builder.build_graph_async(
            text=extracted_text,
            ontology=project.ontology,
            graph_name="Local Zep E2E Graph",
            chunk_size=400,
            chunk_overlap=40,
            batch_size=2,
        )
        task = wait_for_task(TaskManager(), task_id)
        assert task.status.value == "completed", task.error

        graph_id = task.result["graph_id"]
        graph_data = builder.get_graph_data(graph_id)
        assert graph_data["node_count"] >= 5, graph_data
        assert graph_data["edge_count"] >= 5, graph_data

        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(graph_id=graph_id, enrich_with_edges=True)
        assert filtered.filtered_count >= 5, filtered.to_dict()

        tools = ZepToolsService(api_key="ignored-for-local")
        search = tools.search_graph(graph_id=graph_id, query="Alice supports GreenFuture", limit=5, scope="edges")
        assert any("Alice supports GreenFuture" in fact for fact in search.facts), search.to_dict()
        cross_encoder_results = tools.client.graph.search(
            graph_id=graph_id,
            query="Alice supports GreenFuture",
            limit=3,
            scope="edges",
            reranker="cross_encoder",
        )
        assert cross_encoder_results.edges, cross_encoder_results
        assert cross_encoder_results.edges[0].score is not None
        assert cross_encoder_results.edges[0].relevance is not None

        rrf_results = tools.client.graph.search(
            graph_id=graph_id,
            query="GreenFuture",
            limit=3,
            scope="both",
            reranker="rrf",
        )
        assert rrf_results.edges or rrf_results.nodes, rrf_results

        mmr_results = tools.client.graph.search(
            graph_id=graph_id,
            query="GreenFuture",
            limit=3,
            scope="edges",
            reranker="mmr",
            mmr_lambda=0.5,
        )
        assert mmr_results.edges, mmr_results

        episode_results = tools.client.graph.search(
            graph_id=graph_id,
            query="Mayor Lee",
            limit=2,
            scope="episodes",
            reranker="rrf",
        )
        assert episode_results.episodes, episode_results

        temporal_episode = tools.client.graph.add(
            graph_id=graph_id,
            data="Alice opposes GreenFuture.",
            type="text",
            created_at="2025-01-01T00:00:00Z",
            metadata={"source": "temporal_test"},
            source_description="Temporal update test",
        )
        assert temporal_episode.metadata["source"] == "temporal_test"

        temporal_edges = tools.client.graph.edge.get_by_graph_id(graph_id=graph_id, limit=20)
        old_supports = [
            edge
            for edge in temporal_edges
            if edge.name == "SUPPORTS" and edge.source_node_uuid and "Alice supports GreenFuture" in edge.fact
        ]
        new_opposes = [
            edge
            for edge in temporal_edges
            if edge.name == "OPPOSES" and "Alice opposes GreenFuture" in edge.fact
        ]
        assert old_supports and old_supports[0].invalid_at is not None, [edge.fact for edge in temporal_edges]
        assert new_opposes and new_opposes[0].valid_at == "2025-01-01T00:00:00Z", new_opposes

        active_results = tools.client.graph.search(
            graph_id=graph_id,
            query="Alice GreenFuture",
            limit=10,
            scope="edges",
            reranker="rrf",
            search_filters={"invalid_at": [[{"comparison_operator": "IS NULL"}]]},
        )
        assert any("Alice opposes GreenFuture" in edge.fact for edge in active_results.edges)
        assert not any("Alice supports GreenFuture" in edge.fact for edge in active_results.edges)

        metadata_results = tools.client.graph.search(
            graph_id=graph_id,
            query="Alice opposes GreenFuture",
            limit=5,
            scope="episodes",
            search_filters={
                "episode_metadata_filters": {
                    "type": "and",
                    "filters": [
                        {
                            "property_name": "source",
                            "comparison_operator": "=",
                            "property_value": "temporal_test",
                        }
                    ],
                }
            },
        )
        assert metadata_results.episodes and metadata_results.episodes[0].uuid_ == temporal_episode.uuid_

        stats = tools.get_graph_statistics(graph_id)
        assert stats["total_nodes"] >= 5
        assert stats["total_edges"] >= 5

        summary = tools.get_entity_summary(graph_id=graph_id, entity_name="Alice")
        assert summary["entity_info"] is not None, summary
        assert summary["total_relations"] >= 2, summary

        return {
            "project_id": project.project_id,
            "graph_id": graph_id,
            "node_count": graph_data["node_count"],
            "edge_count": graph_data["edge_count"],
            "entity_count": filtered.filtered_count,
            "search_facts": search.facts[:3],
            "cross_encoder_relevance": cross_encoder_results.edges[0].relevance,
            "episode_hits": len(episode_results.episodes),
            "alice_relations": summary["total_relations"],
        }


def main() -> int:
    server, thread = start_server()
    try:
        result = run_e2e()
        print(json.dumps({"status": "ok", "result": result}, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_server(server, thread)


if __name__ == "__main__":
    raise SystemExit(main())
