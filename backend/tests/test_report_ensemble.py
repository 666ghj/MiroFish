"""Stage 4: reports built on an ensemble (ReportAgent, ReportManager and /api/report/generate)."""
import json
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report_bp
from app.models.project import ProjectStatus
from app.services.ensemble_runner import EnsembleManager
from app.services.report_agent import (
    Report,
    ReportAgent,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
)
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import RunnerStatus

# Reuse the fake runner / temp-directory environment of the ensemble tests.
from test_ensemble_manager import (  # noqa: F401  (env is a fixture)
    BASE_ID,
    create,
    drive,
    env,
    rid,
)

NARRATIVE = "Prices will rally after the demerger."
FOUR_TOOLS = ["insight_forge", "panorama_search", "quick_search", "interview_agents"]


# --- fakes -----------------------------------------------------------------------------------

class ScriptedLLM:
    """Plans two sections, then answers each section after one call to every tool in ``tools``."""

    def __init__(self, tools=("quick_search", "ensemble_stats", "panorama_search")):
        self.tools = tools
        self.plans = []
        self.sections = []

    def chat_json(self, messages, temperature=0.3):
        self.plans.append(messages)
        return {"title": "Findings report", "summary": "S", "sections": [{"title": "Findings"}, {"title": "Doubt"}]}

    def chat(self, messages, temperature=0.5, max_tokens=4096):
        self.sections.append(messages)
        done = sum(1 for m in messages if m["role"] == "assistant")
        if done < len(self.tools):
            name = self.tools[done]
            params = {"section": "q1"} if name == "ensemble_stats" else {"query": "x"}
            return '<tool_call>{"name": "%s", "parameters": %s}</tool_call>' % (name, json.dumps(params))
        return "Final Answer: P(q1) ranged from 60 to 80 across the runs."


class FakeZep:
    def get_simulation_context(self, graph_id, simulation_requirement):
        return {"graph_statistics": {"total_nodes": 3, "total_edges": 4, "entity_types": {"Person": 2}},
                "total_entities": 3, "related_facts": ["fact one", "fact two"]}

    def quick_search(self, **_kwargs):
        return SimpleNamespace(to_text=lambda: "quick result")

    def panorama_search(self, **_kwargs):
        return SimpleNamespace(to_text=lambda: "panorama result")

    def insight_forge(self, **_kwargs):
        return SimpleNamespace(to_text=lambda: "insight result")


def plain_agent(llm=None):
    return ReportAgent("graph_1", BASE_ID, "Will HEGAM rise?", llm_client=llm or ScriptedLLM(), zep_tools=FakeZep())


def finished_ensemble(env, polls=(60, 70, 80)):
    """An aggregated ensemble whose replicates each answered q1 with one number."""
    path = env.sims / BASE_ID / "simulation_config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["event_config"]["narrative_direction"] = NARRATIVE
    path.write_text(json.dumps(config), encoding="utf-8")

    ensemble = create(env, n_replicates=len(polls))
    for index, value in enumerate(polls, start=1):
        row = {"agent_id": 0, "agent_name": "A0", "stance_initial": "neutral", "answers": {"q1": value},
               "reason": "", "raw": "{}", "parse_ok": True}
        (env.sims / rid(ensemble, index) / "final_poll.json").write_text(json.dumps([row]), encoding="utf-8")
    EnsembleManager.start(ensemble["ensemble_id"])
    drive(env, ensemble["ensemble_id"], {})
    assert EnsembleManager.get(ensemble["ensemble_id"])["status"] == "completed"
    return ensemble


def ensemble_agent(env, llm=None, ensemble=None):
    ensemble = ensemble or finished_ensemble(env)
    return ReportAgent("graph_1", BASE_ID, "Will HEGAM rise?", llm_client=llm or ScriptedLLM(), zep_tools=FakeZep(),
                       ensemble_id=ensemble["ensemble_id"])


@pytest.fixture
def reports(monkeypatch, tmp_path):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    return tmp_path / "reports"


# --- a report without an ensemble is exactly what it was -------------------------------------------

def test_a_plain_agent_keeps_its_four_tools_and_mentions_no_ensemble():
    llm = ScriptedLLM(tools=("quick_search", "panorama_search", "insight_forge"))
    agent = plain_agent(llm)
    assert agent.ensemble_id is None and list(agent.tools) == FOUR_TOOLS
    assert "ensemble" not in agent._get_tools_description().lower()
    assert agent._ensemble_plan_context() == "" and agent._ensemble_section_rules() == ""

    outline = agent.plan_outline()
    agent._generate_section_react(ReportSection(title="Findings"), outline, [])
    prompts = " ".join(m["content"] for call in llm.plans + llm.sections for m in call)
    assert "ensemble" not in prompts.lower() and "集合运行" not in prompts


def test_a_plain_agent_rejects_the_ensemble_tool():
    agent = plain_agent()
    assert agent._is_valid_tool_call({"name": "ensemble_stats", "parameters": {}}) is False
    assert agent._execute_tool("ensemble_stats", {"section": "q1"}).startswith("未知工具")
    assert agent._parse_tool_calls('{"name": "ensemble_stats", "parameters": {}}') == []


def test_a_plain_report_serialises_an_empty_ensemble_id():
    report = Report("r1", BASE_ID, "graph_1", "Req", ReportStatus.PENDING)
    assert report.ensemble_id is None and report.to_dict()["ensemble_id"] is None


def test_a_report_saved_before_ensembles_existed_still_loads(reports):
    folder = reports / "report_legacy"
    folder.mkdir(parents=True)
    legacy = {"report_id": "report_legacy", "simulation_id": BASE_ID, "graph_id": "graph_1",
              "simulation_requirement": "Req", "status": "completed", "created_at": "2026-01-01T00:00:00",
              "completed_at": "2026-01-01T00:10:00", "error": None, "markdown_content": "# Old"}
    (folder / "meta.json").write_text(json.dumps(legacy), encoding="utf-8")
    report = ReportManager.get_report("report_legacy")
    assert report is not None and report.ensemble_id is None and report.markdown_content == "# Old"


# --- the ensemble agent ---------------------------------------------------------------------------

def test_an_ensemble_agent_gets_ensemble_stats_as_a_fifth_tool(env):
    agent = ensemble_agent(env)
    assert list(agent.tools) == FOUR_TOOLS + ["ensemble_stats"]
    assert "ensemble_stats" in agent._get_tools_description()
    assert agent._is_valid_tool_call({"name": "ensemble_stats", "parameters": {}}) is True
    calls = agent._parse_tool_calls('{"name": "ensemble_stats", "parameters": {"section": "q1"}}')
    assert [c["name"] for c in calls] == ["ensemble_stats"]


def test_an_ensemble_report_needs_an_aggregated_ensemble(env):
    created = create(env, n_replicates=2)  # never started: no summary yet
    with pytest.raises(ValueError, match="聚合结果"):
        ReportAgent("graph_1", BASE_ID, "Req", llm_client=ScriptedLLM(), zep_tools=FakeZep(),
                    ensemble_id=created["ensemble_id"])
    with pytest.raises(ValueError):
        ReportAgent("graph_1", BASE_ID, "Req", llm_client=ScriptedLLM(), zep_tools=FakeZep(),
                    ensemble_id="ens_does_not_exist")


def test_planning_sees_the_summary_the_caveat_and_the_hypothesis(env):
    llm = ScriptedLLM()
    agent = ensemble_agent(env, llm)
    caveat = EnsembleManager.summary(agent.ensemble_id)["caveat"]
    agent.plan_outline()

    prompt = llm.plans[0][1]["content"]
    assert prompt.startswith("【集合运行统计摘要】（基于 3 次")
    assert caveat in prompt and NARRATIVE in prompt
    assert "从未提供给任何Agent" in prompt  # the hypothesis is labelled as untested and never shown to agents
    assert "fact one" in prompt  # the normal planning context still follows
    assert prompt.index(NARRATIVE) < prompt.index("fact one")


def test_the_hypothesis_is_labelled_when_the_generator_gave_none(env):
    ensemble = finished_ensemble(env)
    path = env.sims / BASE_ID / "simulation_config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["event_config"].pop("narrative_direction")
    path.write_text(json.dumps(config), encoding="utf-8")
    assert "生成器没有给出假设" in ensemble_agent(env, ensemble=ensemble)._ensemble_section_rules()


def test_sections_get_the_tool_hint_and_the_ensemble_rules(env):
    llm = ScriptedLLM()
    agent = ensemble_agent(env, llm)
    caveat = EnsembleManager.summary(agent.ensemble_id)["caveat"]
    agent._generate_section_react(ReportSection(title="Findings"), ReportOutline("T", "S", []), [])

    system = llm.sections[0][0]["content"]
    assert "- ensemble_stats:" in system  # listed next to the other tools in the usage advice
    assert "【集合运行规则 - 必须遵守】" in system
    assert caveat in system and NARRATIVE in system
    assert "p10–p90" in system and "证实 / 部分证实 / 推翻" in system


def test_ensemble_stats_returns_the_overview_by_default(env):
    agent = ensemble_agent(env)
    for parameters in ({}, {"section": "overview"}, {"section": ""}, {"query": "overview"}):
        result = json.loads(agent._execute_tool("ensemble_stats", parameters))
        assert result["n_replicates_ok"] == 3 and result["caveat"].startswith("These are distributions")
        assert "q1" in result["available_sections"]


def test_ensemble_stats_returns_one_question_with_its_range_across_runs(env):
    agent = ensemble_agent(env)
    result = json.loads(agent._execute_tool("ensemble_stats", {"section": "Q1"}))
    assert result["question"] == "q1" and result["replicates_with_data"] == 3
    spread = result["agent_mean"]
    assert (spread["min"], spread["median"], spread["max"]) == (60, 70, 80)
    assert spread["p10"] < 70 < spread["p90"] and result["share_of_replicates_mean_above_50"] == 1.0


def test_ensemble_stats_lists_what_is_available_for_an_unknown_section(env):
    agent = ensemble_agent(env)
    result = json.loads(agent._execute_tool("ensemble_stats", {"section": "nonsense"}))
    assert "unknown section" in result["error"] and "behavior" in result["available_sections"]
    for section in ("polls", "stance_drift", "behavior", "hot_topics", "replicates"):
        assert section in json.loads(agent._execute_tool("ensemble_stats", {"section": section}))


def test_a_section_can_call_ensemble_stats_and_the_tool_is_offered_until_it_is_used(env):
    llm = ScriptedLLM(tools=("quick_search", "quick_search", "quick_search"))
    agent = ensemble_agent(env, llm)
    text = agent._generate_section_react(ReportSection(title="Findings"), ReportOutline("T", "S", []), [])
    assert text.startswith("P(q1) ranged")
    observations = [m["content"] for m in llm.sections[-1] if m["role"] == "user"][1:]
    assert any("ensemble_stats" in o for o in observations)  # still listed among the unused tools


def test_an_ensemble_report_is_generated_end_to_end_and_remembers_its_ensemble(env, reports):
    llm = ScriptedLLM()
    agent = ensemble_agent(env, llm)
    report = agent.generate_report(report_id="report_ens_1")
    assert report.status == ReportStatus.COMPLETED, report.error
    assert report.ensemble_id == agent.ensemble_id
    assert "P(q1) ranged from 60 to 80" in report.markdown_content

    saved = ReportManager.get_report("report_ens_1")
    assert saved.ensemble_id == agent.ensemble_id
    assert json.loads((reports / "report_ens_1" / "meta.json").read_text(encoding="utf-8"))["ensemble_id"] == agent.ensemble_id
    # the planning call and every section call carried the ensemble material
    assert "【集合运行统计摘要】" in llm.plans[0][1]["content"]
    assert all("【集合运行规则" in call[0]["content"] for call in llm.sections)


# --- ReportManager.find_completed_report ---------------------------------------------------------

def stored(report_id, ensemble_id=None, status=ReportStatus.COMPLETED, created_at="2026-10-01T00:00:00", sim=BASE_ID):
    ReportManager.save_report(Report(report_id, sim, "graph_1", "Req", status, markdown_content="# R",
                                     created_at=created_at, ensemble_id=ensemble_id))


def test_a_plain_report_never_stands_in_for_an_ensemble_report_or_the_reverse(reports):
    stored("report_plain")
    assert ReportManager.find_completed_report(BASE_ID).report_id == "report_plain"
    assert ReportManager.find_completed_report(BASE_ID, "ens_a") is None
    stored("report_a", "ens_a", created_at="2026-10-02T00:00:00")
    assert ReportManager.find_completed_report(BASE_ID, "ens_a").report_id == "report_a"
    assert ReportManager.find_completed_report(BASE_ID, "ens_b") is None
    assert ReportManager.find_completed_report(BASE_ID).report_id == "report_plain"


def test_find_completed_report_takes_the_newest_completed_match(reports):
    stored("report_old", "ens_a", created_at="2026-10-01T00:00:00")
    stored("report_new", "ens_a", created_at="2026-10-03T00:00:00")
    stored("report_failed", "ens_a", status=ReportStatus.FAILED, created_at="2026-10-05T00:00:00")
    stored("report_other_sim", "ens_a", created_at="2026-10-09T00:00:00", sim="sim_other")
    assert ReportManager.find_completed_report(BASE_ID, "ens_a").report_id == "report_new"
    assert ReportManager.find_completed_report("sim_unknown", "ens_a") is None


# --- POST /api/report/generate with an ensemble ------------------------------------------------------

@pytest.fixture
def api(env, reports, monkeypatch):
    """The report blueprint with the heavy collaborators replaced; the ensemble side is real."""
    from app.api import report as report_api

    state = SimpleNamespace(project_id="proj_1", graph_id="graph_1")
    project = SimpleNamespace(project_id="proj_1", graph_id="graph_1", status=ProjectStatus.GRAPH_COMPLETED,
                              simulation_requirement="Will HEGAM rise?")
    base_run = {"state": None}  # the base simulation itself: never run when an ensemble is used
    workers, agents, tasks = [], [], []

    class Tasks:
        def create_task(self, **kwargs):
            tasks.append(kwargs)
            return f"task_{len(tasks)}"

        def update_task(self, *_a, **_k):
            pass

        def complete_task(self, *_a, **_k):
            pass

        def fail_task(self, *_a, **_k):
            raise AssertionError(f"report task failed: {_a}")

    class ParkedThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            workers.append(self.target)

    class Agent:
        def __init__(self, **kwargs):
            agents.append(kwargs)

        def generate_report(self, *, progress_callback, report_id):
            ensemble_id = agents[-1].get("ensemble_id")
            return Report(report_id, BASE_ID, "graph_1", "Req", ReportStatus.COMPLETED,
                          markdown_content="# R", created_at="2026-10-09T00:00:00", ensemble_id=ensemble_id)

    def run_state_of(_cls, simulation_id):
        # the base simulation has its own state; replicates answer from the fake runner
        return base_run["state"] if simulation_id == BASE_ID else env.runner.get_state(simulation_id)

    monkeypatch.setattr(report_api, "SimulationManager",
                        lambda: SimpleNamespace(get_simulation=lambda sid: state if sid == BASE_ID else None))
    monkeypatch.setattr(report_api.ProjectManager, "get_project", classmethod(lambda _c, _pid: project))
    monkeypatch.setattr(report_api.SimulationRunner, "get_run_state", classmethod(run_state_of))
    monkeypatch.setattr(report_api.ZepGraphMemoryManager, "get_updater", classmethod(lambda _c, _sid: None))
    monkeypatch.setattr(report_api, "TaskManager", Tasks)
    monkeypatch.setattr(report_api, "ReportAgent", Agent)
    # replace the name inside report.py only: EnsembleManager needs the real threading.Thread
    monkeypatch.setattr(report_api, "threading", SimpleNamespace(Thread=ParkedThread))

    app = Flask(__name__)
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    def generate(body):
        response = client.post("/api/report/generate", json=body)
        while workers:  # run the parked background reports so their graph leases are released
            workers.pop(0)()
        return response

    return SimpleNamespace(generate=generate, base_run=base_run, agents=agents, tasks=tasks, client=client,
                           workers=workers)


def completed_run():
    return SimpleNamespace(runner_status=RunnerStatus.COMPLETED)


def test_an_ensemble_report_does_not_need_the_base_simulation_to_have_run(env, api):
    ensemble = finished_ensemble(env)
    assert api.base_run["state"] is None
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": ensemble["ensemble_id"]})
    body = response.get_json()
    assert response.status_code == 200 and body["success"] is True, body
    assert body["data"]["ensemble_id"] == ensemble["ensemble_id"] and body["data"]["already_generated"] is False
    assert api.agents[0]["ensemble_id"] == ensemble["ensemble_id"]
    assert api.tasks[0]["metadata"]["ensemble_id"] == ensemble["ensemble_id"]
    assert ReportManager.get_report(body["data"]["report_id"]).ensemble_id == ensemble["ensemble_id"]


def test_a_plain_report_still_needs_a_finished_run(env, api):
    response = api.generate({"simulation_id": BASE_ID})
    assert response.status_code == 409 and "successfully completed" in response.get_json()["error"]
    assert api.agents == []

    api.base_run["state"] = completed_run()
    ok = api.generate({"simulation_id": BASE_ID})
    assert ok.status_code == 200 and ok.get_json()["data"]["ensemble_id"] is None
    assert api.agents[0]["ensemble_id"] is None


def test_a_running_base_simulation_still_blocks_an_ensemble_report(env, api):
    ensemble = finished_ensemble(env)
    api.base_run["state"] = SimpleNamespace(runner_status=RunnerStatus.RUNNING)
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": ensemble["ensemble_id"]})
    assert response.status_code == 409 and api.agents == []


@pytest.mark.parametrize("bad", [123, ["ens_x"], "", "   ", {"id": "x"}, True])
def test_ensemble_id_must_be_a_non_empty_string(env, api, bad):
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": bad})
    assert response.status_code == 400 and "ensemble_id" in response.get_json()["error"]
    assert api.agents == []


def test_an_unknown_ensemble_is_a_404(env, api):
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": "ens_nope"})
    assert response.status_code == 404 and api.agents == []


def test_an_ensemble_of_another_simulation_is_rejected(env, api):
    ensemble = finished_ensemble(env)
    env.make_base("sim_other")
    other = EnsembleManager.create("sim_other", n_replicates=2, max_rounds=5, outcome_questions=[
        {"id": "q1", "text": "Will it rise?", "type": "probability"}], base_seed=5)
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": other["ensemble_id"]})
    assert response.status_code == 400 and "different simulation" in response.get_json()["error"]
    assert ensemble["ensemble_id"] != other["ensemble_id"] and api.agents == []


def test_an_ensemble_that_has_not_finished_cannot_be_reported_on(env, api):
    created = create(env, n_replicates=2)  # status: created
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": created["ensemble_id"]})
    assert response.status_code == 409 and "not finished" in response.get_json()["error"]

    EnsembleManager.start(created["ensemble_id"])  # running
    response = api.generate({"simulation_id": BASE_ID, "ensemble_id": created["ensemble_id"]})
    assert response.status_code == 409 and api.agents == []
    EnsembleManager.stop(created["ensemble_id"])
    stopped = api.generate({"simulation_id": BASE_ID, "ensemble_id": created["ensemble_id"]})
    assert stopped.status_code == 409 and api.agents == []


def test_a_completed_report_is_reused_only_for_the_same_ensemble(env, api):
    ensemble = finished_ensemble(env)
    api.base_run["state"] = completed_run()
    stored("report_plain")
    stored("report_ens", ensemble["ensemble_id"], created_at="2026-10-02T00:00:00")

    plain = api.generate({"simulation_id": BASE_ID}).get_json()["data"]
    assert plain["already_generated"] is True and plain["report_id"] == "report_plain" and plain["ensemble_id"] is None
    with_ensemble = api.generate({"simulation_id": BASE_ID, "ensemble_id": ensemble["ensemble_id"]}).get_json()["data"]
    assert with_ensemble["already_generated"] is True and with_ensemble["report_id"] == "report_ens"
    assert with_ensemble["ensemble_id"] == ensemble["ensemble_id"]
    assert api.agents == []  # nothing was regenerated


def test_a_plain_report_does_not_satisfy_an_ensemble_request(env, api):
    ensemble = finished_ensemble(env)
    stored("report_plain")
    body = api.generate({"simulation_id": BASE_ID, "ensemble_id": ensemble["ensemble_id"]}).get_json()["data"]
    assert body["already_generated"] is False and body["report_id"] != "report_plain"
    assert len(api.agents) == 1


def test_force_regenerate_builds_a_new_ensemble_report(env, api):
    ensemble = finished_ensemble(env)
    stored("report_ens", ensemble["ensemble_id"])
    body = api.generate({"simulation_id": BASE_ID, "ensemble_id": ensemble["ensemble_id"],
                         "force_regenerate": True}).get_json()["data"]
    assert body["already_generated"] is False and body["report_id"] != "report_ens"
    assert api.agents[0]["ensemble_id"] == ensemble["ensemble_id"]


def test_the_report_endpoints_expose_the_ensemble_id(env, api):
    ensemble = finished_ensemble(env)
    report_id = api.generate({"simulation_id": BASE_ID, "ensemble_id": ensemble["ensemble_id"]}).get_json()["data"]["report_id"]
    fetched = api.client.get(f"/api/report/{report_id}").get_json()
    assert fetched["success"] is True and fetched["data"]["ensemble_id"] == ensemble["ensemble_id"]
