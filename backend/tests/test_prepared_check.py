import json
import os

import pytest

from app.api import simulation as simulation_api
from app.config import Config


def make_simulation(root, simulation_id, status, config_generated=True):
    folder = os.path.join(root, simulation_id)
    os.makedirs(folder)
    for name in ("simulation_config.json", "reddit_profiles.json", "twitter_profiles.csv"):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write("[]" if name.endswith(".json") else "")
    with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as handle:
        json.dump({"simulation_id": simulation_id, "status": status, "config_generated": config_generated}, handle)
    return folder


@pytest.mark.parametrize("status", ["ready", "preparing", "running", "stopping", "paused", "stopped", "completed", "failed"])
def test_a_simulation_that_was_prepared_is_never_prepared_again_whatever_its_run_status(tmp_path, monkeypatch, status):
    # "stopping" is what state.json keeps when the run's process dies while it is being stopped. It used to be missing
    # from the list, so opening such a simulation regenerated every profile and the config over the run's own.
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    make_simulation(str(tmp_path), "sim_a", status)
    prepared, info = simulation_api._check_simulation_prepared("sim_a")
    assert prepared is True, info


@pytest.mark.parametrize("status,config_generated", [("created", False), ("preparing", False), ("stopping", False)])
def test_a_simulation_whose_preparation_never_finished_is_still_prepared_from_scratch(tmp_path, monkeypatch, status, config_generated):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    make_simulation(str(tmp_path), "sim_b", status, config_generated)
    prepared, _info = simulation_api._check_simulation_prepared("sim_b")
    assert prepared is False
