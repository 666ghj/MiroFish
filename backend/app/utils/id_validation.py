"""
Centralized identifier and filesystem-path validation.

Every identifier that originates from a client request (project_id, simulation_id,
report_id, graph_id, platform name, ...) must be validated against a strict format
before it is used to build a filesystem path. In addition, every path built from
such an identifier must be resolved and checked to still live inside its expected
base directory (defense in depth against traversal via unexpected OS/filesystem
behavior, symlinks, etc.).

Do not bypass this module by concatenating identifiers into paths directly.
"""

import os
import re

# Production IDs are generated as e.g. "proj_" + 12 hex chars (see
# models/project.py, services/simulation_manager.py, api/report.py,
# services/graph_builder.py), but internal callers and the test suite also use
# looser opaque identifiers (e.g. "sim-1", "sim_failed"). The security-relevant
# property is not the exact shape of the ID, it's that it can never contain a
# path separator, a "." segment, a null byte, or non-ASCII/unexpected characters
# that could influence path resolution. So validation is a generic safe-token
# check (letters, digits, underscore, hyphen only) rather than a per-type regex
# tied to the current ID-generation scheme.
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')

_ALLOWED_PLATFORMS = ('twitter', 'reddit')


class InvalidIdentifierError(ValueError):
    """Raised when a client-supplied identifier does not match the expected format."""


class PathContainmentError(ValueError):
    """Raised when a resolved path would escape its expected base directory."""


def _validate(value, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidIdentifierError(f"Invalid {label}: value is missing or malformed")
    if not _SAFE_ID_RE.fullmatch(value):
        raise InvalidIdentifierError(f"Invalid {label}: '{value}' does not match the expected format")
    return value


def validate_project_id(project_id) -> str:
    return _validate(project_id, "project_id")


def validate_simulation_id(simulation_id) -> str:
    return _validate(simulation_id, "simulation_id")


def validate_report_id(report_id) -> str:
    return _validate(report_id, "report_id")


def validate_graph_id(graph_id) -> str:
    return _validate(graph_id, "graph_id")


def validate_task_id(task_id) -> str:
    return _validate(task_id, "task_id")


def validate_ensemble_id(ensemble_id) -> str:
    return _validate(ensemble_id, "ensemble_id")


def validate_backtest_id(backtest_id) -> str:
    return _validate(backtest_id, "backtest_id")


def validate_platform_name(platform) -> str:
    if platform not in _ALLOWED_PLATFORMS:
        raise InvalidIdentifierError(
            f"Invalid platform: '{platform}' is not one of {_ALLOWED_PLATFORMS}"
        )
    return platform


def safe_join(base_dir: str, *parts: str) -> str:
    """
    Join `parts` onto `base_dir` and verify the resolved result is still contained
    within `base_dir`. Use this for every path built from a validated identifier
    as a second line of defense (validated identifiers alone should already be
    traversal-safe, but this guards against future call sites that forget to
    validate, and against unexpected path parts such as embedded separators).
    """
    base_real = os.path.realpath(base_dir)
    candidate = os.path.join(base_dir, *parts)
    candidate_real = os.path.realpath(candidate)
    if candidate_real != base_real and not candidate_real.startswith(base_real + os.sep):
        raise PathContainmentError(
            f"Resolved path '{candidate_real}' escapes base directory '{base_real}'"
        )
    return candidate
