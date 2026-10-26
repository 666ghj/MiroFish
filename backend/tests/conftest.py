"""Shared pytest setup.

* Makes the run-script helper modules (``backend/scripts``) importable.
  ``sim_behavior`` and friends deliberately live next to the run scripts, which
  are executed as plain files and are not part of the ``app`` package.
* Redirects every data directory to a temporary location for the whole test
  session. Several services create directories as a side effect of looking a
  simulation up, and ensemble runner threads can outlive the test that started
  them; without this, test runs leave stray files in the real ``uploads``
  folder. Tests that need their own directory still patch these attributes
  themselves; undoing such a patch restores the session directory, never the
  real one.
"""

import os
import sys

import pytest

_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.append(_SCRIPTS_DIR)


@pytest.fixture(scope="session", autouse=True)
def _isolate_data_directories(tmp_path_factory):
    from app.config import Config
    from app.models.project import ProjectManager
    from app.services.ensemble_runner import EnsembleManager
    from app.services.report_agent import ReportManager
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner

    root = tmp_path_factory.mktemp("mirofish_data")
    patch = pytest.MonkeyPatch()
    patch.setattr(Config, "UPLOAD_FOLDER", str(root))
    patch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(root / "simulations"))
    patch.setattr(ProjectManager, "PROJECTS_DIR", str(root / "projects"))
    patch.setattr(ReportManager, "REPORTS_DIR", str(root / "reports"))
    patch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(root / "simulations"))
    patch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root / "simulations"))
    patch.setattr(EnsembleManager, "ENSEMBLE_DATA_DIR", str(root / "ensembles"))
    yield root
    patch.undo()
