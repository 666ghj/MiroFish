"""M0 experimental counterfactual HTTP contract tests."""

from __future__ import annotations

from app import create_app
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


def _base_snapshot_payload() -> dict:
    snapshot = create_snapshot(
        source_revision=5,
        input_hash="seed-hash",
        state=WorldState(
            entities={
                "linyan": {"kind": "character", "location": "harbor"},
                "harbor": {"kind": "location", "open": True},
                "old-port": {"kind": "location", "open": True},
            },
            facts={"storyTime": "night-1"},
        ),
    )
    return snapshot.model_dump(mode="json")


def _action_payload() -> dict:
    return WorldAction(
        actionId="move-1",
        sourceRevision=5,
        inputHash="seed-hash",
        actorId="linyan",
        actionType="move",
        preconditions=[
            WorldPrecondition(entityId="linyan", field="location", expected="harbor"),
        ],
        effects=[
            WorldEffect(entityId="linyan", field="location", operation="set", value="old-port"),
        ],
    ).model_dump(mode="json")


def test_capabilities_identify_the_experimental_m0_contract():
    response = _client().get("/api/novel/counterfactual/capabilities")

    assert response.status_code == 200
    data = response.json["data"]
    assert data["protocolVersion"] == "novel-counterfactual/0.1"
    assert data["stage"] == "m2-experimental"
    assert "branch" in data["capabilities"]
    assert "plot-counterfactual" in data["experimentalModes"]
    assert data["productModes"] == []


def test_branch_and_replay_are_http_only_and_do_not_need_neo4j():
    client = _client()
    base = _base_snapshot_payload()

    branch_response = client.post(
        "/api/novel/counterfactual/branch",
        json={"snapshot": base, "branchId": "what-if-a"},
    )
    assert branch_response.status_code == 200, branch_response.json
    branch = branch_response.json["data"]
    assert branch["branchId"] == "what-if-a"
    assert branch["baseSnapshotHash"] == base["snapshotHash"]

    replay_response = client.post(
        "/api/novel/counterfactual/replay",
        json={"baseSnapshot": branch, "actions": [_action_payload()]},
    )
    assert replay_response.status_code == 200, replay_response.json
    final = replay_response.json["data"]["finalSnapshot"]
    assert final["step"] == 1
    assert final["state"]["entities"]["linyan"]["location"] == "old-port"
    assert replay_response.json["data"]["deltas"][0]["actionId"] == "move-1"


def test_replay_rejects_tampered_snapshot_hash():
    base = _base_snapshot_payload()
    base["snapshotHash"] = "tampered"

    response = _client().post(
        "/api/novel/counterfactual/replay",
        json={"baseSnapshot": base, "actions": []},
    )

    assert response.status_code == 400
    assert "snapshot hash mismatch" in response.json["error"]
