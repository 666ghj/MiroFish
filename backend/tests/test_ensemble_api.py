import json

import pytest
from flask import Flask

from app.api import ensemble_bp, simulation_bp
from app.services.ensemble_runner import EnsembleManager

# Reuse the fake runner / temp-directory environment of the manager tests.
from test_ensemble_manager import (  # noqa: F401  (env is a fixture)
    BASE_ID,
    QUESTIONS,
    drive,
    env,
    rid,
    wait_for,
)


@pytest.fixture
def client(env):
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    app.register_blueprint(ensemble_bp, url_prefix="/api/simulation")
    return app.test_client()


def post(client, path, body=None, **kwargs):
    return client.post(f"/api/simulation{path}", json=body if body is not None else {}, **kwargs)


def create_body(**overrides):
    body = {"simulation_id": BASE_ID, "max_rounds": 12, "n_replicates": 3, "outcome_questions": QUESTIONS,
            "base_seed": 4242}
    body.update(overrides)
    return body


def created(client):
    response = post(client, "/ensemble/create", create_body())
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


# --- create ----------------------------------------------------------------------------

def test_create_returns_the_ensemble_questions_and_cost_estimate(client):
    response = post(client, "/ensemble/create", create_body())
    body = response.get_json()
    assert response.status_code == 201 and body["success"] is True
    data = body["data"]
    assert data["ensemble_id"].startswith("ens_") and data["status"] == "created"
    assert data["base_simulation_id"] == BASE_ID and data["max_rounds"] == 12 and data["base_seed"] == 4242
    assert len(data["replicates"]) == 3 and data["outcome_questions"] == QUESTIONS
    assert data["cost_estimate"]["llm_calls_upper_bound"] > 0
    assert data["progress"]["pending"] == 3


def test_create_needs_a_simulation_id(client):
    response = post(client, "/ensemble/create", {"max_rounds": 5})
    assert response.status_code == 400 and "simulation_id" in response.get_json()["error"]
    zh = post(client, "/ensemble/create", {"max_rounds": 5}, headers={"Accept-Language": "zh"})
    assert zh.status_code == 400 and zh.get_json()["error"] != response.get_json()["error"]


def test_create_needs_max_rounds(client):
    response = post(client, "/ensemble/create", {"simulation_id": BASE_ID, "outcome_questions": QUESTIONS})
    assert response.status_code == 400 and "max_rounds is required" in response.get_json()["error"]


@pytest.mark.parametrize("override", [
    {"n_replicates": 0}, {"n_replicates": 51}, {"concurrency": 9}, {"max_rounds": 0},
    {"platform": "reddit"}, {"base_seed": -5}, {"llm_temperature": 5},
    {"outcome_questions": "nope"}, {"outcome_questions": [{"text": "x", "type": "huh"}]},
])
def test_create_rejects_invalid_parameters_with_a_400(client, override):
    response = post(client, "/ensemble/create", create_body(**override))
    assert response.status_code == 400
    assert response.get_json()["success"] is False and response.get_json()["error"]


def test_create_from_a_missing_or_unprepared_simulation(client, env):
    missing = post(client, "/ensemble/create", create_body(simulation_id="sim_nope"))
    assert missing.status_code == 404
    env.make_base("sim_raw", prepared=False)
    raw = post(client, "/ensemble/create", create_body(simulation_id="sim_raw"))
    assert raw.status_code == 409 and "not prepared" in raw.get_json()["error"]


def test_create_without_questions_derives_them(client, monkeypatch):
    from app.services import ensemble_runner

    monkeypatch.setattr(
        ensemble_runner, "derive_outcome_questions",
        lambda config, llm_json=None: ([{"id": "q1", "text": "Derived?", "type": "probability"}], "llm"),
    )
    body = create_body()
    del body["outcome_questions"]
    data = post(client, "/ensemble/create", body).get_json()["data"]
    assert data["questions_source"] == "llm" and data["outcome_questions"][0]["text"] == "Derived?"


# --- questions, start, stop ------------------------------------------------------------------

def test_questions_can_be_replaced_before_start(client):
    ensemble = created(client)
    new = [{"text": "Which way?", "type": "choice", "options": ["up", "down"]}]
    response = client.put(f"/api/simulation/ensemble/{ensemble['ensemble_id']}/outcome-questions",
                          json={"outcome_questions": new})
    assert response.status_code == 200
    assert response.get_json()["data"]["outcome_questions"][0]["options"] == ["up", "down"]


def test_replacing_questions_validates_and_is_blocked_after_start(client):
    ensemble = created(client)
    url = f"/api/simulation/ensemble/{ensemble['ensemble_id']}/outcome-questions"
    assert client.put(url, json={}).status_code == 400
    assert client.put(url, json={"outcome_questions": "x"}).status_code == 400
    assert client.put(url, json={"outcome_questions": [{"text": "x", "type": "bad"}]}).status_code == 400
    assert client.put("/api/simulation/ensemble/ens_missing/outcome-questions",
                      json={"outcome_questions": []}).status_code == 404

    assert post(client, f"/ensemble/{ensemble['ensemble_id']}/start").status_code == 200
    late = client.put(url, json={"outcome_questions": QUESTIONS})
    assert late.status_code == 409 and "before the ensemble starts" in late.get_json()["error"]


def test_start_runs_the_ensemble_and_a_second_start_conflicts(client, env):
    ensemble = created(client)
    started = post(client, f"/ensemble/{ensemble['ensemble_id']}/start")
    assert started.status_code == 200 and started.get_json()["data"]["status"] == "running"
    again = post(client, f"/ensemble/{ensemble['ensemble_id']}/start")
    assert again.status_code == 409
    assert post(client, "/ensemble/ens_missing/start").status_code == 404

    drive(env, ensemble["ensemble_id"], {})
    final = client.get(f"/api/simulation/ensemble/{ensemble['ensemble_id']}").get_json()["data"]
    assert final["status"] == "completed" and final["progress"]["completed"] == 3


def test_stop_marks_the_ensemble_stopped(client, env):
    ensemble = created(client)
    post(client, f"/ensemble/{ensemble['ensemble_id']}/start")
    wait_for(lambda: len(env.runner.running()) == 1)
    response = post(client, f"/ensemble/{ensemble['ensemble_id']}/stop")
    assert response.status_code == 200 and response.get_json()["data"]["status"] == "stopped"
    assert post(client, "/ensemble/ens_missing/stop").status_code == 404


# --- reading ------------------------------------------------------------------------------------

def test_get_reports_per_replicate_progress(client, env):
    ensemble = created(client)
    post(client, f"/ensemble/{ensemble['ensemble_id']}/start")
    wait_for(lambda: len(env.runner.running()) == 1)
    env.runner.states[rid(ensemble, 1)].current_round = 5
    data = client.get(f"/api/simulation/ensemble/{ensemble['ensemble_id']}").get_json()["data"]
    first = data["replicates"][0]
    assert (first["current_round"], first["total_rounds"], first["status"]) == (5, 12, "running")
    assert client.get("/api/simulation/ensemble/ens_missing").status_code == 404
    drive(env, ensemble["ensemble_id"], {})


def test_summary_is_404_until_the_ensemble_has_been_aggregated(client, env):
    ensemble = created(client)
    url = f"/api/simulation/ensemble/{ensemble['ensemble_id']}/summary"
    assert client.get(url).status_code == 404
    assert client.get("/api/simulation/ensemble/ens_missing/summary").status_code == 404

    post(client, f"/ensemble/{ensemble['ensemble_id']}/start")
    drive(env, ensemble["ensemble_id"], {})
    response = client.get(url)
    summary = response.get_json()["data"]
    assert response.status_code == 200
    assert summary["ensemble_id"] == ensemble["ensemble_id"] and summary["n_replicates_ok"] == 3
    assert "not calibrated probabilities" in summary["caveat"]


def test_list_filters_by_base_simulation(client, env):
    env.make_base("sim_other")
    first = created(client)
    post(client, "/ensemble/create", create_body(simulation_id="sim_other"))
    everything = client.get("/api/simulation/ensemble/list").get_json()
    assert everything["count"] == 2 and everything["success"] is True
    only = client.get(f"/api/simulation/ensemble/list?simulation_id={BASE_ID}").get_json()
    assert [e["ensemble_id"] for e in only["data"]] == [first["ensemble_id"]]
    assert client.get("/api/simulation/ensemble/list?simulation_id=sim_x").get_json()["data"] == []


def test_the_list_route_is_not_shadowed_by_the_id_route(client):
    created(client)
    response = client.get("/api/simulation/ensemble/list")
    assert response.status_code == 200 and isinstance(response.get_json()["data"], list)


# --- replicates stay out of the simulation lists ------------------------------------------------------

def test_simulation_list_hides_replicates_unless_asked(client):
    ensemble = created(client)
    ids = [s["simulation_id"] for s in client.get("/api/simulation/list").get_json()["data"]]
    assert ids == [BASE_ID]
    shown = client.get("/api/simulation/list?include_replicates=true").get_json()
    assert {s["simulation_id"] for s in shown["data"]} == {BASE_ID, *[r["simulation_id"] for r in ensemble["replicates"]]}
    assert shown["count"] == 4
    assert client.get("/api/simulation/list?include_replicates=false").get_json()["count"] == 1


def test_simulation_history_hides_replicates_unless_asked(client):
    ensemble = created(client)
    history = client.get("/api/simulation/history").get_json()
    assert [s["simulation_id"] for s in history["data"]] == [BASE_ID]
    shown = client.get("/api/simulation/history?include_replicates=1").get_json()
    assert shown["count"] == 4
    replicate_entry = next(s for s in shown["data"] if s["simulation_id"] == rid(ensemble, 1))
    assert replicate_entry["ensemble_id"] == ensemble["ensemble_id"] and replicate_entry["replicate_index"] == 1


def test_the_history_limit_applies_after_replicates_are_filtered(client):
    created(client)
    history = client.get("/api/simulation/history?limit=1").get_json()
    assert [s["simulation_id"] for s in history["data"]] == [BASE_ID]


def test_ensemble_json_on_disk_is_valid_after_the_api_flow(client, env):
    ensemble = created(client)
    on_disk = json.loads((env.ensembles / ensemble["ensemble_id"] / "ensemble.json").read_text(encoding="utf-8"))
    assert on_disk["replicates"][0]["seed"] == ensemble["replicates"][0]["seed"]
    assert EnsembleManager.load_outcome_questions(ensemble["ensemble_id"]) == QUESTIONS
