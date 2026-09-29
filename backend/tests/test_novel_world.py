"""M0 contract tests for the deterministic novel world-state spike."""

from __future__ import annotations

import pytest

from app.services.novel_world import (
    WorldAction,
    WorldEffect,
    WorldPrecondition,
    WorldSimulationError,
    WorldState,
    branch_snapshot,
    create_snapshot,
    replay_actions,
    snapshot_digest,
)


def base_snapshot():
    return create_snapshot(
        source_revision=5,
        input_hash="seed-hash",
        state=WorldState(
            entities={
                "linyan": {"kind": "character", "location": "harbor", "trust": 1},
                "harbor": {"kind": "location", "open": True},
                "old-port": {"kind": "location", "open": True},
                "ledger": {"kind": "object", "holder": "linyan"},
            },
            facts={"storyTime": "night-1"},
        ),
    )


def move_action(action_id: str = "move-1") -> WorldAction:
    return WorldAction(
        actionId=action_id,
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
        cost={"time": 1},
    )


def test_snapshot_hash_is_canonical_across_mapping_order():
    first = base_snapshot()
    second = create_snapshot(
        source_revision=5,
        input_hash="seed-hash",
        state=WorldState(
            facts={"storyTime": "night-1"},
            entities={
                "ledger": {"holder": "linyan", "kind": "object"},
                "harbor": {"open": True, "kind": "location"},
                "old-port": {"open": True, "kind": "location"},
                "linyan": {"trust": 1, "location": "harbor", "kind": "character"},
            },
        ),
    )
    assert first.snapshotHash == second.snapshotHash
    assert snapshot_digest(first) == first.snapshotHash


def test_action_produces_source_bearing_delta_and_replayable_snapshot():
    final, deltas = replay_actions(base_snapshot(), [move_action()])

    assert final.step == 1
    assert final.parentSnapshotHash == base_snapshot().snapshotHash
    assert final.state.entities["linyan"]["location"] == "old-port"
    assert deltas[0].changes[0].before == "harbor"
    assert deltas[0].changes[0].after == "old-port"
    assert deltas[0].snapshotHash == final.snapshotHash


def test_failed_precondition_does_not_return_a_successful_state():
    action = move_action()
    action.preconditions[0].expected = "wrong-place"

    with pytest.raises(WorldSimulationError, match="precondition failed"):
        replay_actions(base_snapshot(), [action])


def test_branch_starts_from_a_frozen_base_without_mutating_it():
    base = base_snapshot()
    branch = branch_snapshot(base, "what-if-a")
    final, _ = replay_actions(branch, [move_action("branch-move")])

    assert branch.branchId == "what-if-a"
    assert branch.baseSnapshotHash == base.snapshotHash
    assert branch.state == base.state
    assert final.branchId == "what-if-a"
    assert base.snapshotHash == snapshot_digest(base)




def test_replay_rejects_duplicate_actions_and_cross_revision_actions():
    with pytest.raises(WorldSimulationError, match="actionId must be unique"):
        replay_actions(base_snapshot(), [move_action(), move_action()])

    mismatched = move_action()
    mismatched.sourceRevision = 6
    with pytest.raises(WorldSimulationError, match="sourceRevision"):
        replay_actions(base_snapshot(), [mismatched])


def test_named_world_actions_cover_resource_time_relationship_and_knowledge_state():
    base = base_snapshot()
    transfer = WorldAction(
        actionId="transfer-1",
        sourceRevision=5,
        inputHash="seed-hash",
        actorId="linyan",
        actionType="resource-transfer",
        effects=[
            WorldEffect(entityId="ledger", field="holderId", operation="set", value="linyan"),
            WorldEffect(entityId="ledger", field="quantity", operation="set", value=2),
        ],
    )
    after_transfer, _ = replay_actions(base, [transfer])
    assert after_transfer.state.entities["ledger"]["quantity"] == 2

    advance = WorldAction(
        actionId="time-1",
        sourceRevision=5,
        inputHash="seed-hash",
        actorId="linyan",
        actionType="advance-story-time",
        effects=[
            WorldEffect(
                scope="fact",
                entityId="__world__",
                field="storyTime",
                operation="set",
                value="night-2",
            ),
        ],
    )
    after_time, deltas = replay_actions(after_transfer, [advance])
    assert after_time.state.facts["storyTime"] == "night-2"
    assert deltas[0].changes[0].scope == "fact"

    relationship = WorldAction(
        actionId="relationship-1",
        sourceRevision=5,
        inputHash="seed-hash",
        actorId="linyan",
        actionType="relationship-transition",
        effects=[
            WorldEffect(entityId="linyan", field="trust", operation="set", value=2),
        ],
    )
    after_relationship, _ = replay_actions(after_time, [relationship])
    assert after_relationship.state.entities["linyan"]["trust"] == 2

    knowledge = WorldAction(
        actionId="knowledge-1",
        sourceRevision=5,
        inputHash="seed-hash",
        actorId="linyan",
        actionType="knowledge-reveal",
        effects=[
            WorldEffect(entityId="linyan", field="knowledge", operation="set", value=["dock-7"]),
        ],
    )
    after_knowledge, _ = replay_actions(after_relationship, [knowledge])
    assert after_knowledge.state.entities["linyan"]["knowledge"] == ["dock-7"]


def test_named_world_actions_reject_invalid_resource_and_unknown_action_types():
    invalid_resource = WorldAction(
        actionId="resource-bad",
        sourceRevision=5,
        inputHash="seed-hash",
        actorId="linyan",
        actionType="resource-consume",
        effects=[
            WorldEffect(entityId="ledger", field="quantity", operation="set", value=-1),
        ],
    )
    with pytest.raises(WorldSimulationError, match="non-negative"):
        replay_actions(base_snapshot(), [invalid_resource])

    with pytest.raises(ValueError, match="unsupported actionType"):
        WorldAction(
            actionId="unknown",
            sourceRevision=5,
            inputHash="seed-hash",
            actorId="linyan",
            actionType="teleport-story",
            effects=[
                WorldEffect(entityId="linyan", field="location", operation="set", value="elsewhere"),
            ],
        )
