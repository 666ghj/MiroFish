"""The actual OASIS CSV must retain profile-card text on both read paths."""
from flask import Flask
import pytest

from app.api import simulation as simulation_api
from app.config import Config
from app.services.oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator
from app.services.simulation_manager import SimulationManager


@pytest.mark.parametrize("realtime", [False, True])
def test_saved_twitter_profile_keeps_bio_and_persona_visible(monkeypatch, tmp_path, realtime):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    state = SimulationManager().create_simulation("project", "graph", enable_twitter=True, enable_reddit=False)
    profile = OasisAgentProfile(
        user_id=0, user_name="alice", name="Alice", bio="A researcher.",
        persona="Studies long-term public opinion.",
    )
    path = tmp_path / state.simulation_id / "twitter_profiles.csv"
    generator = object.__new__(OasisProfileGenerator)
    generator.save_profiles([profile], str(path), platform="twitter")
    original_csv = path.read_bytes()
    app = Flask(__name__)
    app.register_blueprint(simulation_api.simulation_bp, url_prefix="/simulation")
    endpoint = "profiles/realtime" if realtime else "profiles"
    response = app.test_client().get(f"/simulation/{state.simulation_id}/{endpoint}")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["platform"] == "twitter"
    result = data["profiles"][0]
    assert result["bio"] == profile.bio
    assert profile.persona in result["persona"]
    assert result["description"] == profile.bio
    assert profile.persona in result["user_char"]
    assert path.read_bytes() == original_csv
