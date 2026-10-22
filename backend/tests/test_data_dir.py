import os
import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]

PROBE = """
import json
from app.config import Config
from app.models.project import ProjectManager
print(json.dumps({
    "upload": Config.UPLOAD_FOLDER,
    "simulations": Config.OASIS_SIMULATION_DATA_DIR,
    "projects": ProjectManager.PROJECTS_DIR,
}))
"""


def _probe(env_overrides):
    env = {k: v for k, v in os.environ.items() if k != "MIROFISH_DATA_DIR"}
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=True,
    )
    import json
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_data_dir_defaults_to_backend_uploads():
    paths = _probe({})
    assert paths["upload"] == str((BACKEND / "uploads").resolve())
    assert paths["simulations"] == os.path.join(paths["upload"], "simulations")


def test_mirofish_data_dir_moves_all_storage(tmp_path):
    paths = _probe({"MIROFISH_DATA_DIR": str(tmp_path)})
    assert paths["upload"] == str(tmp_path)
    assert paths["simulations"] == str(tmp_path / "simulations")
    assert paths["projects"] == str(tmp_path / "projects")


def test_no_module_hardcodes_the_uploads_directory():
    offenders = []
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name == "config.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "uploads" in line and not line.lstrip().startswith("#"):
                offenders.append(f"{path.relative_to(BACKEND)}:{lineno}: {line.strip()}")
    assert not offenders, "derive storage paths from Config.UPLOAD_FOLDER:\n" + "\n".join(offenders)
