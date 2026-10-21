from datetime import datetime, timezone

import pytest
from zep_cloud.types.entity_edge import EntityEdge

from app.services import zep_tools
from app.services.zep_tools import EdgeInfo, ZepToolsService


@pytest.fixture
def fixed_time(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
            return reference.astimezone(tz) if tz else reference.replace(tzinfo=None)

    monkeypatch.setattr(zep_tools, "datetime", FixedDateTime, raising=False)


@pytest.mark.parametrize("invalid_at,expected", [
    ("2026-01-01T01:00:00Z", False),
    ("2026-01-01T01:00:00", False),
    ("2026-01-01T01:00:00+02:00", True),
    ("2025-12-31T20:00:00-05:00", False),
    ("2026-01-01T00:00:00Z", True),
    (None, False),
    ("invalid-date", True),
])
def test_fact_invalidation_respects_the_instant_and_timezone(fixed_time, invalid_at, expected):
    edge = EdgeInfo("edge-1", "WORKS_FOR", "A fact", "alice", "acme", invalid_at=invalid_at)

    assert edge.is_invalid is expected


def test_panorama_keeps_a_current_fact_until_its_future_end_date(fixed_time, monkeypatch):
    # Pinned SDK defines invalid_at as when the fact stopped being true,
    # whereas expired_at represents the graph record's invalidation.
    edge = EntityEdge(
        uuid_="edge-1", name="WORKS_FOR", fact="Alice works for Acme",
        source_node_uuid="alice", target_node_uuid="acme",
        created_at="2020-01-01T00:00:00Z", valid_at="2020-01-01T00:00:00Z",
        invalid_at="2027-01-01T00:00:00Z",
    )
    service = object.__new__(ZepToolsService)
    service.client = object()
    monkeypatch.setattr(service, "get_all_nodes", lambda graph_id: [])
    monkeypatch.setattr(zep_tools, "fetch_all_edges", lambda client, graph_id: [edge])

    result = service.panorama_search("graph-1", "Acme", include_expired=False)

    assert result.active_facts == ["Alice works for Acme"]
    assert result.active_count == 1
    assert result.historical_count == 0


def test_expired_records_remain_historical_even_with_future_fact_end(fixed_time, monkeypatch):
    service = object.__new__(ZepToolsService)
    monkeypatch.setattr(service, "get_all_nodes", lambda graph_id: [])
    monkeypatch.setattr(service, "get_all_edges", lambda *args, **kwargs: [EdgeInfo(
        "edge-1", "WORKS_FOR", "Old fact", "alice", "acme",
        valid_at="2020-01-01T00:00:00Z", invalid_at="2027-01-01T00:00:00Z",
        expired_at="2025-01-01T00:00:00Z",
    )])

    result = service.panorama_search("graph-1", "Acme", include_expired=False)

    assert result.active_facts == []
    assert result.historical_count == 1
