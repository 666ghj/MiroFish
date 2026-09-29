"""Experimental async Plot Counterfactual run registry for the fork.

The registry owns no Canon and persists no accepted novel facts. It does keep
its opaque run request and typed branch results in a sidecar-local JSON store
so a process restart can recover completed snapshots without re-running them.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .novel_world import (
    WorldAction,
    WorldSimulationError,
    WorldSnapshot,
    WorldStateDelta,
    apply_action,
    branch_snapshot,
)


class CounterfactualBranchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branchId: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list, max_length=32)
    actions: list[WorldAction] = Field(default_factory=list, max_length=32)


class CounterfactualRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str | None = None
    sourceRevision: int = Field(ge=0)
    inputHash: str = Field(min_length=1)
    baseSnapshot: WorldSnapshot
    branches: list[CounterfactualBranchRequest] = Field(min_length=1, max_length=8)
    maxActions: int = Field(default=32, ge=1, le=32)

    @model_validator(mode="after")
    def validate_source_and_branches(self) -> "CounterfactualRunRequest":
        if self.baseSnapshot.sourceRevision != self.sourceRevision:
            raise ValueError("sourceRevision does not match baseSnapshot")
        if self.baseSnapshot.inputHash != self.inputHash:
            raise ValueError("inputHash does not match baseSnapshot")
        branch_ids = [branch.branchId for branch in self.branches]
        if len(branch_ids) != len(set(branch_ids)):
            raise ValueError("branchId must be unique within one run")
        if self.baseSnapshot.branchId in branch_ids:
            raise ValueError("branchId must differ from the base snapshot branch")
        return self


class CounterfactualBranchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branchId: str
    assumptions: list[str]
    status: str
    finalSnapshot: WorldSnapshot | None = None
    deltas: list[WorldStateDelta] = Field(default_factory=list)
    error: str | None = None


class CounterfactualRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str
    sourceRevision: int
    inputHash: str
    status: str
    branches: list[CounterfactualBranchResult] = Field(default_factory=list)
    error: str | None = None


@dataclass
class _CounterfactualRun:
    request: CounterfactualRunRequest
    run_id: str
    status: str = "queued"
    branches: dict[str, CounterfactualBranchResult] = field(default_factory=dict)
    error: str | None = None
    stop_requested: bool = False


class CounterfactualRunNotFound(KeyError):
    """The requested run or branch is not known to this sidecar process/store."""


class CounterfactualRunRegistry:
    """Bounded async lifecycle backed by a sidecar-local atomic JSON store."""

    STORE_VERSION = 1
    INTERRUPTED_ERROR = "sidecar restarted before the counterfactual run completed"

    def __init__(self, max_workers: int = 2, store_path: str | Path | None = None):
        self._lock = Lock()
        configured_path = store_path or os.environ.get("NOVEL_COUNTERFACTUAL_STORE_PATH")
        self._store_path = Path(configured_path) if configured_path else (
            Path(__file__).resolve().parents[2] / "uploads" / "counterfactual" / "runs.json"
        )
        self._runs: dict[str, _CounterfactualRun] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="novel-cf")
        self._load()

    @property
    def store_path(self) -> Path:
        """Expose the runtime path for diagnostics and isolated acceptance tests."""

        return self._store_path

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"unable to load counterfactual store {self._store_path}: {error}") from error
        if not isinstance(payload, dict) or payload.get("version") != self.STORE_VERSION:
            raise RuntimeError(f"unsupported counterfactual store format: {self._store_path}")
        records = payload.get("runs")
        if not isinstance(records, list):
            raise RuntimeError(f"counterfactual store runs must be a list: {self._store_path}")
        for raw in records:
            if not isinstance(raw, dict):
                raise RuntimeError(f"counterfactual store contains a non-object run: {self._store_path}")
            try:
                request = CounterfactualRunRequest.model_validate(raw["request"])
                run_id = str(raw["run_id"])
                status = str(raw.get("status", "failed"))
                branches_payload = raw.get("branches", {})
                if not isinstance(branches_payload, dict):
                    raise ValueError("branches must be an object")
                branches = {
                    branch_id: CounterfactualBranchResult.model_validate(branch)
                    for branch_id, branch in branches_payload.items()
                }
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(f"invalid counterfactual store record: {self._store_path}: {error}") from error
            error = raw.get("error")
            if error is not None and not isinstance(error, str):
                raise RuntimeError(f"counterfactual store error must be a string: {self._store_path}")
            if status in {"queued", "running", "stopping"}:
                status = "failed"
                error = self.INTERRUPTED_ERROR
            self._runs[run_id] = _CounterfactualRun(
                request=request,
                run_id=run_id,
                status=status,
                branches=branches,
                error=error,
                stop_requested=False,
            )

    def _persist_locked(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.STORE_VERSION,
            "runs": [
                {
                    "run_id": record.run_id,
                    "request": record.request.model_dump(mode="json"),
                    "status": record.status,
                    "branches": {
                        branch_id: result.model_dump(mode="json")
                        for branch_id, result in record.branches.items()
                    },
                    "error": record.error,
                }
                for record in self._runs.values()
            ],
        }
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._store_path.parent,
                prefix=f".{self._store_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._store_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def create(self, request: CounterfactualRunRequest) -> CounterfactualRunSummary:
        run_id = request.runId or f"cf-{uuid4().hex}"
        with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None:
                if (
                    existing.request.sourceRevision != request.sourceRevision
                    or existing.request.inputHash != request.inputHash
                ):
                    raise WorldSimulationError("runId already belongs to another source revision or input hash")
                return self._summary_locked(existing)
            record = _CounterfactualRun(request=request, run_id=run_id)
            self._runs[run_id] = record
            try:
                self._persist_locked()
            except Exception:
                del self._runs[run_id]
                raise
            self._executor.submit(self._execute, run_id)
            return self._summary_locked(record)

    def summary(self, run_id: str) -> CounterfactualRunSummary:
        with self._lock:
            return self._summary_locked(self._require_locked(run_id))

    def branch(self, run_id: str, branch_id: str) -> CounterfactualBranchResult:
        with self._lock:
            record = self._require_locked(run_id)
            result = record.branches.get(branch_id)
            if result is None:
                raise CounterfactualRunNotFound(f"unknown branch: {branch_id}")
            return result.model_copy(deep=True)

    def stop(self, run_id: str) -> CounterfactualRunSummary:
        with self._lock:
            record = self._require_locked(run_id)
            if record.status in {"queued", "running"}:
                record.stop_requested = True
                record.status = "stopping"
                self._persist_locked()
            return self._summary_locked(record)

    def _execute(self, run_id: str) -> None:
        with self._lock:
            record = self._require_locked(run_id)
            record.status = "running"
            request = record.request
            self._persist_locked()
        try:
            for branch_request in request.branches:
                with self._lock:
                    record = self._require_locked(run_id)
                    if record.stop_requested:
                        record.status = "stopped"
                        self._persist_locked()
                        return
                branch = branch_snapshot(request.baseSnapshot, branch_request.branchId)
                deltas: list[WorldStateDelta] = []
                try:
                    for action in branch_request.actions:
                        with self._lock:
                            record = self._require_locked(run_id)
                            if record.stop_requested:
                                record.status = "stopped"
                                self._persist_locked()
                                return
                        if len(deltas) >= request.maxActions:
                            raise WorldSimulationError(
                                f"action count exceeds maxActions {request.maxActions}"
                            )
                        branch, delta = apply_action(branch, action)
                        deltas.append(delta)
                    result = CounterfactualBranchResult(
                        branchId=branch_request.branchId,
                        assumptions=branch_request.assumptions,
                        status="completed",
                        finalSnapshot=branch,
                        deltas=deltas,
                    )
                except WorldSimulationError as error:
                    result = CounterfactualBranchResult(
                        branchId=branch_request.branchId,
                        assumptions=branch_request.assumptions,
                        status="failed",
                        deltas=deltas,
                        error=str(error),
                    )
                    with self._lock:
                        record = self._require_locked(run_id)
                        record.branches[branch_request.branchId] = result
                        record.status = "failed"
                        record.error = str(error)
                        self._persist_locked()
                    return
                with self._lock:
                    record = self._require_locked(run_id)
                    record.branches[branch_request.branchId] = result
                    self._persist_locked()
            with self._lock:
                record = self._require_locked(run_id)
                record.status = "completed" if not record.stop_requested else "stopped"
                self._persist_locked()
        except Exception as error:
            with self._lock:
                record = self._require_locked(run_id)
                record.status = "failed"
                record.error = str(error)
                self._persist_locked()

    def shutdown(self) -> None:
        """Stop worker threads; the Flask process normally exits with the registry."""

        self._executor.shutdown(wait=True)

    def _require_locked(self, run_id: str) -> _CounterfactualRun:
        record = self._runs.get(run_id)
        if record is None:
            raise CounterfactualRunNotFound(f"unknown run: {run_id}")
        return record

    @staticmethod
    def _summary_locked(record: _CounterfactualRun) -> CounterfactualRunSummary:
        return CounterfactualRunSummary(
            runId=record.run_id,
            sourceRevision=record.request.sourceRevision,
            inputHash=record.request.inputHash,
            status=record.status,
            branches=[result.model_copy(deep=True) for result in record.branches.values()],
            error=record.error,
        )


counterfactual_runs = CounterfactualRunRegistry()
