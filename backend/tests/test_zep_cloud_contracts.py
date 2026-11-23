import uuid
from types import SimpleNamespace

import pytest
from zep_cloud.core.api_error import ApiError as ZepApiError

from app.services import graph_builder as graph_builder_module
from app.services.graph_builder import BatchSubmission, GraphBuilderService
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode, ZepEntityReader
from app.services.zep_tools import ZepToolsService
from app.utils.zep import deterministic_idempotency_key

GRAPH_UUID = "00000000-0000-4000-8000-000000000001"


def test_get_graph_data_includes_fact_type(monkeypatch):
    node = SimpleNamespace(
        uuid_="node-1",
        name="Acme",
        labels=["Company"],
        summary="",
        attributes={},
    )
    edge = SimpleNamespace(
        uuid_="edge-1",
        name="WORKS_AT",
        fact="Alice works at Acme",
        source_node_uuid="person-1",
        target_node_uuid="node-1",
        attributes={},
        episode_uuids=[],
    )
    monkeypatch.setattr(
        graph_builder_module,
        "fetch_all_nodes",
        lambda *_args: [node],
    )
    monkeypatch.setattr(
        graph_builder_module,
        "fetch_all_edges",
        lambda *_args: [edge],
    )
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace()

    graph_data = builder.get_graph_data(GRAPH_UUID)

    assert graph_data["edges"][0]["fact_type"] == "WORKS_AT"


def test_report_search_caps_the_query_sent_to_zep():
    calls = []

    class GraphApi:
        def search_edges(self, graph_uuid, **kwargs):
            calls.append((graph_uuid, kwargs))
            return SimpleNamespace(items=[])

    service = object.__new__(ZepToolsService)
    service.client = SimpleNamespace(graph=GraphApi())

    original_query = "q" * 401
    result = service.search_graph(GRAPH_UUID, original_query)

    assert calls[0][0] == GRAPH_UUID
    assert calls[0][1]["query"] == original_query[:400]
    assert result.query == original_query


def test_profile_context_search_caps_both_queries_sent_to_zep():
    calls = []

    class GraphApi:
        def search_edges(self, graph_uuid, **kwargs):
            calls.append((graph_uuid, kwargs))
            return SimpleNamespace(items=[])

        def search_nodes(self, graph_uuid, **kwargs):
            calls.append((graph_uuid, kwargs))
            return SimpleNamespace(items=[])

    generator = object.__new__(OasisProfileGenerator)
    generator.zep_client = SimpleNamespace(graph=GraphApi())
    generator.graph_id = GRAPH_UUID

    entity = EntityNode(
        uuid="node-id",
        name="n" * 500,
        labels=["Entity", "Person"],
        summary="",
        attributes={},
    )
    generator._search_zep_for_entity(entity)

    assert len(calls) == 2
    assert all(0 < len(call[1]["query"]) <= 400 for call in calls)


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
                get=lambda *_args: SimpleNamespace(
                    uuid_="acme",
                    name="Acme",
                    labels=["Company"],
                    summary="",
                    attributes={},
                )
            ),
            edge=SimpleNamespace(
                list=lambda *_args, **_kwargs: SimpleNamespace(
                    items=[
                        SimpleNamespace(**incoming),
                        SimpleNamespace(**outgoing),
                    ],
                    response=SimpleNamespace(next_cursor=None),
                )
            ),
        )
    )
    reader.get_all_nodes = lambda _graph_id: [
        {"uuid": "alice", "name": "Alice", "labels": ["Person"], "summary": ""},
        {"uuid": "acme", "name": "Acme", "labels": ["Company"], "summary": ""},
        {"uuid": "product", "name": "Product", "labels": ["Product"], "summary": ""},
    ]

    entity = reader.get_entity_with_context(GRAPH_UUID, "acme")

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
    def unauthorized(*_args, **_kwargs):
        raise ZepApiError(status_code=401, body={"message": "unauthorized"})

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(
        graph=SimpleNamespace(node=SimpleNamespace(get=unauthorized))
    )

    with pytest.raises(ZepApiError) as error:
        reader.get_entity_with_context(GRAPH_UUID, "node-id")

    assert error.value.status_code == 401


def test_entity_reader_does_not_turn_edge_failure_into_empty_data():
    def forbidden(*_args, **_kwargs):
        raise ZepApiError(status_code=403, body={"message": "forbidden"})

    reader = object.__new__(ZepEntityReader)
    reader.client = SimpleNamespace(
        graph=SimpleNamespace(
            edge=SimpleNamespace(list=forbidden),
        )
    )

    with pytest.raises(ZepApiError) as error:
        reader.get_node_edges("node-id", GRAPH_UUID)

    assert error.value.status_code == 403


def test_report_tools_do_not_turn_zep_read_failures_into_empty_data():
    def unauthorized(*_args, **_kwargs):
        raise ZepApiError(status_code=401, body={"message": "unauthorized"})

    service = object.__new__(ZepToolsService)
    service.client = SimpleNamespace(
        graph=SimpleNamespace(node=SimpleNamespace(get=unauthorized))
    )

    with pytest.raises(ZepApiError):
        service.get_node_detail(GRAPH_UUID, "node-id")

    service.get_all_edges = lambda _graph_id: (_ for _ in ()).throw(
        ZepApiError(status_code=503, body={"message": "unavailable"})
    )
    with pytest.raises(ZepApiError):
        service.get_node_edges(GRAPH_UUID, "node-id")


def test_episode_processing_timeout_fails_instead_of_reporting_success(monkeypatch):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        graph=SimpleNamespace(
            episode=SimpleNamespace(
                get=lambda *_args: SimpleNamespace(processed=False)
            )
        )
    )

    timestamps = iter([0.0, 2.0])
    monkeypatch.setattr(graph_builder_module.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="episode"):
        builder._wait_for_episodes(
            GRAPH_UUID,
            ["episode-1"],
            timeout=1,
        )


def test_document_ingestion_uses_current_batch_api_and_persists_identity():
    calls = []

    class BatchApi:
        def create(self, **kwargs):
            calls.append(("create", kwargs))
            return SimpleNamespace(uuid_="batch-1")

        def add_items(self, batch_uuid, **kwargs):
            calls.append(("add", {"batch_uuid": batch_uuid, **kwargs}))
            return SimpleNamespace(
                items=[
                    SimpleNamespace(episode_uuid=f"episode-{index}")
                    for index, _item in enumerate(kwargs["items"])
                ],
                rejected_items=[],
            )

        def process(self, batch_uuid, **kwargs):
            calls.append(("process", {"batch_uuid": batch_uuid, **kwargs}))
            return SimpleNamespace(status="queued")

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    persisted = []

    submission = builder.add_text_batches(
        GRAPH_UUID,
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
    assert calls[0][1]["idempotency_key"] == deterministic_idempotency_key(
        submission.operation_id,
        "create",
    )
    assert calls[1][1]["idempotency_key"] == deterministic_idempotency_key(
        submission.operation_id,
        "items",
        "0",
    )
    assert calls[2][1]["idempotency_key"] == deterministic_idempotency_key(
        submission.operation_id,
        "process",
    )
    items = calls[1][1]["items"]
    assert [item.type for item in items] == ["graph_episode", "graph_episode"]
    assert all(item.graph_uuid == GRAPH_UUID for item in items)
    assert all(item.data_type == "text" for item in items)


def test_graph_create_returns_server_uuid_and_calls_callback_after_success():
    events = []

    class GraphApi:
        def create(self, **kwargs):
            events.append(("create", kwargs))
            return SimpleNamespace(uuid_=GRAPH_UUID)

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=GraphApi())

    graph_id = builder.create_graph(
        "Graph",
        graph_id_callback=lambda value: events.append(("persist", value)),
    )

    assert graph_id == GRAPH_UUID
    assert events[0][0] == "create"
    assert events[0][1]["name"] == "Graph"
    assert events[0][1]["description"] == "MiroFish Social Simulation Graph"
    create_key = events[0][1]["idempotency_key"]
    assert uuid.UUID(create_key).version == 4
    assert str(uuid.UUID(create_key)) == create_key
    assert events[1] == ("persist", GRAPH_UUID)


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
                return SimpleNamespace(
                    items=[],
                    response=SimpleNamespace(next_cursor=None),
                )
            return SimpleNamespace(
                items=[SimpleNamespace(
                    uuid_="batch-recovered",
                    metadata={
                        "mirofish_operation_id": GraphBuilderService.build_operation_id(
                            GRAPH_UUID, ["chunk"]
                        ),
                        "graph_id": GRAPH_UUID,
                    },
                )],
                response=SimpleNamespace(next_cursor=None),
            )

        def add_items(self, batch_uuid, **kwargs):
            calls.append("add")
            return SimpleNamespace(
                items=[SimpleNamespace(episode_uuid="episode-1")],
                rejected_items=[],
            )

        def process(self, _batch_uuid, **_kwargs):
            calls.append("process")
            return SimpleNamespace(status="queued")

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    submission = builder.add_text_batches(GRAPH_UUID, ["chunk"])

    assert submission.batch_id == "batch-recovered"
    assert calls == ["create", "list", "list", "add", "process"]


def test_batch_add_timeout_recovers_a_fully_accepted_group_without_replay(monkeypatch):
    add_calls = []
    list_calls = []

    class BatchApi:
        def create(self, **_kwargs):
            return SimpleNamespace(uuid_="batch-1")

        def add_items(self, _batch_uuid, **_kwargs):
            add_calls.append(True)
            raise TimeoutError("response lost")

        def list_items(self, _batch_uuid, **kwargs):
            list_calls.append(True)
            if len(list_calls) == 1:
                return SimpleNamespace(
                    items=[],
                    response=SimpleNamespace(next_cursor=None),
                )
            return SimpleNamespace(
                items=[
                    SimpleNamespace(sequence_index=0, episode_uuid="episode-1"),
                    SimpleNamespace(sequence_index=1, episode_uuid="episode-2"),
                ],
                response=SimpleNamespace(next_cursor=None),
            )

        def process(self, _batch_uuid, **_kwargs):
            return SimpleNamespace(status="queued")

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)

    submission = builder.add_text_batches(
        GRAPH_UUID, ["chunk one", "chunk two"]
    )

    assert submission.item_count == 2
    assert add_calls == [True]
    assert len(list_calls) == 2


def test_batch_wait_validates_terminal_items_and_opaque_cursor():
    list_calls = []

    class BatchApi:
        def get(self, _batch_id):
            return SimpleNamespace(
                status="succeeded",
                progress=SimpleNamespace(
                    succeeded_items=2,
                    failed_items=0,
                    total_items=2,
                ),
            )

        def list_items(self, _batch_id, **kwargs):
            list_calls.append(kwargs)
            if kwargs["cursor"] is None:
                return SimpleNamespace(
                    items=[SimpleNamespace(
                        sequence_index=0,
                        status="succeeded",
                        episode_uuid="episode-1",
                        source_uuid="episode-1",
                    )],
                    response=SimpleNamespace(next_cursor="opaque-cursor-2"),
                )
            return SimpleNamespace(
                items=[SimpleNamespace(
                    sequence_index=1,
                    status="succeeded",
                        episode_uuid="episode-2",
                        source_uuid="episode-2",
                    )],
                response=SimpleNamespace(next_cursor=None),
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    submission = BatchSubmission("batch-1", "operation", [], 2)

    assert builder._wait_for_batch(submission, timeout=1) == [
        "episode-1",
        "episode-2",
    ]
    assert [call["cursor"] for call in list_calls] == [
        None,
        "opaque-cursor-2",
    ]


@pytest.mark.parametrize("status", ["partial", "failed", "invalid", "canceled"])
def test_batch_non_success_terminal_states_fail(status):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        batch=SimpleNamespace(
            get=lambda _batch_id: SimpleNamespace(status=status, progress=None),
            list_items=lambda _batch_id, **_kwargs: SimpleNamespace(
                items=[SimpleNamespace(status="failed", error={"message": "bad"})],
                response=SimpleNamespace(next_cursor=None),
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
            get=lambda _batch_id: SimpleNamespace(status="processing", progress=None)
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
