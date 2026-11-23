from types import SimpleNamespace

import pytest

from app.utils import zep_paging

GRAPH_UUID = "00000000-0000-4000-8000-000000000001"


def _page(items, next_cursor=None):
    return SimpleNamespace(
        items=items,
        response=SimpleNamespace(next_cursor=next_cursor),
    )


def _client(list_edges=None):
    return SimpleNamespace(
        graph=SimpleNamespace(
            edge=SimpleNamespace(
                list=list_edges or (lambda *_args, **_kwargs: _page([]))
            )
        )
    )


def test_edge_cap_stops_pagination_at_requested_limit(monkeypatch):
    pages = [
        _page(
            [SimpleNamespace(uuid_="e1"), SimpleNamespace(uuid_="e2")],
            "opaque-page-2",
        ),
        _page(
            [SimpleNamespace(uuid_="e3"), SimpleNamespace(uuid_="e4")],
        ),
    ]
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(kwargs)
        return pages[len(calls) - 1]

    monkeypatch.setattr(zep_paging, "_fetch_page_with_retry", fake_fetch)

    result = zep_paging.fetch_all_edges(
        _client(),
        GRAPH_UUID,
        page_size=2,
        max_items=3,
    )

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
    assert len(calls) == 2
    assert calls[1]["cursor"] == "opaque-page-2"


def test_existing_positional_retry_arguments_keep_their_meaning(monkeypatch):
    observed = {}

    def fake_fetch(*args, **kwargs):
        observed.update(kwargs)
        return _page([])

    monkeypatch.setattr(zep_paging, "_fetch_page_with_retry", fake_fetch)

    zep_paging.fetch_all_edges(_client(), GRAPH_UUID, 25, 7, 0.25)

    assert observed["page_size"] == 25
    assert observed["cursor"] is None
    assert observed["max_retries"] == 7
    assert observed["retry_delay"] == 0.25


def test_pagination_uses_the_current_opaque_response_cursor():
    calls = []

    def list_edges(graph_uuid, **kwargs):
        calls.append((graph_uuid, kwargs))
        if kwargs["cursor"] is None:
            return _page(
                [SimpleNamespace(uuid_="e1"), SimpleNamespace(uuid_="e2")],
                "opaque-page-2",
            )
        return _page([SimpleNamespace(uuid_="e3")])

    result = zep_paging.fetch_all_edges(
        _client(list_edges),
        GRAPH_UUID,
        page_size=2,
    )

    assert [edge.uuid_ for edge in result] == ["e1", "e2", "e3"]
    assert calls == [
        (GRAPH_UUID, {"page_size": 2, "cursor": None}),
        (GRAPH_UUID, {"page_size": 2, "cursor": "opaque-page-2"}),
    ]


def test_pagination_fails_if_the_service_repeats_a_cursor():
    client = _client(
        lambda *_args, **_kwargs: _page(
            [SimpleNamespace(uuid_="e1")],
            "same-cursor",
        )
    )

    with pytest.raises(RuntimeError, match="did not advance"):
        zep_paging.fetch_all_edges(client, GRAPH_UUID, page_size=1)


@pytest.mark.parametrize("page_size", [0, 101])
def test_pagination_rejects_page_sizes_outside_the_v4_limit(page_size):
    with pytest.raises(ValueError, match="page_size"):
        zep_paging.fetch_all_edges(_client(), GRAPH_UUID, page_size=page_size)
