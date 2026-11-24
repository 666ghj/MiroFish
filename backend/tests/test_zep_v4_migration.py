import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services import graph_builder as graph_builder_module
from app.services.graph_builder import GraphBuilderService
from app.services.zep_tools import ZepToolsService
from app.utils.zep import (
    deterministic_idempotency_key,
    ensure_zep_graph_uuid,
)
from app.utils import zep_paging
from scripts import backfill_zep_graph_uuids as backfill


GRAPH_UUID = "00000000-0000-4000-8000-000000000001"
NODE_UUID = "00000000-0000-4000-8000-000000000002"
EPISODE_UUID = "00000000-0000-4000-8000-000000000003"


@pytest.mark.parametrize(
    "graph_id",
    [
        "00000000-0000-4000-8000-000000000001",
        "a5c11f86-ff96-58ab-958f-94d6c0bb25a8",
    ],
)
def test_graph_uuid_validation_accepts_v4_and_v5_ids(graph_id):
    assert ensure_zep_graph_uuid(graph_id) == graph_id


def test_deterministic_idempotency_keys_are_canonical_and_distinct_by_parts():
    operation_id = "operation-1"
    create_key = deterministic_idempotency_key(operation_id, "create")
    items_key = deterministic_idempotency_key(operation_id, "items", "0")
    process_key = deterministic_idempotency_key(operation_id, "process")

    for key in (create_key, items_key, process_key):
        parsed = uuid.UUID(key)
        assert parsed.version == 4
        assert str(parsed) == key

    assert create_key == deterministic_idempotency_key(operation_id, "create")
    assert len({create_key, items_key, process_key}) == 3


@pytest.mark.parametrize(
    "graph_id",
    [
        "mirofish_legacy",
        "not-a-uuid",
        "",
        "{00000000-0000-4000-8000-000000000001}",
    ],
)
def test_graph_uuid_validation_rejects_legacy_ids_with_backfill_hint(graph_id):
    with pytest.raises(ValueError, match="legacy Zep v3 ID") as error:
        ensure_zep_graph_uuid(graph_id)
    assert "python backend/scripts/backfill_zep_graph_uuids.py --apply" in str(
        error.value
    )


def test_graph_create_retries_with_the_same_idempotency_key(monkeypatch):
    create_keys = []
    callback_values = []

    class GraphApi:
        def create(self, **kwargs):
            create_keys.append(kwargs["idempotency_key"])
            if len(create_keys) == 1:
                raise httpx.ReadTimeout("response timed out")
            return SimpleNamespace(uuid_=GRAPH_UUID)

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=GraphApi())
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    graph_id = builder.create_graph(
        "MiroFish",
        graph_id_callback=callback_values.append,
    )

    assert graph_id == GRAPH_UUID
    assert len(create_keys) == 2
    assert create_keys[0] == create_keys[1]
    assert uuid.UUID(create_keys[0]).version == 4
    assert str(uuid.UUID(create_keys[0])) == create_keys[0]
    assert callback_values == [GRAPH_UUID]


@pytest.mark.parametrize("status", ["succeeded", "partial"])
def test_graph_delete_waits_for_a_successful_terminal_task(monkeypatch, status):
    calls = []

    class GraphApi:
        def delete(self, graph_uuid):
            calls.append(("delete", graph_uuid))
            return SimpleNamespace(task=SimpleNamespace(uuid_="task-1"))

    class TaskApi:
        def get(self, task_uuid):
            calls.append(("get", task_uuid))
            return SimpleNamespace(status=status)

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=GraphApi(), task=TaskApi())

    assert builder.delete_graph(GRAPH_UUID) is None
    assert calls == [("delete", GRAPH_UUID), ("get", "task-1")]


def test_graph_delete_raises_when_the_task_fails():
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        graph=SimpleNamespace(
            delete=lambda _graph_uuid: SimpleNamespace(
                task=SimpleNamespace(uuid_="task-failed")
            )
        ),
        task=SimpleNamespace(
            get=lambda _task_uuid: SimpleNamespace(status="failed")
        ),
    )

    with pytest.raises(RuntimeError, match="delete task task-failed failed"):
        builder.delete_graph(GRAPH_UUID)


def test_graph_delete_times_out_when_task_status_is_missing(monkeypatch):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        graph=SimpleNamespace(
            delete=lambda _graph_uuid: SimpleNamespace(
                task=SimpleNamespace(uuid_="task-pending")
            )
        ),
        task=SimpleNamespace(get=lambda _task_uuid: SimpleNamespace()),
    )
    monkeypatch.setattr(
        graph_builder_module,
        "ZEP_INGESTION_WAIT_TIMEOUT_SECONDS",
        1,
    )
    timestamps = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(graph_builder_module.time, "monotonic", lambda: next(timestamps))
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="task-pending"):
        builder.delete_graph(GRAPH_UUID)


def test_search_reads_only_the_first_page():
    node = SimpleNamespace(
        uuid_="edge-1",
        name="WORKS_AT",
        fact="Alice works at Acme",
        source_node_uuid=NODE_UUID,
        target_node_uuid=EPISODE_UUID,
    )

    class Pager:
        items = [node]

        def __iter__(self):
            raise AssertionError("search must not fetch later pages")

    calls = []

    class GraphApi:
        def search_edges(self, graph_uuid, **kwargs):
            calls.append((graph_uuid, kwargs))
            return Pager()

    service = object.__new__(ZepToolsService)
    service.client = SimpleNamespace(graph=GraphApi())

    result = service.search_graph(GRAPH_UUID, "Alice works at Acme", scope="edges")

    assert calls == [
        (
            GRAPH_UUID,
            {
                "query": "Alice works at Acme",
                "page_size": 10,
                "reranker": "cross_encoder",
            },
        )
    ]
    assert len(result.edges) == 1


def test_edge_paging_uses_opaque_cursors_and_honors_max_items(monkeypatch):
    calls = []
    pages = [
        SimpleNamespace(
            items=[SimpleNamespace(uuid_="edge-1"), SimpleNamespace(uuid_="edge-2")],
            response=SimpleNamespace(next_cursor="cursor-two"),
        ),
        SimpleNamespace(
            items=[SimpleNamespace(uuid_="edge-3"), SimpleNamespace(uuid_="edge-4")],
            response=SimpleNamespace(next_cursor="cursor-three"),
        ),
    ]

    def fake_fetch(api_call, graph_uuid, **kwargs):
        calls.append((graph_uuid, kwargs))
        return pages[len(calls) - 1]

    monkeypatch.setattr(zep_paging, "_fetch_page_with_retry", fake_fetch)
    client = SimpleNamespace(
        graph=SimpleNamespace(edge=SimpleNamespace(list=lambda *_args, **_kwargs: None))
    )

    edges = zep_paging.fetch_all_edges(
        client,
        GRAPH_UUID,
        page_size=2,
        max_items=3,
    )

    assert [edge.uuid_ for edge in edges] == ["edge-1", "edge-2", "edge-3"]
    assert calls[0][1]["cursor"] is None
    assert calls[1][1]["cursor"] == "cursor-two"


def test_edge_paging_rejects_a_repeated_cursor(monkeypatch):
    response = SimpleNamespace(
        items=[SimpleNamespace(uuid_="edge-1")],
        response=SimpleNamespace(next_cursor="same-cursor"),
    )
    monkeypatch.setattr(
        zep_paging,
        "_fetch_page_with_retry",
        lambda *_args, **_kwargs: response,
    )
    client = SimpleNamespace(
        graph=SimpleNamespace(edge=SimpleNamespace(list=lambda *_args, **_kwargs: None))
    )

    with pytest.raises(RuntimeError, match="cursor did not advance"):
        zep_paging.fetch_all_edges(client, GRAPH_UUID, page_size=1)


def test_backfill_dry_run_does_not_write_and_caches_lookup(tmp_path):
    path = tmp_path / "project.json"
    original = {
        "graph_id": "mirofish_legacy",
        "name": "Project",
        "details": [{"graph_id": "mirofish_legacy"}],
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    calls = []

    class GraphApi:
        def lookup(self, *, graph_id):
            calls.append(graph_id)
            return SimpleNamespace(uuid_=GRAPH_UUID)

    result = backfill.backfill_graph_ids(
        tmp_path,
        SimpleNamespace(graph=GraphApi()),
    )

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert len(calls) == 1
    assert result["apply"] is False
    assert len(result["planned_changes"]) == 2


def test_backfill_apply_rewrites_atomically_and_is_idempotent(tmp_path):
    path = tmp_path / "reports" / "report.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"graph_id": "mirofish_legacy", "report_id": "report-1"}),
        encoding="utf-8",
    )
    calls = []

    class GraphApi:
        def lookup(self, *, graph_id):
            calls.append(graph_id)
            return SimpleNamespace(uuid_=GRAPH_UUID)

    client = SimpleNamespace(graph=GraphApi())
    first = backfill.backfill_graph_ids(tmp_path, client, apply=True)
    saved = json.loads(path.read_text(encoding="utf-8"))
    second = backfill.backfill_graph_ids(tmp_path, client, apply=True)

    assert saved == {
        "graph_id": GRAPH_UUID,
        "legacy_zep_graph_id": "mirofish_legacy",
        "report_id": "report-1",
    }
    assert len(calls) == 1
    assert len(first["updated_files"]) == 1
    assert second["planned_changes"] == []


def test_backfill_reports_not_found_ids_and_continues(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "graph_id": "mirofish_missing",
                "related": [{"graph_id": "mirofish_found"}],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    class LookupNotFound(Exception):
        pass

    monkeypatch.setattr(backfill, "NotFoundError", LookupNotFound)

    class GraphApi:
        def lookup(self, *, graph_id):
            calls.append(graph_id)
            if graph_id == "mirofish_missing":
                raise LookupNotFound()
            return SimpleNamespace(uuid_=GRAPH_UUID)

    result = backfill.backfill_graph_ids(
        tmp_path,
        SimpleNamespace(graph=GraphApi()),
        apply=True,
    )

    assert result["not_found"] == ["mirofish_missing"]
    assert len(result["planned_changes"]) == 1
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "graph_id": "mirofish_missing",
        "related": [
            {
                "graph_id": GRAPH_UUID,
                "legacy_zep_graph_id": "mirofish_found",
            }
        ],
    }
    assert set(calls) == {"mirofish_missing", "mirofish_found"}


def test_backfill_skips_malformed_and_unreadable_files(tmp_path, monkeypatch):
    malformed_path = tmp_path / "a_malformed.json"
    malformed_path.write_text("{", encoding="utf-8")
    invalid_utf8_path = tmp_path / "b_invalid_utf8.jsonl"
    invalid_utf8_path.write_bytes(b"\xff")
    unreadable_path = tmp_path / "c_unreadable.json"
    unreadable_path.write_text("{}", encoding="utf-8")
    valid_path = tmp_path / "d_valid.json"
    valid_path.write_text(
        json.dumps({"graph_id": "mirofish_legacy"}),
        encoding="utf-8",
    )

    read_json_file = backfill._read_json_file

    def read_file(path):
        if path == unreadable_path:
            raise PermissionError("file is not readable")
        return read_json_file(path)

    monkeypatch.setattr(backfill, "_read_json_file", read_file)

    class GraphApi:
        def lookup(self, *, graph_id):
            assert graph_id == "mirofish_legacy"
            return SimpleNamespace(uuid_=GRAPH_UUID)

    result = backfill.backfill_graph_ids(
        tmp_path,
        SimpleNamespace(graph=GraphApi()),
    )

    assert result["skipped_files"] == [
        {
            "path": str(malformed_path),
            "error_type": "JSONDecodeError",
        },
        {
            "path": str(invalid_utf8_path),
            "error_type": "UnicodeDecodeError",
        },
        {
            "path": str(unreadable_path),
            "error_type": "PermissionError",
        },
    ]
    assert result["planned_changes"][0]["file"] == str(valid_path)
