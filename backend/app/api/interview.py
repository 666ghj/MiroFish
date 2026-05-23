from __future__ import annotations
import threading
import traceback
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file
from app.config import Config
from app.models.interview import SubagentKind, InterviewPhase
from app.services.interviews.adapters import FileSystemPersonaProvider, ZepMemoryProvider
from app.services.interviews.zep_writer import InterviewZepWriter
from app.services.interview_orchestrator import InterviewOrchestrator
from app.services.interview_synthesizer import InterviewSynthesizer
from app.services.interviews.storage import InterviewStore
from app.utils.llm_client import LLMClient

from . import interview_bp

_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()

INSTRUMENT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "instruments"


def _uploads_root() -> Path:
    return Path(getattr(Config, "UPLOADS_DIR", "uploads"))


def _build_orchestrator(sim_id: str) -> InterviewOrchestrator:
    sim_dir = _uploads_root() / "simulations" / sim_id
    reddit = sim_dir / "reddit_profiles.json"
    twitter = sim_dir / "twitter_profiles.csv"
    personas = FileSystemPersonaProvider(reddit_path=reddit if reddit.exists() else None,
                                         twitter_path=twitter if twitter.exists() else None)
    # Zep memory + writer: best-effort; in stub/test mode the writer no-ops on exceptions
    class _NullUpdater:
        def add_text_episode(self, *a, **kw): return None
    try:
        from app.services.zep_entity_reader import ZepEntityReader
        from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater
        graph_id = (sim_dir / "graph_id.txt").read_text().strip() if (sim_dir / "graph_id.txt").exists() else ""
        reader = ZepEntityReader()
        updater = ZepGraphMemoryUpdater()
        memory = ZepMemoryProvider(reader, graph_id=graph_id)
        zep_writer = InterviewZepWriter(memory_updater=updater, graph_id=graph_id)
    except Exception:
        class _Mem:
            def get_digest(self, agent_id, max_chars=2000):
                from app.services.interviews.base import MemoryDigest
                return MemoryDigest(text="[memory unavailable]", available=False)
        memory = _Mem()
        zep_writer = InterviewZepWriter(memory_updater=_NullUpdater(), graph_id="")
    llm = LLMClient(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL,
                    model=Config.LLM_MODEL_NAME)
    return InterviewOrchestrator(
        llm=llm, memory=memory, personas=personas,
        instrument_dir=INSTRUMENT_DIR, store_root=_uploads_root(), sim_id=sim_id,
        zep_writer=zep_writer, max_workers=Config.INTERVIEW_MAX_WORKERS,
        language=Config.INTERVIEW_DEFAULT_LANGUAGE,
    )


def _run_task(task_id: str, fn) -> None:
    with _LOCK:
        _TASKS[task_id] = {"status": "running", "progress": {}, "result": None, "error": None}
    try:
        result = fn(task_id)
        with _LOCK:
            _TASKS[task_id]["status"] = "completed"; _TASKS[task_id]["result"] = result
    except Exception as e:
        with _LOCK:
            _TASKS[task_id]["status"] = "failed"
            _TASKS[task_id]["error"] = repr(e)
            _TASKS[task_id]["traceback"] = traceback.format_exc()


def _start_task(fn) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _TASKS[task_id] = {"status": "queued", "progress": {}, "result": None, "error": None}
    threading.Thread(target=_run_task, args=(task_id, fn), daemon=True).start()
    return task_id


def _envelope(data=None, error=None, status: int = 200):
    body = {"success": error is None, "data": data or {}, "error": error}
    return jsonify(body), status


@interview_bp.route("/<sim_id>/pre", methods=["POST"])
def post_pre(sim_id: str):
    orch = _build_orchestrator(sim_id)
    task_id = _start_task(lambda tid: orch.run_pre())
    return _envelope({"task_id": task_id})


@interview_bp.route("/<sim_id>/post", methods=["POST"])
def post_post(sim_id: str):
    orch = _build_orchestrator(sim_id)
    def run(tid):
        out = orch.run_post()
        synth = InterviewSynthesizer(store=orch.store)
        out["synthesis"] = synth.run()[:1000]  # short preview
        return out
    task_id = _start_task(run)
    return _envelope({"task_id": task_id})


@interview_bp.route("/<sim_id>/rerun", methods=["POST"])
def post_rerun(sim_id: str):
    body = request.get_json(silent=True) or {}
    sub = body.get("subagent")
    try: subagent = SubagentKind(sub)
    except ValueError: return _envelope(error=f"unknown subagent {sub!r}", status=400)
    orch = _build_orchestrator(sim_id)
    task_id = _start_task(lambda tid: orch.rerun(subagent))
    return _envelope({"task_id": task_id})


@interview_bp.route("/<sim_id>/status", methods=["GET"])
def get_status(sim_id: str):
    task_id = request.args.get("task_id")
    with _LOCK:
        task = _TASKS.get(task_id)
    if task is None: return _envelope(error="unknown task_id", status=404)
    return _envelope({"status": task["status"], "progress": task.get("progress", {}),
                      "result": task.get("result"), "error": task.get("error")})


@interview_bp.route("/<sim_id>/results/<subagent>", methods=["GET"])
def get_results(sim_id: str, subagent: str):
    try: sub = SubagentKind(subagent)
    except ValueError: return _envelope(error=f"unknown subagent {subagent!r}", status=400)
    store = InterviewStore(root=_uploads_root(), sim_id=sim_id)
    phase = InterviewPhase.T1 if sub != SubagentKind.LONGITUDINAL else InterviewPhase.T1
    run = store.latest_run(phase, sub)
    if run is None: return _envelope(error="no results yet", status=404)
    agg = (run / "aggregate.json")
    if not agg.exists(): return _envelope(error="aggregate missing", status=404)
    import json as _j
    return _envelope({"aggregate": _j.loads(agg.read_text(encoding="utf-8")),
                      "run_dir": str(run)})


@interview_bp.route("/<sim_id>/results/synthesis", methods=["GET"])
def get_synthesis(sim_id: str):
    store = InterviewStore(root=_uploads_root(), sim_id=sim_id)
    report = store.base / "synthesis" / "report.md"
    if not report.exists():
        synth = InterviewSynthesizer(store=store)
        synth.run()
    return _envelope({"report_markdown": report.read_text(encoding="utf-8")})


@interview_bp.route("/<sim_id>/export.csv", methods=["GET"])
def get_export_csv(sim_id: str):
    store = InterviewStore(root=_uploads_root(), sim_id=sim_id)
    csv_path = store.base / "synthesis" / "exports" / "all_responses.csv"
    if not csv_path.exists():
        InterviewSynthesizer(store=store).run()
    return send_file(csv_path, mimetype="text/csv", as_attachment=True,
                     download_name=f"{sim_id}_interviews.csv")
