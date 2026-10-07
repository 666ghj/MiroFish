"""issue #489: posts/comments 接口把请求参数直接拼进 SQLite 路径。

`_resolve_simulation_db_path` 必须拒绝一切能逃出
uploads/simulations/<id>/ 的 simulation_id / platform 组合，
否则 `..` 可以打开磁盘上任意 *_simulation.db 并把行当 JSON 返回。
"""

import os

import pytest

from app.api.simulation import _resolve_simulation_db_path


VALID_ID = "sim_0123456789ab"


def test_valid_id_and_platform_resolve_inside_simulations_dir():
    path = _resolve_simulation_db_path(VALID_ID, "reddit")
    normalized = os.path.normpath(path)
    assert normalized.endswith(
        os.path.join("uploads", "simulations", VALID_ID, "reddit_simulation.db")
    )


def test_valid_twitter_platform_resolves():
    path = _resolve_simulation_db_path(VALID_ID, "twitter")
    assert path.endswith("twitter_simulation.db")


@pytest.mark.parametrize("platform", ["../../evil", "..\\..\\evil", "postgres", "twitter_", "", None])
def test_platform_outside_allowlist_is_rejected(platform):
    with pytest.raises(ValueError):
        _resolve_simulation_db_path(VALID_ID, platform)


@pytest.mark.parametrize(
    "simulation_id",
    ["../../etc", "..\\..\\uploads", "sim_short", "sim_" + "a" * 13, "", None, "other_sim_0123456789ab"],
)
def test_simulation_id_outside_expected_format_is_rejected(simulation_id):
    with pytest.raises(ValueError):
        _resolve_simulation_db_path(simulation_id, "reddit")


def test_traversal_via_combined_inputs_is_rejected():
    with pytest.raises(ValueError):
        _resolve_simulation_db_path("../..", "../../uploads/other/reddit")
