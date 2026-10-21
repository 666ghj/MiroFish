"""Model JSON event shapes must remain usable by config assignment and display."""
import json

from flask import Flask
import pytest

from app.api import simulation as simulation_api
from app.config import Config
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.simulation_manager import SimulationManager
from app.services.zep_entity_reader import EntityNode


@pytest.mark.parametrize("initial_posts", [
    None,
    {"content": "not a list"},
    [None, "not a post object", 7, {}, {"content": None}, {"content": " "},
     {"content": "A real initial post", "poster_type": "Person"}],
    [{"content": "A real initial post", "poster_type": None}],
    [{"content": "A real initial post", "poster_type": "Person"}],
])
@pytest.mark.parametrize("hot_topics", [None, [None, "public policy", 12], ["public policy"]])
def test_model_event_shapes_survive_generation_assignment_and_config_api(
    monkeypatch, tmp_path, initial_posts, hot_topics
):
    generator = object.__new__(SimulationConfigGenerator)
    generator.model_name, generator.base_url = "offline-fixture", ""
    responses = iter([
        {"total_simulation_hours": 72, "minutes_per_round": 60},
        {"initial_posts": initial_posts, "hot_topics": hot_topics},
        {"agent_configs": [{"agent_id": 0, "activity_level": 0.5}]},
    ])
    # Substitute only the model response boundary; all generation, parsing,
    # assignment, serialization, persistence and endpoint logic are production.
    monkeypatch.setattr(generator, "_call_llm_with_retry", lambda *_args: next(responses))
    entity = EntityNode("person", "Alice", ["Person"], "A participant", {})
    params = generator.generate_config("sim_event", "project", "graph", "Study public policy", "Evidence", [entity])
    payload = json.loads(params.to_json())
    posts = payload["event_config"]["initial_posts"]
    expected_post = isinstance(initial_posts, list) and any(
        isinstance(post, dict) and post.get("content") == "A real initial post" for post in initial_posts
    )
    assert len(posts) == (1 if expected_post else 0)
    if posts:
        assert posts[0]["content"] == "A real initial post"
        assert posts[0]["poster_agent_id"] == 0
    assert payload["event_config"]["hot_topics"] == ([] if hot_topics is None else ["public policy"])

    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    folder = tmp_path / "sim_event"
    folder.mkdir()
    (folder / "simulation_config.json").write_text(params.to_json(), encoding="utf-8")
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    response = app.test_client().get("/simulation/sim_event/config/realtime")
    assert response.status_code == 200
    assert response.get_json()["data"]["summary"]["initial_posts_count"] == len(posts)
