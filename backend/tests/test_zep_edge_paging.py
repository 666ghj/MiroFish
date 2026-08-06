from types import SimpleNamespace

from app.utils import zep_paging


def _client():
    edge_api = SimpleNamespace(
        with_raw_response=SimpleNamespace(
            get_by_graph_id=lambda *args, **kwargs: SimpleNamespace(
                data=[],
                headers={},
            )
        )
    )
    return SimpleNamespace(graph=SimpleNamespace(edge=edge_api))


def test_edge_cap_stops_pagination_at_requested_limit(monkeypatch):
    pages = [
        SimpleNamespace(
            data=[SimpleNamespace(uuid_="e1"), SimpleNamespace(uuid_="e2")],
            headers={"Zep-Next-Cursor": "opaque-page-2"},
        ),
        SimpleNamespace(
            data=[SimpleNamespace(uuid_="e3"), SimpleNamespace(uuid_="e4")],
            headers={},
        ),
    ]
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(kwargs)
        return pages[len(calls) - 1]

    monkeypatch.setattr(zep_paging, "_fetch_page_with_retry", fake_fetch)

    result = zep_paging.fetch_all_edges(_client(), "graph", page_size=2, max_items=3)

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
    assert len(calls) == 2
    assert calls[1]["cursor"] == "opaque-page-2"


def test_existing_positional_retry_arguments_keep_their_meaning(monkeypatch):
    observed = {}

    def fake_fetch(*args, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(data=[], headers={})

    monkeypatch.setattr(zep_paging, "_fetch_page_with_retry", fake_fetch)

    zep_paging.fetch_all_edges(_client(), "graph", 25, 7, 0.25)

    assert observed["limit"] == 25
    assert observed["max_retries"] == 7
    assert observed["retry_delay"] == 0.25


def test_pagination_uses_the_current_opaque_response_cursor():
    calls = []

    class RawEdgeApi:
        def get_by_graph_id(self, graph_id, **kwargs):
            calls.append((graph_id, kwargs))
            if kwargs.get("cursor") is None:
                return SimpleNamespace(
                    data=[SimpleNamespace(uuid_="e1"), SimpleNamespace(uuid_="e2")],
                    headers={"Zep-Next-Cursor": "opaque-page-2"},
                )
            return SimpleNamespace(
                data=[SimpleNamespace(uuid_="e3")],
                headers={},
            )

    class EdgeApi:
        with_raw_response = RawEdgeApi()

        def get_by_graph_id(self, *_args, **_kwargs):
            raise AssertionError("pagination must read the response cursor header")

    client = SimpleNamespace(
        graph=SimpleNamespace(edge=EdgeApi())
    )

    result = zep_paging.fetch_all_edges(client, "graph", page_size=2)

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
    assert calls == [
        ("graph", {"limit": 2}),
        ("graph", {"limit": 2, "cursor": "opaque-page-2"}),
    ]


def test_pagination_fails_if_the_service_repeats_a_cursor():
    class RawEdgeApi:
        def get_by_graph_id(self, _graph_id, **_kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(uuid_="e1")],
                headers={"Zep-Next-Cursor": "same-cursor"},
            )

    client = SimpleNamespace(
        graph=SimpleNamespace(
            edge=SimpleNamespace(with_raw_response=RawEdgeApi())
        )
    )

    import pytest

    with pytest.raises(RuntimeError, match="did not advance"):
        zep_paging.fetch_all_edges(client, "graph", page_size=1)
