"""M0 typed world-state spike for novel counterfactual experiments.

This module is deliberately independent from OASIS and the graph backend. It
proves that a frozen novel state can be changed by validated typed actions,
branched, hashed and replayed without touching Canon or an external store.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorldSimulationError(ValueError):
    """A typed action cannot be applied to the frozen simulation state."""


WORLD_ENTITY_KINDS = frozenset(
    {
        "character",
        "reader",
        "faction",
        "location",
        "object",
        "resource",
        "relationship",
        "knowledge",
        "world-rule",
        "promise",
        "debt",
    }
)
class WorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: dict[str, dict[str, Any]] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_entity_ids(self) -> "WorldState":
        for entity_id, entity in self.entities.items():
            if not entity_id.strip():
                raise ValueError("entities must not contain an empty id")
            kind = entity.get("kind")
            if kind not in WORLD_ENTITY_KINDS:
                raise ValueError(
                    f"entity {entity_id} must declare one of the supported kinds: {sorted(WORLD_ENTITY_KINDS)}"
                )
        return self


class WorldPrecondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["entity", "fact"] = "entity"
    entityId: str
    field: str
    expected: Any = None
    present: bool = True


class WorldEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["entity", "fact"] = "entity"
    entityId: str
    field: str
    operation: Literal["set", "remove"]
    value: Any = None


SUPPORTED_ACTION_TYPES = frozenset(
    {
        "set",
        "remove",
        "move",
        "containment",
        "resource-transfer",
        "resource-consume",
        "relationship-transition",
        "knowledge-reveal",
        "advance-story-time",
        "rule-transition",
        "debt-transition",
    }
)


class WorldAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actionId: str
    sourceRevision: int = Field(ge=0)
    inputHash: str = Field(min_length=1)
    actorId: str = Field(min_length=1)
    actionType: str = Field(min_length=1)
    preconditions: list[WorldPrecondition] = Field(default_factory=list)
    effects: list[WorldEffect] = Field(min_length=1)
    cost: Any = None

    @model_validator(mode="after")
    def validate_action_id(self) -> "WorldAction":
        if not self.actionId.strip():
            raise ValueError("actionId must not be empty")
        if self.actionType not in SUPPORTED_ACTION_TYPES:
            raise ValueError(f"unsupported actionType: {self.actionType}")
        return self


class WorldSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceRevision: int = Field(ge=0)
    inputHash: str = Field(min_length=1)
    branchId: str = Field(min_length=1)
    step: int = Field(ge=0)
    parentSnapshotHash: str | None = None
    baseSnapshotHash: str | None = None
    state: WorldState
    snapshotHash: str = Field(min_length=1)


class WorldStateChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["entity", "fact"] = "entity"
    entityId: str
    field: str
    operation: Literal["set", "remove"]
    before: Any = None
    after: Any = None


class WorldStateDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actionId: str
    actionType: str
    branchId: str
    sourceRevision: int
    inputHash: str
    parentSnapshotHash: str
    snapshotHash: str
    changes: list[WorldStateChange]


class WorldReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseSnapshot: WorldSnapshot
    actions: list[WorldAction] = Field(default_factory=list)
    maxActions: int = Field(default=32, ge=1, le=32)


_MISSING = object()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _snapshot_payload(
    *,
    source_revision: int,
    input_hash: str,
    branch_id: str,
    step: int,
    parent_snapshot_hash: str | None,
    base_snapshot_hash: str | None,
    state: WorldState,
) -> dict[str, Any]:
    return {
        "sourceRevision": source_revision,
        "inputHash": input_hash,
        "branchId": branch_id,
        "step": step,
        "parentSnapshotHash": parent_snapshot_hash,
        "baseSnapshotHash": base_snapshot_hash,
        "state": state.model_dump(mode="json"),
    }


def snapshot_digest(snapshot: WorldSnapshot) -> str:
    """Return the canonical hash for a snapshot, excluding its stored hash."""

    payload = _snapshot_payload(
        source_revision=snapshot.sourceRevision,
        input_hash=snapshot.inputHash,
        branch_id=snapshot.branchId,
        step=snapshot.step,
        parent_snapshot_hash=snapshot.parentSnapshotHash,
        base_snapshot_hash=snapshot.baseSnapshotHash,
        state=snapshot.state,
    )
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def verify_snapshot(snapshot: WorldSnapshot) -> None:
    expected = snapshot_digest(snapshot)
    if snapshot.snapshotHash != expected:
        raise WorldSimulationError(
            f"snapshot hash mismatch: expected {expected}, got {snapshot.snapshotHash}"
        )


def create_snapshot(
    *,
    source_revision: int,
    input_hash: str,
    state: WorldState,
    branch_id: str = "main",
    step: int = 0,
    parent_snapshot_hash: str | None = None,
    base_snapshot_hash: str | None = None,
) -> WorldSnapshot:
    payload = _snapshot_payload(
        source_revision=source_revision,
        input_hash=input_hash,
        branch_id=branch_id,
        step=step,
        parent_snapshot_hash=parent_snapshot_hash,
        base_snapshot_hash=base_snapshot_hash,
        state=state,
    )
    snapshot_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return WorldSnapshot(snapshotHash=snapshot_hash, **payload)


def branch_snapshot(snapshot: WorldSnapshot, branch_id: str) -> WorldSnapshot:
    verify_snapshot(snapshot)
    if not branch_id.strip() or branch_id == snapshot.branchId:
        raise WorldSimulationError("branchId must be non-empty and distinct from the source branch")
    return create_snapshot(
        source_revision=snapshot.sourceRevision,
        input_hash=snapshot.inputHash,
        state=copy.deepcopy(snapshot.state),
        branch_id=branch_id,
        parent_snapshot_hash=snapshot.snapshotHash,
        base_snapshot_hash=snapshot.snapshotHash,
    )


def _read_field(state: WorldState, scope: str, entity_id: str, field: str) -> Any:
    if scope == "fact":
        return state.facts.get(field, _MISSING)
    entity = state.entities.get(entity_id)
    if entity is None:
        raise WorldSimulationError(f"unknown entity: {entity_id}")
    return entity.get(field, _MISSING)


def _entity_kind(state: WorldState, entity_id: str) -> str:
    entity = state.entities.get(entity_id)
    if entity is None:
        raise WorldSimulationError(f"unknown entity: {entity_id}")
    return str(entity["kind"])


def _display(value: Any) -> str:
    return "<missing>" if value is _MISSING else _canonical_json(value)


def _validate_action_semantics(state: WorldState, action: WorldAction) -> None:
    """Keep named action types explicit while effects remain auditable deltas."""

    if action.actionType in {"set", "remove"}:
        return
    if action.actorId not in state.entities:
        raise WorldSimulationError(f"unknown actor: {action.actorId}")

    entity_effects = [effect for effect in action.effects if effect.scope == "entity"]
    if action.actionType in {"move", "containment"}:
        expected_field = "location" if action.actionType == "move" else "containerId"
        if len(action.effects) != 1:
            raise WorldSimulationError(f"{action.actionType} requires exactly one effect")
        effect = action.effects[0]
        if effect.scope != "entity" or effect.field != expected_field or effect.operation != "set":
            raise WorldSimulationError(
                f"{action.actionType} must set entity.{expected_field}"
            )
        if not isinstance(effect.value, str) or not effect.value.strip():
            raise WorldSimulationError(f"{action.actionType} target must be a non-empty string")
        target_kind = _entity_kind(state, effect.value)
        allowed_kinds = {"location"} if action.actionType == "move" else {
            "location", "object", "resource"
        }
        if target_kind not in allowed_kinds:
            raise WorldSimulationError(
                f"{action.actionType} target {effect.value} has unsupported kind {target_kind}"
            )
        return

    if action.actionType in {"resource-transfer", "resource-consume"}:
        quantity_effects = [effect for effect in entity_effects if effect.field == "quantity"]
        if len(quantity_effects) != 1:
            raise WorldSimulationError(f"{action.actionType} requires one quantity effect")
        quantity = quantity_effects[0].value
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or quantity < 0:
            raise WorldSimulationError("resource quantity must be a non-negative number")
        if action.actionType == "resource-transfer" and not any(
            effect.field in {"holderId", "ownerId"} and effect.operation == "set"
            for effect in entity_effects
        ):
            raise WorldSimulationError("resource-transfer requires a holderId or ownerId effect")
        return

    if action.actionType == "relationship-transition":
        if not any(effect.field in {"relationship", "stage", "trust", "status"} for effect in entity_effects):
            raise WorldSimulationError("relationship-transition requires a relationship state effect")
        return

    if action.actionType == "knowledge-reveal":
        if not any(effect.field in {"knowledge", "known", "belief"} for effect in entity_effects):
            raise WorldSimulationError("knowledge-reveal requires a knowledge or belief effect")
        return

    if action.actionType == "advance-story-time":
        if not any(
            effect.scope == "fact" and effect.field == "storyTime" and effect.operation == "set"
            for effect in action.effects
        ):
            raise WorldSimulationError("advance-story-time requires a fact.storyTime effect")
        return

    if action.actionType == "rule-transition":
        if not any(effect.field in {"state", "status"} for effect in entity_effects):
            raise WorldSimulationError("rule-transition requires a state or status effect")
        return

    if action.actionType == "debt-transition":
        if not any(effect.field in {"state", "status", "resolution"} for effect in entity_effects):
            raise WorldSimulationError("debt-transition requires a debt state effect")
        return

    raise WorldSimulationError(f"unsupported actionType: {action.actionType}")


def apply_action(
    snapshot: WorldSnapshot,
    action: WorldAction,
) -> tuple[WorldSnapshot, WorldStateDelta]:
    verify_snapshot(snapshot)
    if action.sourceRevision != snapshot.sourceRevision:
        raise WorldSimulationError(
            f"action sourceRevision {action.sourceRevision} does not match snapshot {snapshot.sourceRevision}"
        )
    if action.inputHash != snapshot.inputHash:
        raise WorldSimulationError("action inputHash does not match snapshot")
    _validate_action_semantics(snapshot.state, action)

    seen_effects: set[tuple[str, str, str]] = set()
    for precondition in action.preconditions:
        actual = _read_field(
            snapshot.state,
            precondition.scope,
            precondition.entityId,
            precondition.field,
        )
        if precondition.present:
            if actual is _MISSING or actual != precondition.expected:
                raise WorldSimulationError(
                    f"precondition failed for {precondition.entityId}.{precondition.field}: "
                    f"expected {_display(precondition.expected)}, got {_display(actual)}"
                )
        elif actual is not _MISSING:
            raise WorldSimulationError(
                f"precondition failed for {precondition.entityId}.{precondition.field}: field is present"
            )

    next_state = copy.deepcopy(snapshot.state)
    changes: list[WorldStateChange] = []
    for effect in action.effects:
        key = (effect.scope, effect.entityId, effect.field)
        if key in seen_effects:
            raise WorldSimulationError(
                f"action contains duplicate effect target: {effect.scope}.{effect.entityId}.{effect.field}"
            )
        seen_effects.add(key)
        if effect.scope == "fact":
            target = next_state.facts
        else:
            target = next_state.entities.get(effect.entityId)
            if target is None:
                raise WorldSimulationError(f"unknown entity: {effect.entityId}")
        before = target.get(effect.field, _MISSING)
        if effect.operation == "remove":
            if before is _MISSING:
                raise WorldSimulationError(
                    f"cannot remove missing field: {effect.scope}.{effect.entityId}.{effect.field}"
                )
            del target[effect.field]
            after = _MISSING
        else:
            target[effect.field] = copy.deepcopy(effect.value)
            after = effect.value
        changes.append(
            WorldStateChange(
                scope=effect.scope,
                entityId=effect.entityId,
                field=effect.field,
                operation=effect.operation,
                before=None if before is _MISSING else copy.deepcopy(before),
                after=None if after is _MISSING else copy.deepcopy(after),
            )
        )

    next_snapshot = create_snapshot(
        source_revision=snapshot.sourceRevision,
        input_hash=snapshot.inputHash,
        state=next_state,
        branch_id=snapshot.branchId,
        step=snapshot.step + 1,
        parent_snapshot_hash=snapshot.snapshotHash,
        base_snapshot_hash=snapshot.baseSnapshotHash,
    )
    delta = WorldStateDelta(
        actionId=action.actionId,
        actionType=action.actionType,
        branchId=snapshot.branchId,
        sourceRevision=snapshot.sourceRevision,
        inputHash=snapshot.inputHash,
        parentSnapshotHash=snapshot.snapshotHash,
        snapshotHash=next_snapshot.snapshotHash,
        changes=changes,
    )
    return next_snapshot, delta


def replay_actions(
    base_snapshot: WorldSnapshot,
    actions: list[WorldAction],
    *,
    max_actions: int = 32,
) -> tuple[WorldSnapshot, list[WorldStateDelta]]:
    verify_snapshot(base_snapshot)
    if len(actions) > max_actions:
        raise WorldSimulationError(
            f"action count {len(actions)} exceeds max_actions {max_actions}"
        )
    action_ids = [action.actionId for action in actions]
    if len(action_ids) != len(set(action_ids)):
        raise WorldSimulationError("actionId must be unique within one replay")
    current = base_snapshot
    deltas: list[WorldStateDelta] = []
    for action in actions:
        current, delta = apply_action(current, action)
        deltas.append(delta)
    return current, deltas
