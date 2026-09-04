from types import SimpleNamespace
import json

import httpx
import pytest
from zep_cloud import NotFoundError, Zep
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
                        "sosim_operation_id": GraphBuilderService.build_operation_id(
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


@pytest.mark.parametrize("status", ["failed", "invalid", "canceled"])
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


def _batch_item(sequence_index, status, episode_uuid=None, error=None):
    return SimpleNamespace(
        sequence_index=sequence_index,
        status=status,
        episode_uuid=episode_uuid,
        source_uuid=episode_uuid,
        graph_id="graph-1",
        error=error,
    )


def test_partial_batch_retries_only_the_failed_items():
    """One timed-out episode must not discard the ones that committed."""

    resubmitted = []

    class BatchApi:
        def get(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(status="partial", progress=None)
            return SimpleNamespace(status="succeeded", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-retry")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-3")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "succeeded", "episode-2"),
                        _batch_item(2, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-3")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 3),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two", "chunk three"],
        lost_items_callback=lost.extend,
    )

    assert episode_uuids == ["episode-1", "episode-2", "episode-3"]
    # Only the failed chunk is re-ingested; the other two already have episodes.
    assert resubmitted == [["chunk three"]]
    assert lost == []


def test_partial_batch_keeps_landed_episodes_when_retries_exhaust(monkeypatch):
    resubmitted = []

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id=f"batch-retry-{len(resubmitted)}")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-pending")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "failed", error={"message": "llm timeout"})],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    # Prove the bound is the bound: one retry means exactly one resubmission.
    monkeypatch.setattr(graph_builder_module, "GRAPH_BUILD_MAX_ITEM_RETRIES", 1)
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        lost_items_callback=lost.extend,
    )

    assert episode_uuids == ["episode-1"]
    assert resubmitted == [["chunk two"]]
    assert [item.sequence_index for item in lost] == [1]
    assert lost[0].error == {"message": "llm timeout"}


def test_partial_batch_resubmits_an_item_the_listing_never_reported():
    resubmitted = []

    class BatchApi:
        def get(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(status="partial", progress=None)
            return SimpleNamespace(status="succeeded", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-retry")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-2")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                # The second item is missing from the listing entirely.
                return SimpleNamespace(
                    items=[_batch_item(0, "succeeded", "episode-1")],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-2")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
    )

    assert episode_uuids == ["episode-1", "episode-2"]
    assert resubmitted == [["chunk two"]]


def test_retry_batch_short_listing_is_not_reported_as_recovered():
    """A resubmitted item the retry listing omits is still a lost chunk."""

    resubmitted = []

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id=f"batch-retry-{len(resubmitted)}")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-pending")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            # The retry batch reports nothing at all about the item it was
            # given, which used to read as "recovered every failed item".
            return SimpleNamespace(items=[], next_cursor=None)

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        lost_items_callback=lost.extend,
    )

    assert episode_uuids == ["episode-1"]
    assert [item.sequence_index for item in lost] == [1]
    assert resubmitted == [["chunk two"], ["chunk two"]]


def test_partial_batch_raises_unless_the_caller_opts_into_salvage():
    """A caller that only counts episodes must not silently get a short list."""

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def list_items(self, **_kwargs):
            return SimpleNamespace(
                items=[
                    _batch_item(0, "succeeded", "episode-1"),
                    _batch_item(1, "failed", error={"message": "llm timeout"}),
                ],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())

    with pytest.raises(RuntimeError, match="partial"):
        builder._wait_for_batch(
            BatchSubmission("batch-1", "operation", [], 2),
            timeout=1,
        )


def test_partial_batch_fails_when_no_episode_landed_at_all():
    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def list_items(self, **_kwargs):
            return SimpleNamespace(
                items=[_batch_item(0, "failed", error={"message": "bad"})],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())

    with pytest.raises(RuntimeError, match="partial"):
        builder._wait_for_batch(
            BatchSubmission("batch-1", "operation", [], 1),
            timeout=1,
            allow_partial=True,
        )


def test_retry_budget_comes_out_of_the_caller_timeout(monkeypatch):
    """Each retry must spend the caller's deadline, not restart it."""

    resubmitted = []
    clock = {"now": 0.0}

    class BatchApi:
        def get(self, **_kwargs):
            # Polling the main batch consumes the whole ingestion budget.
            clock["now"] += 20.0
            return SimpleNamespace(status="partial", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-retry")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-2")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **_kwargs):
            return SimpleNamespace(
                items=[
                    _batch_item(0, "succeeded", "episode-1"),
                    _batch_item(1, "failed", error={"message": "llm timeout"}),
                ],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    monkeypatch.setattr(graph_builder_module.time, "time", lambda: clock["now"])
    monkeypatch.setattr(graph_builder_module.time, "sleep", lambda _seconds: None)
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=10,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        lost_items_callback=lost.extend,
    )

    assert episode_uuids == ["episode-1"]
    assert resubmitted == []
    assert [item.sequence_index for item in lost] == [1]


def test_skipped_item_is_reported_lost_without_being_resubmitted():
    """Zep declined this item; replaying it would risk a duplicate episode."""

    resubmitted = []

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-retry")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-2")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "skipped"),
                        _batch_item(2, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-2")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 3),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two", "chunk three"],
        lost_items_callback=lost.extend,
    )

    assert episode_uuids == ["episode-1", "episode-2"]
    # Only the failed chunk goes back; the skipped one is reported, not replayed.
    assert resubmitted == [["chunk three"]]
    assert [(item.sequence_index, item.status) for item in lost] == [(1, "skipped")]


def test_a_truncated_item_is_reported_lost_without_being_resubmitted():
    """Truncation is deterministic, so a resubmission only truncates again."""

    resubmitted = []

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-retry")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-3")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(
                            1,
                            "failed",
                            error={
                                "type": "TruncatedResponseError",
                                "message": (
                                    "hit max_tokens=4096 before closing its JSON"
                                ),
                            },
                        ),
                        _batch_item(2, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-3")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 3),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two", "chunk three"],
        lost_items_callback=lost.extend,
    )

    assert episode_uuids == ["episode-1", "episode-3"]
    # The timeout is worth another attempt; the truncation never is, so the
    # retry budget goes to the item that can still land.
    assert resubmitted == [["chunk three"]]
    assert [item.sequence_index for item in lost] == [1]


def test_succeeded_batch_rejects_a_duplicate_sequence_index():
    """A listing of the right length can still be missing a chunk."""

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="succeeded", progress=None)

        def list_items(self, **_kwargs):
            return SimpleNamespace(
                items=[
                    _batch_item(0, "succeeded", "episode-1"),
                    _batch_item(0, "succeeded", "episode-1"),
                ],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())

    with pytest.raises(RuntimeError, match="expected 2"):
        builder._wait_for_batch(
            BatchSubmission("batch-1", "operation", [], 2),
            timeout=1,
        )


def test_resume_replays_a_recorded_retry_batch_instead_of_reingesting():
    """A crash after the retries succeeded must not duplicate their episodes."""

    resubmitted = []

    class BatchApi:
        def get(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(status="partial", progress=None)
            return SimpleNamespace(status="succeeded", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-retry-2")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-2")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-2")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    recorded = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        retry_batch_callback=lambda batch_id, operation_id: recorded.append(
            {"batch_id": batch_id, "operation_id": operation_id}
        ),
        known_retry_batches=[],
    )

    assert episode_uuids == ["episode-1", "episode-2"]
    assert resubmitted == [["chunk two"]]
    assert [entry["batch_id"] for entry in recorded] == [None, "batch-retry-2"]

    # Replaying the journalled batch recovers the same episode without a
    # second ingest of the same chunk.
    resubmitted.clear()
    replayed = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        known_retry_batches=[entry for entry in recorded if entry["batch_id"]],
    )

    assert replayed == ["episode-1", "episode-2"]
    assert resubmitted == []


def _aged_out_batch(batch_id):
    return NotFoundError(
        body={"message": f"batch {batch_id} not found"},
    )


def _retry_operation_id(chunks):
    """The identity a retry batch for these chunks is journalled under."""

    return GraphBuilderService.build_operation_id("graph-1", chunks)


def test_an_unreadable_journal_entry_still_lets_a_later_one_recover():
    """One aged-out retry batch must not abandon the retries that follow it."""

    resubmitted = []

    class BatchApi:
        def get(self, **kwargs):
            batch_id = kwargs["batch_id"]
            if batch_id == "batch-1":
                return SimpleNamespace(status="partial", progress=None)
            if batch_id == "batch-dead":
                raise _aged_out_batch(batch_id)
            return SimpleNamespace(status="succeeded", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-fresh")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-2")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-2")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        lost_items_callback=lost.extend,
        known_retry_batches=[
            # Both entries were journalled for this same chunk set, so either
            # one may be replayed against it; the operation ID is what says so.
            {"operation_id": _retry_operation_id(["chunk two"]), "batch_id": "batch-dead"},
            {"operation_id": _retry_operation_id(["chunk two"]), "batch_id": "batch-alive"},
        ],
    )

    assert episode_uuids == ["episode-1", "episode-2"]
    assert lost == []
    # The second journalled batch already held the episode, so nothing was
    # ingested a second time.
    assert resubmitted == []


def test_an_unreadable_journal_entry_is_not_replaced_by_a_fresh_ingest():
    """Nobody can say what the dead batch committed, so do not repeat it."""

    resubmitted = []

    class BatchApi:
        def get(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(status="partial", progress=None)
            raise _aged_out_batch(kwargs["batch_id"])

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-fresh")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-2")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **_kwargs):
            return SimpleNamespace(
                items=[
                    _batch_item(0, "succeeded", "episode-1"),
                    _batch_item(1, "failed", error={"message": "llm timeout"}),
                ],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 2),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two"],
        lost_items_callback=lost.extend,
        known_retry_batches=[
            {
                "operation_id": _retry_operation_id(["chunk two"]),
                "batch_id": "batch-dead",
            }
        ],
    )

    assert episode_uuids == ["episode-1"]
    assert resubmitted == []
    assert [item.sequence_index for item in lost] == [1]


def test_a_journal_entry_is_never_mapped_onto_a_different_pending_set():
    """Retry results are merged by position, so identity has to be checked.

    The journal was written by a run whose second attempt carried chunk three
    alone. This run cannot shrink `pending` the same way - its first entry is
    unreadable - so replaying the second entry positionally would credit chunk
    index 1 with chunk three's episode: the wrong source chunk, silently.
    """

    resubmitted = []

    class BatchApi:
        def get(self, **kwargs):
            batch_id = kwargs["batch_id"]
            if batch_id == "batch-1":
                return SimpleNamespace(status="partial", progress=None)
            if batch_id == "batch-dead":
                raise _aged_out_batch(batch_id)
            return SimpleNamespace(status="succeeded", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-fresh")

        def add(self, **kwargs):
            resubmitted.append([item.data for item in kwargs["items"]])
            return [SimpleNamespace(episode_uuid="episode-fresh")]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **kwargs):
            if kwargs["batch_id"] == "batch-1":
                return SimpleNamespace(
                    items=[
                        _batch_item(0, "succeeded", "episode-1"),
                        _batch_item(1, "failed", error={"message": "llm timeout"}),
                        _batch_item(2, "failed", error={"message": "llm timeout"}),
                    ],
                    next_cursor=None,
                )
            # The batch that carried chunk three alone; its only item sits at
            # sequence index 0.
            return SimpleNamespace(
                items=[_batch_item(0, "succeeded", "episode-3")],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    lost = []

    episode_uuids = builder._wait_for_batch(
        BatchSubmission("batch-1", "operation", [], 3),
        timeout=1,
        allow_partial=True,
        retry_chunks=["chunk one", "chunk two", "chunk three"],
        lost_items_callback=lost.extend,
        known_retry_batches=[
            {
                "operation_id": _retry_operation_id(["chunk two", "chunk three"]),
                "batch_id": "batch-dead",
            },
            {
                "operation_id": _retry_operation_id(["chunk three"]),
                "batch_id": "batch-alive",
            },
        ],
    )

    # chunk three's episode belongs to chunk three or to nobody.
    assert episode_uuids == ["episode-1"]
    assert [item.sequence_index for item in lost] == [1, 2]
    # And nothing is re-ingested either: batch-dead may already hold these.
    assert resubmitted == []


def test_service_worker_reports_the_chunks_its_retries_could_not_recover(monkeypatch):
    """The legacy build path opts into salvage, so it must report the losses."""

    updates = []

    class BatchApi:
        def get(self, **_kwargs):
            return SimpleNamespace(status="partial", progress=None)

        def create(self, **_kwargs):
            return SimpleNamespace(batch_id="batch-1")

        def add(self, **kwargs):
            return [
                SimpleNamespace(episode_uuid=f"episode-{index}")
                for index, _item in enumerate(kwargs["items"])
            ]

        def process(self, **_kwargs):
            return SimpleNamespace(status="queued")

        def list_items(self, **_kwargs):
            return SimpleNamespace(
                items=[
                    _batch_item(0, "succeeded", "episode-0"),
                    _batch_item(1, "failed", error={"message": "llm timeout"}),
                    _batch_item(2, "succeeded", "episode-2"),
                ],
                next_cursor=None,
            )

    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=BatchApi())
    builder.task_manager = SimpleNamespace(
        update_task=lambda task_id, **kwargs: updates.append((task_id, kwargs)),
        complete_task=lambda task_id, result: updates.append(
            (task_id, {"status": "complete_task", "result": result})
        ),
        fail_task=lambda task_id, error: updates.append(
            (task_id, {"status": "fail_task", "error": error})
        ),
    )
    builder.create_graph = lambda name, **_kwargs: "graph-1"
    builder.set_ontology = lambda _graph_id, _ontology: None
    builder._get_graph_info = lambda graph_id: graph_builder_module.GraphInfo(
        graph_id=graph_id, node_count=4, edge_count=3, entity_types=["Person"]
    )
    # One retry, and it recovers nothing, so the item stays lost.
    monkeypatch.setattr(graph_builder_module, "GRAPH_BUILD_MAX_ITEM_RETRIES", 1)

    builder._build_graph_worker(
        "task-1",
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
        {"entity_types": [], "edge_types": []},
        "Graph",
        30,
        0,
        350,
    )

    completions = [
        kwargs for _task_id, kwargs in updates
        if kwargs.get("status") == graph_builder_module.TaskStatus.COMPLETED
    ]
    assert len(completions) == 1
    result = completions[0]["result"]
    assert result["lost_chunk_count"] == 1
    assert result["lost_chunk_indexes"] == [1]
    assert result["chunk_count"] == 3
    # The chunks that landed, not the chunks that were submitted.
    assert result["chunks_processed"] == 2
    assert "fail_task" not in [
        kwargs.get("status") for _task_id, kwargs in updates
    ]


def test_batch_wait_times_out_while_status_remains_nonterminal(monkeypatch):
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(
        batch=SimpleNamespace(
            get=lambda **_kwargs: SimpleNamespace(status="processing", progress=None)
        )
    )
    # One reading for the ingestion deadline, then the poll's own start and
    # first elapsed check.
    timestamps = iter([0.0, 0.0, 2.0])
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
        "source_description": "SoSim source document chunk",
        "type": "graph_episode",
    }
