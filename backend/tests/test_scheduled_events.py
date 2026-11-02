import json

import pytest
from flask import Flask

from app.api import simulation_bp
from app.services.scheduled_events import (
    MAX_EVENT_CONTENT_CHARS,
    MAX_SCHEDULED_EVENTS,
    validate_scheduled_events,
)
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus


def make_config(total_hours=48):
    return {
        "time_config": {"total_simulation_hours": total_hours, "minutes_per_round": 60},
        "agent_configs": [
            {"agent_id": 0, "entity_type": "Organization", "influence_weight": 1.0},
            {"agent_id": 1, "entity_type": "MediaOutlet", "influence_weight": 2.0},
            {"agent_id": 2, "entity_type": "Person", "influence_weight": 0.5},
        ],
        "event_config": {"initial_posts": [], "scheduled_events": [], "topic": "t"},
    }


def event(**overrides):
    base = {"at_sim_hour": 5, "poster_agent_id": 1, "content": "Breaking news"}
    base.update(overrides)
    return base


# --- validation --------------------------------------------------------------

def test_a_valid_event_is_normalised():
    events, errors = validate_scheduled_events([event()], make_config())
    assert errors == []
    assert events == [{
        "id": "evt_1", "at_sim_hour": 5, "poster_agent_id": 1, "poster_type": "MediaOutlet",
        "content": "Breaking news", "source": "user", "enabled": True,
    }]


def test_events_are_sorted_by_hour_and_ids_are_generated_without_clashes():
    events, errors = validate_scheduled_events(
        [event(at_sim_hour=20, id="evt_1"), event(at_sim_hour=3), event(at_sim_hour=3.0, content="b")],
        make_config(),
    )
    assert errors == []
    assert [e["at_sim_hour"] for e in events] == [3, 3, 20]
    ids = [e["id"] for e in events]
    assert len(set(ids)) == 3 and "evt_1" in ids
    assert [e["content"] for e in events if e["at_sim_hour"] == 20] == ["Breaking news"]


def test_fractional_hours_are_kept_and_integral_floats_become_ints():
    events, errors = validate_scheduled_events(
        [event(at_sim_hour=1.5), event(at_sim_hour=4.0)], make_config()
    )
    assert errors == []
    assert [e["at_sim_hour"] for e in events] == [1.5, 4]
    assert isinstance(events[1]["at_sim_hour"], int)


def test_poster_type_is_resolved_to_an_agent():
    events, errors = validate_scheduled_events(
        [{"at_sim_hour": 2, "poster_type": "MediaOutlet", "content": "x"}], make_config()
    )
    assert errors == []
    assert events[0]["poster_agent_id"] == 1 and events[0]["poster_type"] == "MediaOutlet"


def test_an_explicit_poster_wins_over_the_poster_type_and_keeps_a_given_type():
    events, _ = validate_scheduled_events(
        [event(poster_agent_id=2, poster_type="Custom label")], make_config()
    )
    assert events[0]["poster_agent_id"] == 2 and events[0]["poster_type"] == "Custom label"


def test_whitespace_is_trimmed_and_flags_are_preserved():
    events, errors = validate_scheduled_events(
        [event(content="  hello  ", enabled=False, source="llm_suggested", id="  mine ")], make_config()
    )
    assert errors == []
    assert events[0]["content"] == "hello" and events[0]["enabled"] is False
    assert events[0]["source"] == "llm_suggested" and events[0]["id"] == "mine"


@pytest.mark.parametrize(
    "bad,fragment",
    [
        (event(at_sim_hour=-1), "outside the simulation"),
        (event(at_sim_hour=48), "outside the simulation"),
        (event(at_sim_hour=9999), "outside the simulation"),
        (event(at_sim_hour="5"), "at_sim_hour must be a number"),
        (event(at_sim_hour=True), "at_sim_hour must be a number"),
        (event(at_sim_hour=float("nan")), "at_sim_hour must be a number"),
        (event(at_sim_hour=None), "at_sim_hour must be a number"),
        (event(content=""), "content must be a non-empty string"),
        (event(content="   \n"), "content must be a non-empty string"),
        (event(content=None), "content must be a non-empty string"),
        (event(content=5), "content must be a non-empty string"),
        (event(content="x" * (MAX_EVENT_CONTENT_CHARS + 1)), "longer than"),
        (event(poster_agent_id=99), "not an agent"),
        (event(poster_agent_id="1"), "not an agent"),
        (event(poster_agent_id=True), "not an agent"),
        ({"at_sim_hour": 1, "content": "x"}, "provide poster_agent_id or poster_type"),
        (event(source="robot"), "source must be one of"),
        (event(enabled="yes"), "enabled must be true or false"),
        ("not an object", "must be an object"),
    ],
)
def test_invalid_events_are_reported(bad, fragment):
    events, errors = validate_scheduled_events([bad], make_config())
    assert events == []
    assert len(errors) == 1 and fragment in errors[0]
    assert errors[0].startswith("event 1")


def test_every_bad_event_is_reported_not_just_the_first():
    _, errors = validate_scheduled_events(
        [event(content=""), event(), event(at_sim_hour=-5)], make_config()
    )
    assert len(errors) == 2
    assert errors[0].startswith("event 1") and errors[1].startswith("event 3")


def test_duplicate_ids_are_rejected():
    _, errors = validate_scheduled_events(
        [event(id="a"), event(id="a", at_sim_hour=6)], make_config()
    )
    assert any("duplicate id 'a'" in e for e in errors)


def test_list_shape_and_size_limits():
    assert validate_scheduled_events("nope", make_config()) == ([], ["scheduled_events must be a list"])
    assert validate_scheduled_events({}, make_config())[1]
    _, errors = validate_scheduled_events(
        [event() for _ in range(MAX_SCHEDULED_EVENTS + 1)], make_config()
    )
    assert errors and str(MAX_SCHEDULED_EVENTS) in errors[0]
    ok, errors = validate_scheduled_events(
        [event(id=f"e{i}") for i in range(MAX_SCHEDULED_EVENTS)], make_config()
    )
    assert errors == [] and len(ok) == MAX_SCHEDULED_EVENTS


def test_an_empty_list_is_valid_and_clears_the_events():
    assert validate_scheduled_events([], make_config()) == ([], [])


def test_the_hour_limit_follows_the_simulation_length():
    assert validate_scheduled_events([event(at_sim_hour=47)], make_config(48))[1] == []
    assert validate_scheduled_events([event(at_sim_hour=48)], make_config(48))[1] != []
    assert validate_scheduled_events([event(at_sim_hour=100)], make_config(120))[1] == []


def test_validation_does_not_mutate_its_inputs():
    raw = [event(content="  spaced  ")]
    config = make_config()
    before = json.dumps([raw, config], sort_keys=True)
    validate_scheduled_events(raw, config)
    assert json.dumps([raw, config], sort_keys=True) == before


# --- PUT /api/simulation/<id>/scheduled-events --------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    manager = SimulationManager()

    def create(simulation_id="sim_x", status=SimulationStatus.READY, config=None):
        manager._save_simulation_state(
            SimulationState(simulation_id=simulation_id, project_id="p", graph_id="g", status=status)
        )
        if config is not False:
            path = tmp_path / simulation_id / "simulation_config.json"
            path.write_text(json.dumps(config or make_config()), encoding="utf-8")

    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    test_client = app.test_client()
    test_client.create = create
    test_client.dir = tmp_path
    return test_client


def put(client, simulation_id, body, **kwargs):
    return client.put(f"/api/simulation/{simulation_id}/scheduled-events", json=body, **kwargs)


def saved_config(client, simulation_id="sim_x"):
    return json.loads((client.dir / simulation_id / "simulation_config.json").read_text(encoding="utf-8"))


def test_put_replaces_the_list_and_leaves_the_rest_of_the_config_alone(client):
    client.create()
    before = saved_config(client)
    response = put(client, "sim_x", {"scheduled_events": [event(at_sim_hour=30), event(at_sim_hour=2)]})
    body = response.get_json()
    assert response.status_code == 200 and body["success"] is True
    assert [e["at_sim_hour"] for e in body["data"]["scheduled_events"]] == [2, 30]

    after = saved_config(client)
    assert after["event_config"]["scheduled_events"] == body["data"]["scheduled_events"]
    after["event_config"]["scheduled_events"] = []
    assert after == before  # nothing else changed
    assert [p.name for p in (client.dir / "sim_x").iterdir() if p.suffix == ".tmp"] == []

    second = put(client, "sim_x", {"scheduled_events": []})
    assert second.status_code == 200 and saved_config(client)["event_config"]["scheduled_events"] == []


def test_put_rejects_invalid_events_without_touching_the_file(client):
    client.create()
    put(client, "sim_x", {"scheduled_events": [event()]})
    saved = saved_config(client)

    response = put(client, "sim_x", {"scheduled_events": [event(at_sim_hour=500), event(content="")]})
    body = response.get_json()
    assert response.status_code == 400 and body["success"] is False
    assert len(body["errors"]) == 2 and "Invalid scheduled events" in body["error"]
    assert saved_config(client) == saved


@pytest.mark.parametrize("payload", [{}, {"scheduled_events": "x"}, {"scheduled_events": None}, {"scheduled_events": {"a": 1}}])
def test_put_requires_a_list(client, payload):
    client.create()
    response = put(client, "sim_x", payload)
    assert response.status_code == 400 and "must be a list" in response.get_json()["error"]


def test_put_with_a_non_json_body_is_a_400(client):
    client.create()
    response = client.put("/api/simulation/sim_x/scheduled-events", data="nope", content_type="text/plain")
    assert response.status_code == 400


@pytest.mark.parametrize(
    "status",
    [SimulationStatus.RUNNING, SimulationStatus.COMPLETED, SimulationStatus.STOPPED,
     SimulationStatus.PREPARING, SimulationStatus.CREATED, SimulationStatus.FAILED],
)
def test_put_is_only_allowed_while_the_simulation_is_ready(client, status):
    client.create(status=status)
    response = put(client, "sim_x", {"scheduled_events": [event()]})
    assert response.status_code == 409
    assert status.value in response.get_json()["error"]
    assert saved_config(client)["event_config"]["scheduled_events"] == []


def test_put_unknown_simulation_is_a_404(client):
    response = put(client, "sim_missing", {"scheduled_events": []})
    assert response.status_code == 404


def test_put_without_a_config_file_is_a_404(client):
    client.create(config=False)
    response = put(client, "sim_x", {"scheduled_events": []})
    assert response.status_code == 404


def test_put_message_follows_the_requested_language(client):
    client.create(status=SimulationStatus.RUNNING)
    response = put(client, "sim_x", {"scheduled_events": []}, headers={"Accept-Language": "zh"})
    assert response.status_code == 409 and "就绪" in response.get_json()["error"]


def test_saved_events_are_what_the_run_scripts_fire(client):
    import sim_behavior

    client.create()
    put(client, "sim_x", {"scheduled_events": [event(at_sim_hour=7, enabled=True),
                                               event(at_sim_hour=7, enabled=False, content="off")]})
    due = sim_behavior.due_scheduled_events(saved_config(client), 7)
    assert [e["content"] for e in due] == ["Breaking news"]
