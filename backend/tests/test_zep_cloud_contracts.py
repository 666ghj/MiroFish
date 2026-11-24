from types import SimpleNamespace
import json

import httpx
import pytest
from zep_cloud import Zep
from zep_cloud.core.api_error import ApiError as ZepApiError

from app.services import graph_builder as graph_builder_module
from app.services.graph_builder import BatchSubmission, GraphBuilderService
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode, ZepEntityReader
from app.services.zep_tools import ZepToolsService


def test_report_search_caps_the_query_sent_to_zep():
    calls = []

    class GraphApi:
        def search(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(edges=[], nodes=[])

    service = object.__new__(ZepToolsService)
    service.client = SimpleNamespace(graph=GraphApi())

    original_query = "q" * 401
    result = service.search_graph("graph-id", original_query)

    assert calls[0]["query"] == original_query[:400]
    assert result.query == original_query


def test_profile_context_search_caps_both_queries_sent_to_zep():
    calls = []

    class GraphApi:
        def search(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(edges=[], nodes=[])

    generator = object.__new__(OasisProfileGenerator)
    generator.zep_client = SimpleNamespace(graph=GraphApi())
    generator.graph_id = "graph-id"

    entity = EntityNode(
        uuid="node-id",
        name="n" * 500,
        labels=["Entity", "Person"],
        summary="",
        attributes={},
    )
    generator._search_zep_for_entity(entity)

    assert len(calls) == 2
    assert all(0 < len(call["query"]) <= 400 for call in calls)


def test_entity_context_includes_incoming_edges_from_the_full_graph():
    incoming = {
        "uuid": "edge-in",
        "name": "WORKS_AT",
        "fact": "Alice works at Acme",
        "source_node_uuid": "alice",
        "target_node_uuid": "acme",
        "attributes": {},
    }
    outgoing = {
        "uuid": "edge-out",
        "name": "BUILDS",
        "fact": "Acme builds Product",
        "source_node_uuid": "acme",
        "target_node_uuid": "product",
        "attributes": {},
    }
    unrelated = {
        "uuid": "edge-unrelated",
        "name": "LOCATED_IN",
        "fact": "OtherCo is located in Paris",
        "source_node_uuid": "other-company",
        "target_node_uuid": "paris",
        "attributes": {},
    }

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(
        graph=SimpleNamespace(
            node=SimpleNamespace(
                get=lambda **_kwargs: SimpleNamespace(
                    uuid_="acme",
                    name="Acme",
                    labels=["Company"],
                    summary="",
                    attributes={},
                ),
                # Real Cloud 3.25 omits incoming edges here.
                get_edges=lambda **_kwargs: [SimpleNamespace(**outgoing)],
            )
        )
    )
    reader.get_all_edges = lambda _graph_id: [incoming, outgoing, unrelated]
    reader.get_all_nodes = lambda _graph_id: [
        {"uuid": "alice", "name": "Alice", "labels": ["Person"], "summary": ""},
        {"uuid": "acme", "name": "Acme", "labels": ["Company"], "summary": ""},
        {"uuid": "product", "name": "Product", "labels": ["Product"], "summary": ""},
    ]

    entity = reader.get_entity_with_context("graph-id", "acme")

    assert entity is not None
    assert len(entity.related_edges) == 2
    assert {edge["edge_name"] for edge in entity.related_edges} == {
        "WORKS_AT",
        "BUILDS",
    }
    assert {edge["direction"] for edge in entity.related_edges} == {
        "incoming",
        "outgoing",
    }
    assert {node["name"] for node in entity.related_nodes} == {"Alice", "Product"}


def test_entity_reader_does_not_turn_auth_failure_into_missing_entity():
    def unauthorized(**_kwargs):
        raise ZepApiError(status_code=401, body={"message": "unauthorized"})

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(
        graph=SimpleNamespace(node=SimpleNamespace(get=unauthorized))
    )

    with pytest.raises(ZepApiError) as error:
        reader.get_entity_with_context("graph-id", "node-id")

    assert error.value.status_code == 401


def test_entity_reader_does_not_turn_edge_failure_into_empty_data():
    def forbidden(**_kwargs):
        raise ZepApiError(status_code=403, body={"message": "forbidden"})

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(
        graph=SimpleNamespace(
            node=SimpleNamespace(get_edges=forbidden),
        )
    )

    with pytest.raises(ZepApiError) as error:
        reader.get_node_edges("node-id")

    assert error.value.status_code == 403


def test_report_tools_do_not_turn_zep_read_failures_into_empty_data():
    def unauthorized(**_kwargs):
        raise ZepApiError(status_code=401, body={"message": "unauthorized"})

    service = object.__new__(ZepToolsService)
    service.client = SimpleNamespace(
        graph=SimpleNamespace(node=SimpleNamespace(get=unauthorized))
    )

    with pytest.raises(ZepApiError):
        service.get_node_detail("node-id")

    service.get_all_edges = lambda _graph_id: (_ for _ in ()).throw(
        ZepApiError(status_code=503, body={"message": "unavailable"})
    )
    with pytest.raises(ZepApiError):
        service.get_node_edges("graph-id", "node-id")


def test_episode_processing_timeout_fails_instead_of_reporting_success(monkeypatch):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        graph=SimpleNamespace(
            episode=SimpleNamespace(
                get=lambda **_kwargs: SimpleNamespace(processed=False)
            )
        )
    )

    timestamps = iter([0.0, 2.0])
    monkeypatch.setattr(graph_builder_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="episode"):
        builder._wait_for_episodes(["episode-1"], timeout=1)


def test_document_ingestion_uses_current_batch_api_and_persists_identity():
    calls = []

    class BatchApi:
        def create(self, **kwargs):
            calls.append(("create", kwargs))
            return SimpleNamespace(batch_id="batch-1")

        def add(self, **kwargs):
            calls.append(("add", kwargs))
            return [
                SimpleNamespace(episode_uuid=f"episode-{index}")
                for index, _item in enumerate(kwargs["items"])
            ]

        def process(self, **kwargs):
            calls.append(("process", kwargs))
            return SimpleNamespace(status="queued")

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    persisted = []

    submission = builder.add_text_batches(
        "graph-id",
        ["chunk one", "chunk two"],
        batch_created_callback=lambda batch_id, operation_id: persisted.append(
            (batch_id, operation_id)
        ),
    )

    assert submission.batch_id == "batch-1"
    assert submission.item_count == 2
    assert len(submission.operation_id) == 64
    assert persisted == [
        (None, submission.operation_id),
        ("batch-1", submission.operation_id),
    ]
    assert [name for name, _kwargs in calls] == ["create", "add", "process"]
    items = calls[1][1]["items"]
    assert [item.type for item in items] == ["graph_episode", "graph_episode"]
    assert all(item.graph_id == "graph-id" for item in items)
    assert all(item.data_type == "text" for item in items)


def test_graph_create_persists_identity_before_post_and_reconciles_timeout():
    events = []

    class GraphApi:
        def create(self, **kwargs):
            events.append(("create", kwargs["graph_id"]))
            raise TimeoutError("response lost")

        def get(self, graph_id):
            events.append(("get", graph_id))
            return SimpleNamespace(graph_id=graph_id)

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=GraphApi())

    graph_id = builder.create_graph(
        "Graph",
        graph_id="known-id",
        graph_id_callback=lambda value: events.append(("persist", value)),
    )

    assert graph_id == "known-id"
    assert events == [
        ("persist", "known-id"),
        ("create", "known-id"),
        ("get", "known-id"),
    ]


def test_batch_create_timeout_is_reconciled_by_operation_metadata(monkeypatch):
    calls = []
    list_count = 0

    class BatchApi:
        def create(self, **_kwargs):
            calls.append("create")
            raise TimeoutError("response lost")

        def list(self, **_kwargs):
            nonlocal list_count
            calls.append("list")
            list_count += 1
            if list_count == 1:
                return SimpleNamespace(batches=[], next_cursor=None)
            return SimpleNamespace(
                batches=[SimpleNamespace(
                    batch_id="batch-recovered",
                    metadata={
                        "mirofish_operation_id": GraphBuilderService.build_operation_id(
                            "graph-id", ["chunk"]
                        ),
                        "graph_id": "graph-id",
                    },
                )],
                next_cursor=None,
            )

        def add(self, **kwargs):
            calls.append("add")
            return [SimpleNamespace(episode_uuid="episode-1")]

        def process(self, **_kwargs):
            calls.append("process")
            return SimpleNamespace(status="queued")

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    submission = builder.add_text_batches("graph-id", ["chunk"])

    assert submission.batch_id == "batch-recovered"
    assert calls == ["create", "list", "list", "add", "process"]


def test_batch_add_timeout_recovers_a_fully_accepted_group_without_replay(monkeypatch):
    add_calls = []
    list_calls = []

    class BatchApi:
        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-1")

        def add(self, **_kwargs):
            add_calls.append(True)
            raise TimeoutError("response lost")

        def list_items(self, **_kwargs):
            list_calls.append(True)
            if len(list_calls) == 1:
                return SimpleNamespace(items=[], next_cursor=None)
            return SimpleNamespace(
                items=[
                    SimpleNamespace(sequence_index=0, episode_uuid="episode-1"),
                    SimpleNamespace(sequence_index=1, episode_uuid="episode-2"),
                ],
                next_cursor=None,
            )

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    submission = builder.add_text_batches(
        "graph-id", ["chunk one", "chunk two"]
    )

    assert submission.item_count == 2
    assert add_calls == [True]
    assert len(list_calls) == 2


def test_batch_wait_validates_terminal_items_and_opaque_zero_cursor():
    list_calls = []

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(
                status="succeeded",
                progress=SimpleNamespace(
                    percent_complete=100,
                    succeeded_items=2,
                ),
            )

        def list_items(self, **kwargs):
            list_calls.append(kwargs)
            if kwargs["cursor"] is None:
                return SimpleNamespace(
                    items=[SimpleNamespace(
                        sequence_index=0,
                        status="succeeded",
                        episode_uuid="episode-1",
                        source_uuid="episode-1",
                    )],
                    next_cursor=0,
                )
            return SimpleNamespace(
                items=[SimpleNamespace(
                    sequence_index=1,
                    status="succeeded",
                    episode_uuid="episode-2",
                    source_uuid="episode-2",
                )],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    submission = BatchSubmission("batch-1", "operation", [], 2)

    assert builder._wait_for_batch(submission, timeout=1) == [
        "episode-1",
        "episode-2",
    ]
    assert [call["cursor"] for call in list_calls] == [None, 0]


@pytest.mark.parametrize("status", ["partial", "failed", "invalid", "canceled"])
def test_batch_non_success_terminal_states_fail(status):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        batch=SimpleNamespace(
            get=lambda **_kwargs: SimpleNamespace(status=status, progress=None),
            list_items=lambda **_kwargs: SimpleNamespace(
                items=[SimpleNamespace(status="failed", error={"message": "bad"})],
                next_cursor=None,
            ),
        )
    )

    with pytest.raises(RuntimeError, match=status):
        builder._wait_for_batch(
            BatchSubmission("batch-1", "operation", [], 1),
            timeout=1,
        )


def test_batch_wait_times_out_while_status_remains_nonterminal(monkeypatch):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        batch=SimpleNamespace(
            get=lambda **_kwargs: SimpleNamespace(status="processing", progress=None)
        )
    )
    timestamps = iter([0.0, 2.0])
    monkeypatch.setattr(graph_builder_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="batch-1"):
        builder._wait_for_batch(
            BatchSubmission("batch-1", "operation", [], 1),
            timeout=1,
        )


def test_installed_sdk_serializes_the_batch_325_contract():
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path, request.content))
        path = request.url.path
        if path.endswith("/batches") and request.method == "POST":
            return httpx.Response(
                200,
                json={"batch_id": "batch-1", "status": "draft", "item_count": 0},
            )
        if path.endswith("/batches/batch-1/items") and request.method == "POST":
            return httpx.Response(200, json=[{
                "item_id": "item-1",
                "sequence_index": 0,
                "status": "pending",
                "episode_uuid": "episode-1",
                "source_uuid": "episode-1",
            }])
        if path.endswith("/batches/batch-1/process"):
            return httpx.Response(
                200,
                json={"batch_id": "batch-1", "status": "queued", "item_count": 1},
            )
        if path.endswith("/batches/batch-1"):
            return httpx.Response(200, json={
                "batch_id": "batch-1",
                "status": "succeeded",
                "item_count": 1,
                "progress": {"percent_complete": 100, "succeeded_items": 1},
            })
        if path.endswith("/batches/batch-1/items") and request.method == "GET":
            return httpx.Response(200, json={
                "items": [{
                    "item_id": "item-1",
                    "sequence_index": 0,
                    "status": "succeeded",
                    "episode_uuid": "episode-1",
                    "source_uuid": "episode-1",
                }],
                "next_cursor": None,
            })
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport_client:
        builder = object.__new__(GraphBuilderService)
        builder.client = Zep(api_key="test-key", httpx_client=transport_client)
        submission = builder.add_text_batches("graph-id", ["source chunk"])
        assert builder._wait_for_batch(submission, timeout=1) == ["episode-1"]

    assert [(method, path) for method, path, _body in requests] == [
        ("POST", "/api/v2/batches"),
        ("POST", "/api/v2/batches/batch-1/items"),
        ("POST", "/api/v2/batches/batch-1/process"),
        ("GET", "/api/v2/batches/batch-1"),
        ("GET", "/api/v2/batches/batch-1/items"),
    ]
    add_payload = json.loads(requests[1][2])
    assert add_payload["items"][0] == {
        "data": "source chunk",
        "data_type": "text",
        "graph_id": "graph-id",
        "metadata": add_payload["items"][0]["metadata"],
        "source_description": "MiroFish source document chunk",
        "type": "graph_episode",
    }
