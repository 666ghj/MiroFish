from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any
from pydantic import BaseModel
from app.models.interview import InterviewPhase, SubagentKind


class InterviewStore:
    def __init__(self, root: Path, sim_id: str):
        self.base = Path(root) / "simulations" / sim_id / "interviews"
        self.base.mkdir(parents=True, exist_ok=True)

    def start_run(self, phase: InterviewPhase, subagent: SubagentKind) -> Path:
        run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = self.base / phase.value / subagent.value / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        meta = {"run_id": run_id, "phase": phase.value, "subagent": subagent.value,
                "created_at": time.time()}
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return run_dir

    def append_response(self, run_dir: Path, model: BaseModel) -> None:
        path = run_dir / "responses.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(model.model_dump_json() + "\n")

    def append_jsonl(self, run_dir: Path, filename: str, payload: dict | BaseModel) -> None:
        path = run_dir / filename
        with path.open("a", encoding="utf-8") as f:
            if isinstance(payload, BaseModel):
                f.write(payload.model_dump_json() + "\n")
            else:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def read_responses(self, run_dir: Path, filename: str = "responses.jsonl") -> list[dict]:
        path = run_dir / filename
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_aggregate(self, run_dir: Path, payload: dict) -> None:
        (run_dir / "aggregate.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_named(self, run_dir: Path, name: str, payload: Any) -> None:
        (run_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def audit(
        self,
        run_dir: Path,
        agent_id: int | None,
        event: str,
        detail: str | dict = "",
    ) -> None:
        entry = {"ts": time.time(), "agent_id": agent_id, "event": event, "detail": detail}
        with (run_dir / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def mark_latest(self, run_dir: Path) -> None:
        pointer = run_dir.parent / "latest.json"
        pointer.write_text(json.dumps({
            "run_dir": str(run_dir.relative_to(self.base)),
        }), encoding="utf-8")

    def latest_run(self, phase: InterviewPhase, subagent: SubagentKind) -> Path | None:
        pointer = self.base / phase.value / subagent.value / "latest.json"
        if not pointer.exists():
            return None
        rel = json.loads(pointer.read_text())["run_dir"]
        path = self.base / rel
        return path if path.exists() else None
