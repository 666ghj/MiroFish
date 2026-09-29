"""M2 async counterfactual lifecycle contract tests."""

from __future__ import annotations

import time

from app import create_app
from app.services.novel_counterfactual import CounterfactualRunRegistry, CounterfactualRunRequest
from app.services.novel_world import (
    WorldAction,
    WorldEffect,
    WorldPrecondition,
    WorldState,
    create_snapshot,
)


def _client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _base_snapshot():
    return create_snapshot(
        source_revision=7,
        input_hash="seed-m2",
        state=WorldState(
            entities={
                "linyan": {"kind": "character", "location": "harbor", "trust": 1},
                "harbor": {"kind": "location", "open": True},
                "old-port": {"kind": "location", "open": True},
            },
            facts={"storyTime": "night-1"},
        ),
    )


def _move_action(action_id: str, target: str) -> dict:
    return WorldAction(
        actionId=action_id,
        sourceRevision=7,
        inputHash="seed-m2",
        actorId="linyan",
        actionType="move",
        preconditions=[
            WorldPrecondition(entityId="linyan", field="location", expected="harbor"),
        ],
        effects=[
            WorldEffect(entityId="linyan", field="location", operation="set", value=target),
        ],
    ).model_dump(mode="json")


def _wait_for(client, run_id: str, expected: str = "completed") -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get(f"/api/novel/counterfactual/run/{run_id}")
        assert response.status_code == 200, response.json
        data = response.json["data"]
        if data["status"] in {expected, "failed", "stopped"}:
            return data
        time.sleep(0.01)
    raise AssertionError(f"run did not settle: {run_id}")


def test_async_run_branch_snapshot_and_diff_lifecycle():
    client = _client()
    request = {
        "runId": "cf-m2-green",
        "sourceRevision": 7,
        "inputHash": "seed-m2",
        "baseSnapshot": _base_snapshot().model_dump(mode="json"),
        "branches": [
            {"branchId": "north", "assumptions": ["追查旧港"], "actions": [_move_action("move-north", "old-port")]},
            {"branchId": "stay", "assumptions": ["留在港务"], "actions": []},
        ],
    }

    queued = client.post("/api/novel/counterfactual/run", json=request)
    assert queued.status_code == 202, queued.json
    assert queued.json["data"]["status"] in {"queued", "running", "completed"}

    settled = _wait_for(client, "cf-m2-green")
    assert settled["status"] == "completed"
    assert {branch["branchId"] for branch in settled["branches"]} == {"north", "stay"}

    snapshot = client.get("/api/novel/counterfactual/run/cf-m2-green/branches/north/snapshot")
    assert snapshot.status_code == 200, snapshot.json
    assert snapshot.json["data"]["state"]["entities"]["linyan"]["location"] == "old-port"

    diff = client.get("/api/novel/counterfactual/run/cf-m2-green/branches/north/diff")
    assert diff.status_code == 200, diff.json
    assert diff.json["data"]["deltas"][0]["actionId"] == "move-north"


def test_run_failure_is_structured_and_does_not_return_a_final_snapshot():
    client = _client()
    request = {
        "runId": "cf-m2-failed",
        "sourceRevision": 7,
        "inputHash": "seed-m2",
        "baseSnapshot": _base_snapshot().model_dump(mode="json"),
        "branches": [{"branchId": "bad", "actions": [_move_action("move-bad", "missing-place")]}],
    }

    response = client.post("/api/novel/counterfactual/run", json=request)
    assert response.status_code == 202
    settled = _wait_for(client, "cf-m2-failed")
    assert settled["status"] == "failed"
    assert settled["branches"][0]["status"] == "failed"
    assert settled["branches"][0]["finalSnapshot"] is None
    assert "unknown entity" in settled["branches"][0]["error"]


def test_run_id_cannot_be_reused_for_another_source_revision():
    client = _client()
    request = {
        "runId": "cf-m2-idempotency",
        "sourceRevision": 7,
        "inputHash": "seed-m2",
        "baseSnapshot": _base_snapshot().model_dump(mode="json"),
        "branches": [{"branchId": "one", "actions": []}],
    }
    assert client.post("/api/novel/counterfactual/run", json=request).status_code == 202

    conflicting = {**request, "sourceRevision": 8}
    response = client.post("/api/novel/counterfactual/run", json=conflicting)
    assert response.status_code == 400
    assert "sourceRevision" in response.json["error"]


def test_completed_run_and_snapshot_survive_registry_restart(tmp_path):
    store_path = tmp_path / "counterfactual-runs.json"
    request = CounterfactualRunRequest(
        runId="cf-persisted",
        sourceRevision=7,
        inputHash="seed-m2",
        baseSnapshot=_base_snapshot(),
        branches=[
            {
                "branchId": "north",
                "assumptions": ["重启后仍可读取"],
                "actions": [_move_action("move-persisted", "old-port")],
            },
        ],
    )

    first = CounterfactualRunRegistry(store_path=store_path)
    try:
        first.create(request)
        deadline = time.monotonic() + 2
        while first.summary("cf-persisted").status not in {"completed", "failed", "stopped"}:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert first.summary("cf-persisted").status == "completed"
    finally:
        first.shutdown()

    restarted = CounterfactualRunRegistry(store_path=store_path)
    try:
        recovered = restarted.summary("cf-persisted")
        assert recovered.status == "completed"
        assert recovered.branches[0].finalSnapshot is not None
        assert recovered.branches[0].finalSnapshot.snapshotHash == first.summary("cf-persisted").branches[0].finalSnapshot.snapshotHash
        assert restarted.branch("cf-persisted", "north").deltas[0].actionId == "move-persisted"
    finally:
        restarted.shutdown()
