import json

import pytest

from app.api.simulation import _check_simulation_prepared
from app.config import Config


def _write_prepared_simulation(
    root,
    *,
    enable_twitter=None,
    enable_reddit=None,
    profile_files=(),
):
    simulation_id = "sim_prepared"
    simulation_dir = root / simulation_id
    simulation_dir.mkdir(parents=True)

    state = {
        "status": "ready",
        "config_generated": True,
        "profiles_count": 1,
    }
    if enable_twitter is not None:
        state["enable_twitter"] = enable_twitter
    if enable_reddit is not None:
        state["enable_reddit"] = enable_reddit

    (simulation_dir / "state.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    (simulation_dir / "simulation_config.json").write_text(
        "{}",
        encoding="utf-8",
    )

    for filename in profile_files:
        content = "[{}]" if filename.endswith(".json") else "user_id,user_name\n0,alice\n"
        (simulation_dir / filename).write_text(content, encoding="utf-8")

    return simulation_id


def test_twitter_only_simulation_does_not_require_reddit_profiles(tmp_path, monkeypatch):
    simulation_id = _write_prepared_simulation(
        tmp_path,
        enable_twitter=True,
        enable_reddit=False,
        profile_files=("twitter_profiles.csv",),
    )
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))

    is_prepared, info = _check_simulation_prepared(simulation_id)

    assert is_prepared is True
    assert info["profiles_count"] == 1
    assert "twitter_profiles.csv" in info["existing_files"]
    assert "reddit_profiles.json" not in info["existing_files"]


def test_reddit_only_simulation_does_not_require_twitter_profiles(tmp_path, monkeypatch):
    simulation_id = _write_prepared_simulation(
        tmp_path,
        enable_twitter=False,
        enable_reddit=True,
        profile_files=("reddit_profiles.json",),
    )
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))

    is_prepared, info = _check_simulation_prepared(simulation_id)

    assert is_prepared is True
    assert info["profiles_count"] == 1
    assert "reddit_profiles.json" in info["existing_files"]
    assert "twitter_profiles.csv" not in info["existing_files"]


@pytest.mark.parametrize(
    ("enable_twitter", "enable_reddit", "missing_profile"),
    [
        (True, False, "twitter_profiles.csv"),
        (False, True, "reddit_profiles.json"),
    ],
)
def test_enabled_platform_profile_is_still_required(
    tmp_path,
    monkeypatch,
    enable_twitter,
    enable_reddit,
    missing_profile,
):
    simulation_id = _write_prepared_simulation(
        tmp_path,
        enable_twitter=enable_twitter,
        enable_reddit=enable_reddit,
    )
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))

    is_prepared, info = _check_simulation_prepared(simulation_id)

    assert is_prepared is False
    assert info["missing_files"] == [missing_profile]


def test_legacy_state_without_platform_flags_requires_both_profiles(tmp_path, monkeypatch):
    simulation_id = _write_prepared_simulation(
        tmp_path,
        profile_files=("reddit_profiles.json",),
    )
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))

    is_prepared, info = _check_simulation_prepared(simulation_id)

    assert is_prepared is False
    assert info["missing_files"] == ["twitter_profiles.csv"]
