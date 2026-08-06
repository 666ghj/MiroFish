#!/usr/bin/env python3
"""Generate and maintain a repository-owned Star History chart.

The one-time ``backfill`` command queries only opaque edge cursors and
``starredAt`` timestamps. Scheduled updates receive one aggregate count from the
standalone fetch-only helper, then record and render without credentials. No
stargazer identity is persisted.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


REPOSITORY = "666ghj/MiroFish"
REPOSITORY_OWNER, REPOSITORY_NAME = REPOSITORY.split("/", 1)
INTERVAL_DAYS = 13
STATE_RELATIVE = Path(".github/star-history/history.json")
LIGHT_SVG_RELATIVE = Path("static/image/star-history-light.svg")
DARK_SVG_RELATIVE = Path("static/image/star-history-dark.svg")
OUTPUT_RELATIVES = (STATE_RELATIVE, LIGHT_SVG_RELATIVE, DARK_SVG_RELATIVE)
MAX_STATE_BYTES = 5_000_000
MAX_COUNT_FILE_BYTES = 64
MAX_STAR_COUNT = (1 << 63) - 1
PAGE_SIZE = 100
RATE_LIMIT_RESERVE = 20
UTC = timezone.utc

# A reviewed snapshot of the repository owner's public GitHub avatar. The
# bootstrapper injects the bounded PNG/JPEG bytes and their digest into this
# template so scheduled rendering remains offline and the SVG self-contained.
OWNER_AVATAR_BASE64 = "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"
OWNER_AVATAR_MEDIA_TYPE = "image/jpeg"
OWNER_AVATAR_DATA_URI = (
    f"data:{OWNER_AVATAR_MEDIA_TYPE};base64,{OWNER_AVATAR_BASE64}"
)
OWNER_AVATAR_SHA256 = "0b469b43ffc2e2dad3ea63970b3483f38c0199162ff46819cfa19a0237bb9072"
OWNER_AVATAR_DIMENSIONS = (64, 64)
MAX_INLINE_AVATAR_BYTES = 64_000

# Star History's reviewed 64x64 RGBA watermark icon, embedded exactly as used
# by the upstream MIT-licensed renderer (Copyright 2025 Star History). The
# corresponding license notice is retained in THIRD_PARTY_NOTICES.md.
WATERMARK_LOGO_BASE64 = (
    "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"
    "MjY6MTQtMDU6MDDygtFyAAAAAElFTkSuQmCC"
)
WATERMARK_LOGO_DATA_URI = f"data:image/png;base64,{WATERMARK_LOGO_BASE64}"
WATERMARK_LOGO_SHA256 = "02d30436a381b85e3e8beda75b06bd40ab98b14a419f293688ef32931b639bad"
WATERMARK_LOGO_DIMENSIONS = (64, 64)
MAX_INLINE_WATERMARK_BYTES = 8_192

STATE_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GRAPHQL_QUERY = """\
query StarTimes($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    stargazers(
      first: 100
      after: $after
      orderBy: {field: STARRED_AT, direction: DESC}
    ) {
      totalCount
      edges { cursor starredAt }
      pageInfo { hasNextPage endCursor }
    }
  }
  rateLimit { cost remaining resetAt }
}
"""


class StarHistoryError(RuntimeError):
    """A safe, user-facing error that never includes secrets."""


@dataclass(frozen=True)
class StargazerEdge:
    cursor: str
    starred_at: datetime


@dataclass(frozen=True)
class StargazerPage:
    total_count: int
    edges: tuple[StargazerEdge, ...]
    has_next_page: bool
    end_cursor: str | None
    rate_remaining: int


@dataclass(frozen=True)
class Result:
    changed: bool
    due: bool | None
    message: str


class Clock(Protocol):
    def now(self) -> datetime: ...


class GitHubGateway(Protocol):
    def fetch_stargazer_page(self, after: str | None) -> StargazerPage: ...


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(microsecond=0)


class SubprocessCommandRunner:
    def run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(arguments),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
            )
        except FileNotFoundError as exc:
            raise StarHistoryError("GitHub CLI (gh) is required for backfill") from exc
        except subprocess.TimeoutExpired as exc:
            raise StarHistoryError("GitHub GraphQL request timed out") from exc


class GhGraphQLGateway:
    """Production adapter for the one-time, maintainer-authorized backfill."""

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def fetch_stargazer_page(self, after: str | None) -> StargazerPage:
        arguments = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={GRAPHQL_QUERY}",
            "-f",
            f"owner={REPOSITORY_OWNER}",
            "-f",
            f"name={REPOSITORY_NAME}",
        ]
        if after is not None:
            if not after or "\n" in after or "\r" in after:
                raise StarHistoryError("GitHub returned an invalid pagination cursor")
            arguments.extend(("-f", f"after={after}"))

        completed = self._runner.run(arguments)
        if completed.returncode != 0:
            raise StarHistoryError(
                f"GitHub GraphQL request failed (exit {completed.returncode})"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise StarHistoryError("GitHub GraphQL returned malformed JSON") from exc

        if not isinstance(payload, dict) or payload.get("errors"):
            raise StarHistoryError("GitHub GraphQL rejected the stargazer request")
        try:
            data = payload["data"]
            repository = data["repository"]
            stargazers = repository["stargazers"]
            rate_limit = data["rateLimit"]
            raw_edges = stargazers["edges"]
            page_info = stargazers["pageInfo"]
        except (KeyError, TypeError) as exc:
            raise StarHistoryError("GitHub GraphQL response had an unexpected shape") from exc

        if not all(
            isinstance(value, dict)
            for value in (data, repository, stargazers, rate_limit, page_info)
        ):
            raise StarHistoryError("GitHub GraphQL response had an unexpected shape")

        total_count = _strict_non_negative_int(
            stargazers.get("totalCount"), "GraphQL totalCount"
        )
        rate_remaining = _strict_non_negative_int(
            rate_limit.get("remaining"), "GraphQL rate remaining"
        )
        if not isinstance(raw_edges, list):
            raise StarHistoryError("GitHub GraphQL edges were not a list")

        edges: list[StargazerEdge] = []
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                raise StarHistoryError("GitHub GraphQL returned an invalid edge")
            cursor = raw_edge.get("cursor")
            starred_at = raw_edge.get("starredAt")
            if not isinstance(cursor, str) or not cursor:
                raise StarHistoryError("GitHub GraphQL returned an invalid edge cursor")
            if not isinstance(starred_at, str):
                raise StarHistoryError("GitHub GraphQL returned an invalid star timestamp")
            edges.append(StargazerEdge(cursor, _parse_github_timestamp(starred_at)))

        has_next_page = page_info.get("hasNextPage")
        end_cursor = page_info.get("endCursor")
        if type(has_next_page) is not bool:
            raise StarHistoryError("GitHub GraphQL returned invalid page information")
        if end_cursor is not None and not isinstance(end_cursor, str):
            raise StarHistoryError("GitHub GraphQL returned an invalid page cursor")
        if has_next_page and not end_cursor:
            raise StarHistoryError("GitHub GraphQL omitted the next page cursor")

        return StargazerPage(
            total_count=total_count,
            edges=tuple(edges),
            has_next_page=has_next_page,
            end_cursor=end_cursor,
            rate_remaining=rate_remaining,
        )


def _strict_non_negative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise StarHistoryError(f"{label} must be a non-negative integer")
    return value


def _parse_github_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StarHistoryError("GitHub returned an invalid star timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise StarHistoryError("GitHub star timestamp was not UTC")
    return parsed.astimezone(UTC)


def _parse_state_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not STATE_TIMESTAMP_RE.fullmatch(value):
        raise StarHistoryError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise StarHistoryError(f"{label} is not a valid UTC timestamp") from exc
    return parsed


def _format_state_timestamp(value: datetime) -> str:
    normalized = _normalize_now(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise StarHistoryError("clock must return a UTC datetime")
    return value.astimezone(UTC).replace(microsecond=0)


def _expect_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise StarHistoryError(f"{label} contains missing or unknown fields")


def validate_state(state: Any) -> None:
    if not isinstance(state, dict):
        raise StarHistoryError("history state must be a JSON object")
    _expect_keys(
        state,
        {
            "schema_version",
            "repository",
            "timezone",
            "ongoing_interval_days",
            "reconstruction",
            "snapshots",
        },
        "history state",
    )
    if state["schema_version"] != 1 or type(state["schema_version"]) is not int:
        raise StarHistoryError("unsupported history schema_version")
    if state["repository"] != REPOSITORY:
        raise StarHistoryError("history repository does not match configured repository")
    if state["timezone"] != "UTC":
        raise StarHistoryError("history timezone must be UTC")
    if (
        state["ongoing_interval_days"] != INTERVAL_DAYS
        or type(state["ongoing_interval_days"]) is not int
    ):
        raise StarHistoryError(
            f"history interval must be exactly {INTERVAL_DAYS} days"
        )

    reconstruction = state["reconstruction"]
    if not isinstance(reconstruction, dict):
        raise StarHistoryError("reconstruction must be an object")
    _expect_keys(
        reconstruction,
        {"method", "generated_at", "daily"},
        "reconstruction",
    )
    reconstruction_method = reconstruction["method"]
    if reconstruction_method not in {
        "current_stargazers_starred_at",
        "aggregate_snapshot_only",
    }:
        raise StarHistoryError("unsupported reconstruction method")
    generated_at = _parse_state_timestamp(
        reconstruction["generated_at"], "reconstruction.generated_at"
    )
    daily = reconstruction["daily"]
    if not isinstance(daily, list):
        raise StarHistoryError("reconstruction.daily must be a list")
    if reconstruction_method == "aggregate_snapshot_only" and daily:
        raise StarHistoryError("aggregate-only history cannot contain reconstructed dates")

    previous_day: date | None = None
    previous_stars = 0
    for index, raw_point in enumerate(daily):
        if not isinstance(raw_point, dict):
            raise StarHistoryError("reconstruction point must be an object")
        _expect_keys(raw_point, {"date", "stars"}, "reconstruction point")
        raw_date = raw_point["date"]
        if not isinstance(raw_date, str):
            raise StarHistoryError("reconstruction date must be a string")
        try:
            point_day = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise StarHistoryError("reconstruction date is invalid") from exc
        if point_day.isoformat() != raw_date:
            raise StarHistoryError("reconstruction date is not canonical")
        stars = _strict_non_negative_int(raw_point["stars"], "reconstruction stars")
        if index == 0 and stars <= 0:
            raise StarHistoryError("first reconstruction point must have stars")
        if previous_day is not None and point_day <= previous_day:
            raise StarHistoryError("reconstruction dates must be strictly increasing")
        if index > 0 and stars <= previous_stars:
            raise StarHistoryError("reconstruction stars must be strictly increasing")
        if point_day >= generated_at.date():
            raise StarHistoryError("reconstruction must contain only completed UTC dates")
        previous_day = point_day
        previous_stars = stars

    snapshots = state["snapshots"]
    if not isinstance(snapshots, list):
        raise StarHistoryError("snapshots must be a list")
    previous_snapshot: datetime | None = None
    first_snapshot: datetime | None = None
    for raw_snapshot in snapshots:
        if not isinstance(raw_snapshot, dict):
            raise StarHistoryError("snapshot must be an object")
        _expect_keys(raw_snapshot, {"at", "stars"}, "snapshot")
        snapshot_at = _parse_state_timestamp(raw_snapshot["at"], "snapshot.at")
        _strict_non_negative_int(raw_snapshot["stars"], "snapshot stars")
        if previous_snapshot is not None and snapshot_at <= previous_snapshot:
            raise StarHistoryError("snapshot timestamps must be strictly increasing")
        if first_snapshot is None:
            first_snapshot = snapshot_at
        previous_snapshot = snapshot_at

    if first_snapshot is not None:
        if first_snapshot < generated_at:
            raise StarHistoryError("first snapshot cannot predate reconstruction")
        if previous_day is not None and previous_day >= first_snapshot.date():
            raise StarHistoryError("reconstruction dates must predate snapshots")


def canonical_state_bytes(state: Mapping[str, Any]) -> bytes:
    validate_state(state)
    return (
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_workspace(workspace: Path) -> Path:
    try:
        root = workspace.resolve(strict=True)
    except OSError as exc:
        raise StarHistoryError("workspace does not exist") from exc
    if not root.is_dir():
        raise StarHistoryError("workspace is not a directory")
    return root


def _safe_target(workspace: Path, relative: Path, create_parent: bool) -> Path:
    root = _safe_workspace(workspace)
    if relative.is_absolute() or ".." in relative.parts:
        raise StarHistoryError("output path escaped the workspace")

    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise StarHistoryError("output directory cannot be a symbolic link")
    target = root / relative
    if target.is_symlink():
        raise StarHistoryError("output file cannot be a symbolic link")
    if create_parent:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StarHistoryError("could not create output directory") from exc
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise StarHistoryError("output directory cannot be a symbolic link")
        if target.is_symlink():
            raise StarHistoryError("output file cannot be a symbolic link")
    try:
        resolved_parent = target.parent.resolve(strict=False)
        resolved_parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise StarHistoryError("output path escaped the workspace") from exc
    return resolved_parent / target.name


def _read_limited(path: Path, limit: int, label: str) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except FileNotFoundError as exc:
        raise StarHistoryError(f"{label} is missing") from exc
    except OSError as exc:
        raise StarHistoryError(f"could not read {label}") from exc
    if len(payload) > limit:
        raise StarHistoryError(f"{label} exceeded the size limit")
    return payload


def load_star_count_file(path: Path) -> int:
    """Read a tiny, symlink-safe decimal count produced by the fetch-only step."""

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StarHistoryError("Star count file is missing or unsafe") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise StarHistoryError("Star count file is not a regular file")
        payload = os.read(descriptor, MAX_COUNT_FILE_BYTES + 1)
    except OSError as exc:
        raise StarHistoryError("could not read Star count file") from exc
    finally:
        os.close(descriptor)

    if len(payload) > MAX_COUNT_FILE_BYTES:
        raise StarHistoryError("Star count file exceeded the size limit")
    if not re.fullmatch(rb"(?:0|[1-9][0-9]*)\n?", payload):
        raise StarHistoryError("Star count file must contain one decimal integer")
    count = int(payload)
    if count > MAX_STAR_COUNT:
        raise StarHistoryError("Star count exceeded the supported range")
    return count


def load_state(workspace: Path, require_canonical: bool = True) -> dict[str, Any]:
    state_path = _safe_target(workspace, STATE_RELATIVE, create_parent=False)
    payload = _read_limited(state_path, MAX_STATE_BYTES, "history state")
    try:
        state = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarHistoryError("history state is not valid UTF-8 JSON") from exc
    validate_state(state)
    if require_canonical and canonical_state_bytes(state) != payload:
        raise StarHistoryError("history state is not canonically formatted")
    return state


def _snapshot_due(state: Mapping[str, Any], now: datetime) -> bool:
    normalized = _normalize_now(now)
    generated_at = _parse_state_timestamp(
        state["reconstruction"]["generated_at"], "reconstruction.generated_at"
    )
    if normalized < generated_at:
        raise StarHistoryError("clock is earlier than the reconstruction timestamp")
    snapshots = state["snapshots"]
    if not snapshots:
        return True
    latest = _parse_state_timestamp(snapshots[-1]["at"], "snapshot.at")
    if normalized < latest:
        raise StarHistoryError("clock is earlier than the latest snapshot")
    return normalized - latest >= timedelta(days=INTERVAL_DAYS)


def _build_backfill_state(github: GitHubGateway, now: datetime) -> dict[str, Any]:
    normalized_now = _normalize_now(now)
    after: str | None = None
    seen_page_cursors: set[str] = set()
    seen_edge_cursors: set[str] = set()
    daily_increments: Counter[date] = Counter()
    initial_total: int | None = None
    page_number = 0

    while True:
        page = github.fetch_stargazer_page(after)
        page_number += 1
        if initial_total is None:
            initial_total = page.total_count
            pages_required = math.ceil(initial_total / PAGE_SIZE)
            remaining_requests = max(0, pages_required - 1)
            if page.rate_remaining < remaining_requests + RATE_LIMIT_RESERVE:
                raise StarHistoryError("insufficient GitHub GraphQL rate limit for backfill")
        for edge in page.edges:
            if edge.cursor in seen_edge_cursors:
                raise StarHistoryError("GitHub GraphQL repeated an edge cursor")
            seen_edge_cursors.add(edge.cursor)
            if edge.starred_at.date() < normalized_now.date():
                daily_increments[edge.starred_at.date()] += 1

        if page.end_cursor is not None:
            if page.end_cursor in seen_page_cursors:
                raise StarHistoryError("GitHub GraphQL repeated a page cursor")
            seen_page_cursors.add(page.end_cursor)
        if not page.has_next_page:
            break
        if page.end_cursor is None:
            raise StarHistoryError("GitHub GraphQL omitted the next page cursor")
        after = page.end_cursor
        if page_number > 10_000:
            raise StarHistoryError("GitHub GraphQL exceeded the page safety limit")

    if initial_total is None:
        raise StarHistoryError("GitHub GraphQL returned no pages")
    if len(seen_edge_cursors) != initial_total:
        raise StarHistoryError("stargazer list changed or was incomplete during backfill")

    running = 0
    daily: list[dict[str, Any]] = []
    for point_day in sorted(daily_increments):
        running += daily_increments[point_day]
        daily.append({"date": point_day.isoformat(), "stars": running})

    state: dict[str, Any] = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "timezone": "UTC",
        "ongoing_interval_days": INTERVAL_DAYS,
        "reconstruction": {
            "method": "current_stargazers_starred_at",
            "generated_at": _format_state_timestamp(normalized_now),
            "daily": daily,
        },
        "snapshots": [],
    }
    validate_state(state)
    return state


def _build_initial_state(now: datetime, stars: int) -> dict[str, Any]:
    """Start an honest history when timestamp backfill is unavailable."""

    normalized_now = _normalize_now(now)
    checked_stars = _strict_non_negative_int(stars, "stargazers_count")
    if checked_stars > MAX_STAR_COUNT:
        raise StarHistoryError("Star count exceeded the supported range")
    timestamp = _format_state_timestamp(normalized_now)
    state: dict[str, Any] = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "timezone": "UTC",
        "ongoing_interval_days": INTERVAL_DAYS,
        "reconstruction": {
            "method": "aggregate_snapshot_only",
            "generated_at": timestamp,
            "daily": [],
        },
        "snapshots": [{"at": timestamp, "stars": checked_stars}],
    }
    validate_state(state)
    return state


def _updated_with_snapshot(
    state: Mapping[str, Any], now: datetime, stars: int
) -> dict[str, Any]:
    normalized_now = _normalize_now(now)
    _strict_non_negative_int(stars, "stargazers_count")
    updated = json.loads(json.dumps(state))
    snapshots: list[dict[str, Any]] = updated["snapshots"]
    new_snapshot = {
        "at": _format_state_timestamp(normalized_now),
        "stars": stars,
    }
    if snapshots:
        latest_at = _parse_state_timestamp(snapshots[-1]["at"], "snapshot.at")
        if normalized_now < latest_at:
            raise StarHistoryError("clock is earlier than the latest snapshot")
        if normalized_now.date() == latest_at.date():
            if snapshots[-1]["stars"] == stars:
                return updated
            snapshots[-1] = new_snapshot
        else:
            snapshots.append(new_snapshot)
    else:
        snapshots.append(new_snapshot)
    validate_state(updated)
    return updated


@dataclass(frozen=True)
class ChartPoint:
    at: datetime
    stars: int
    source: str


def _chart_points(state: Mapping[str, Any]) -> list[ChartPoint]:
    points: list[ChartPoint] = []
    for item in state["reconstruction"]["daily"]:
        point_day = date.fromisoformat(item["date"])
        end_of_day = datetime.combine(point_day + timedelta(days=1), time.min, UTC)
        points.append(ChartPoint(end_of_day, item["stars"], "reconstruction"))
    for item in state["snapshots"]:
        points.append(
            ChartPoint(
                _parse_state_timestamp(item["at"], "snapshot.at"),
                item["stars"],
                "snapshot",
            )
        )
    points.sort(key=lambda point: point.at)
    return points


def _nice_y_axis(maximum: int) -> tuple[int, int]:
    if maximum <= 0:
        return 1, 5
    raw = maximum / 5
    exponent = math.floor(math.log10(raw)) if raw > 0 else 0
    base = 10**exponent
    fraction = raw / base
    if fraction <= 1:
        multiplier = 1.0
    elif fraction <= 2:
        multiplier = 2.0
    elif fraction <= 2.5:
        multiplier = 2.5
    elif fraction <= 5:
        multiplier = 5.0
    else:
        multiplier = 10.0
    step = max(1, int(multiplier * base))
    top = max(step, math.ceil(maximum / step) * step)
    return step, top


def _format_number(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m".replace(".0m", "m")
    if value >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    return str(value)


def _format_float(value: float) -> str:
    rendered = f"{value:.2f}".rstrip("0").rstrip(".")
    return rendered if rendered != "-0" else "0"


def _x_tick_label(value: datetime, span_days: float) -> str:
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    if span_days >= 365:
        return f"{months[value.month - 1]} {value.year}"
    if span_days >= 14:
        return f"{value.day:02d} {months[value.month - 1]}"
    return f"{weekdays[value.weekday()]} {value.day:02d}"


def _sign(value: float) -> int:
    if value < 0:
        return -1
    if value > 0:
        return 1
    return 0


def _monotone_x_path(points: Sequence[tuple[float, float]]) -> str:
    """Return a D3 curveMonotoneX-equivalent SVG path.

    D3 uses Steffen monotonic interpolation: interior tangents are limited so a
    smooth cubic cannot overshoot a monotonic run. This small implementation
    keeps the Star History curve shape without adding a JavaScript dependency.
    """

    normalized: list[tuple[float, float]] = []
    for x, y in points:
        if not math.isfinite(x) or not math.isfinite(y):
            raise StarHistoryError("chart coordinates must be finite")
        if normalized and x < normalized[-1][0]:
            raise StarHistoryError("chart coordinates must be ordered")
        if normalized and x == normalized[-1][0]:
            normalized[-1] = (x, y)
        else:
            normalized.append((x, y))

    if not normalized:
        return ""

    start_x, start_y = normalized[0]
    commands = [f"M{_format_float(start_x)},{_format_float(start_y)}"]
    if len(normalized) == 1:
        return "".join(commands)
    if len(normalized) == 2:
        end_x, end_y = normalized[1]
        commands.append(f"L{_format_float(end_x)},{_format_float(end_y)}")
        return "".join(commands)

    secants = [
        (normalized[index + 1][1] - normalized[index][1])
        / (normalized[index + 1][0] - normalized[index][0])
        for index in range(len(normalized) - 1)
    ]
    tangents = [0.0] * len(normalized)
    for index in range(1, len(normalized) - 1):
        h0 = normalized[index][0] - normalized[index - 1][0]
        h1 = normalized[index + 1][0] - normalized[index][0]
        slope0 = secants[index - 1]
        slope1 = secants[index]
        weighted = (slope0 * h1 + slope1 * h0) / (h0 + h1)
        tangents[index] = (_sign(slope0) + _sign(slope1)) * min(
            abs(slope0), abs(slope1), 0.5 * abs(weighted)
        )

    tangents[0] = (3 * secants[0] - tangents[1]) / 2
    tangents[-1] = (3 * secants[-1] - tangents[-2]) / 2

    for index in range(len(normalized) - 1):
        x0, y0 = normalized[index]
        x1, y1 = normalized[index + 1]
        third = (x1 - x0) / 3
        control1_x = x0 + third
        control1_y = y0 + third * tangents[index]
        control2_x = x1 - third
        control2_y = y1 - third * tangents[index + 1]
        commands.append(
            "C"
            f"{_format_float(control1_x)},{_format_float(control1_y)} "
            f"{_format_float(control2_x)},{_format_float(control2_y)} "
            f"{_format_float(x1)},{_format_float(y1)}"
        )
    return "".join(commands)


def render_svg(state: Mapping[str, Any], theme: str) -> bytes:
    """Render the dependency-free Star History-compatible SVG.

    The visual contract is a clean-room Python reimplementation of the MIT
    licensed ``star-history/star-history`` renderer behavior reviewed for this
    setup. No narayann7 JavaScript, npm package, or runtime dependency is
    vendored or executed here.
    """

    validate_state(state)
    if theme not in {"light", "dark"}:
        raise StarHistoryError("unsupported SVG theme")

    width = 800.0
    height = 533.333
    plot_left = 70.0
    plot_top = 60.0
    plot_width = 700.0
    plot_height = 423.333
    plot_bottom = plot_top + plot_height

    if theme == "light":
        background = "#ffffff"
        foreground = "#000000"
        legend_background = "#ffffff"
        line_color = "#dd4528"
    else:
        background = "#0d1117"
        foreground = "#ffffff"
        legend_background = "#0d1117"
        line_color = "#ff6b6b"

    points = _chart_points(state)
    generated_at = _parse_state_timestamp(
        state["reconstruction"]["generated_at"], "reconstruction.generated_at"
    )
    if points:
        x_min = points[0].at
        x_max = points[-1].at
        if x_max <= x_min:
            # A one-instant history still needs a visible time domain, but the
            # display padding must not become a fabricated zero-Star sample.
            try:
                x_min = points[0].at - timedelta(days=1)
            except OverflowError:
                pass
            try:
                x_max = points[-1].at + timedelta(days=1)
            except OverflowError:
                pass
        maximum = max(point.stars for point in points)
    else:
        try:
            x_min = generated_at - timedelta(days=1)
            x_max = generated_at
        except OverflowError:
            x_min = generated_at
            x_max = generated_at + timedelta(days=1)
        maximum = 0

    y_step, empty_y_top = _nice_y_axis(maximum)
    y_domain = maximum if maximum > 0 else empty_y_top
    x_span = max(1.0, (x_max - x_min).total_seconds())

    def x_coord(value: datetime) -> float:
        return plot_left + (
            (value - x_min).total_seconds() / x_span
        ) * plot_width

    def y_coord(value: int) -> float:
        return plot_bottom - (value / y_domain) * plot_height

    line_coordinates = [
        (x_coord(point.at), y_coord(point.stars)) for point in points
    ]
    if len({x for x, _ in line_coordinates}) == 1 and line_coordinates:
        # SVG does not paint a path containing only a move command. Draw a
        # small horizontal mark centred on the sole real sample instead.
        x, y = line_coordinates[-1]
        line_path = (
            f"M{_format_float(x - 4)},{_format_float(y)}"
            f"H{_format_float(x + 4)}"
        )
    else:
        line_path = _monotone_x_path(line_coordinates)

    y_ticks: list[str] = []
    y_tick_limit = maximum if maximum > 0 else 5
    for value in range(y_step, y_tick_limit + 1, y_step):
        y = y_coord(value)
        y_ticks.append(
            f'<line x1="69" y1="{_format_float(y)}" x2="70" '
            f'y2="{_format_float(y)}" stroke="{foreground}"/>'
        )
        y_ticks.append(
            f'<text x="63" y="{_format_float(y + 5)}" text-anchor="end" '
            f'font-size="16" fill="{foreground}">{_format_number(value)}</text>'
        )

    x_ticks: list[str] = []
    seen_x_labels: set[str] = set()
    span_days = (x_max - x_min).total_seconds() / 86400
    tick_count = min(6, max(2, math.ceil(span_days) + 1))
    for index in range(tick_count):
        ratio = index / (tick_count - 1)
        value = x_min + (x_max - x_min) * ratio
        label = _x_tick_label(value, span_days)
        if label in seen_x_labels:
            continue
        seen_x_labels.add(label)
        x = x_coord(value)
        if index == 0:
            anchor = "start"
        elif index == tick_count - 1:
            anchor = "end"
        else:
            anchor = "middle"
        x_ticks.append(
            f'<text x="{_format_float(x)}" y="{_format_float(plot_bottom + 18)}" '
            f'text-anchor="{anchor}" font-size="16" fill="{foreground}">'
            f'{html.escape(label)}</text>'
        )

    if state["reconstruction"]["method"] == "current_stargazers_starred_at":
        description = (
            f"Star history for {REPOSITORY}. Dates reconstructed from starredAt "
            "timestamps and later aggregate snapshots are rendered as one continuous "
            "series. No individual stargazer identity is stored."
        )
    else:
        description = (
            f"Star history for {REPOSITORY}. The series starts from the first locally "
            "recorded aggregate snapshot. No individual stargazer identity is stored."
        )
    font = "xkcd"
    legend_width = max(
        len(REPOSITORY) * 7.5 + 8 + 21,
        len(REPOSITORY) * 7 + 8 + 14 + 6,
    )
    svg = "".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 533.333" '
            f'width="800" height="533.333" preserveAspectRatio="xMidYMid meet" '
            f'role="img" aria-labelledby="title desc">',
            f'<title id="title">{html.escape(REPOSITORY_NAME)} Star History</title>',
            f'<desc id="desc">{html.escape(description)}</desc>',
            f'<rect width="800" height="533.333" fill="{background}"/>',
            '<defs>',
            '<filter id="xkcdify" filterUnits="userSpaceOnUse" x="-5" y="-5" '
            'width="100%" height="100%">',
            '<feTurbulence type="fractalNoise" baseFrequency="0.05" result="noise"/>',
            '<feDisplacementMap scale="5" xChannelSelector="R" yChannelSelector="G" '
            'in="SourceGraphic" in2="noise"/>',
            '</filter>',
            '<clipPath id="clip-circle-title">'
            '<circle r="11" cx="327" cy="23"/></clipPath>',
            '</defs>',
            f'<g font-family="{font}">',
            f'<image x="316" y="12" width="22" height="22" '
            f'href="{OWNER_AVATAR_DATA_URI}" clip-path="url(#clip-circle-title)"/>',
            f'<text x="400" y="30" text-anchor="middle" font-size="20" '
            f'font-weight="700" fill="{foreground}">Star History</text>',
            f'<path d="M{_format_float(plot_left)},{_format_float(plot_bottom)}'
            f'H{_format_float(plot_left + plot_width)}" fill="none" '
            f'stroke="{foreground}" stroke-width="3" filter="url(#xkcdify)"/>',
            f'<path d="M{_format_float(plot_left)},{_format_float(plot_bottom)}'
            f'V{_format_float(plot_top)}" fill="none" stroke="{foreground}" '
            f'stroke-width="3" filter="url(#xkcdify)"/>',
            *y_ticks,
            *x_ticks,
            (
                f'<path class="xkcd-chart-xyline" d="{line_path}" fill="none" '
                f'stroke="{line_color}" stroke-width="3" stroke-linecap="round" '
                f'stroke-linejoin="round" filter="url(#xkcdify)"/>'
                if line_path
                else ""
            ),
            f'<rect x="78" y="65" width="{_format_float(legend_width)}" height="32" rx="5" '
            f'fill="{legend_background}" fill-opacity="0.92" stroke="{foreground}" '
            f'stroke-width="2" filter="url(#xkcdify)"/>',
            f'<rect x="85" y="77" width="8" height="8" rx="2" fill="{line_color}" '
            f'filter="url(#xkcdify)"/>',
            f'<text x="99" y="85" font-size="15" fill="{foreground}">'
            f'{html.escape(REPOSITORY)}</text>',
            f'<text x="400" y="523.333" text-anchor="middle" font-size="17" '
            f'fill="{foreground}">Date</text>',
            f'<text x="22" y="272" text-anchor="middle" font-size="17" '
            f'fill="{foreground}" transform="rotate(-90 22 272)">GitHub Stars</text>',
            f'<image x="635" y="508.333" width="20" height="20" '
            f'href="{WATERMARK_LOGO_DATA_URI}"/>',
            '<text x="720" y="523.333" text-anchor="middle" font-size="16" '
            'fill="#666666">star-history.com</text>',
            "</g></svg>\n",
        ]
    )
    payload = svg.encode("utf-8")
    _validate_svg(payload)
    return payload


def _reviewed_avatar_dimensions(payload: bytes) -> tuple[int, int] | None:
    if OWNER_AVATAR_MEDIA_TYPE == "image/png":
        if (
            payload.startswith(b"\x89PNG\r\n\x1a\n")
            and len(payload) >= 33
            and payload[8:12] == (13).to_bytes(4, "big")
            and payload[12:16] == b"IHDR"
            and payload.endswith(b"IEND\xaeB`\x82")
        ):
            return (
                int.from_bytes(payload[16:20], "big"),
                int.from_bytes(payload[20:24], "big"),
            )
        return None
    if OWNER_AVATAR_MEDIA_TYPE == "image/jpeg":
        if not payload.startswith(b"\xff\xd8\xff") or not payload.endswith(b"\xff\xd9"):
            return None
        for marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            offset = payload.find(bytes((0xFF, marker)))
            if offset >= 0 and offset + 9 <= len(payload):
                return (
                    int.from_bytes(payload[offset + 7 : offset + 9], "big"),
                    int.from_bytes(payload[offset + 5 : offset + 7], "big"),
                )
        return None
    return None


def _validate_svg(payload: bytes) -> None:
    try:
        decoded_payload = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise StarHistoryError("generated SVG must be strict UTF-8") from exc
    if decoded_payload.startswith("\ufeff") or "\x00" in decoded_payload:
        raise StarHistoryError("generated SVG must be canonical UTF-8")
    upper_payload = decoded_payload.upper()
    if (
        "<!DOCTYPE" in upper_payload
        or "<!ENTITY" in upper_payload
        or "<?" in decoded_payload
    ):
        raise StarHistoryError("generated SVG contains forbidden XML directives")
    try:
        root = ET.fromstring(decoded_payload)
    except ET.ParseError as exc:
        raise StarHistoryError("generated SVG is not valid XML") from exc
    svg_namespace = "{http://www.w3.org/2000/svg}"
    if root.tag != f"{svg_namespace}svg":
        raise StarHistoryError("generated SVG root is invalid")
    allowed_attributes: dict[str, set[str]] = {
        "svg": {
            "viewBox",
            "width",
            "height",
            "preserveAspectRatio",
            "role",
            "aria-labelledby",
        },
        "title": {"id"},
        "desc": {"id"},
        "rect": {
            "x",
            "y",
            "width",
            "height",
            "rx",
            "fill",
            "fill-opacity",
            "stroke",
            "stroke-width",
            "filter",
        },
        "defs": set(),
        "filter": {"id", "filterUnits", "x", "y", "width", "height"},
        "feTurbulence": {"type", "baseFrequency", "result"},
        "feDisplacementMap": {
            "scale",
            "xChannelSelector",
            "yChannelSelector",
            "in",
            "in2",
        },
        "clipPath": {"id"},
        "circle": {"r", "cx", "cy"},
        "g": {"font-family"},
        "image": {"x", "y", "width", "height", "href", "clip-path"},
        "line": {"x1", "y1", "x2", "y2", "stroke"},
        "path": {
            "class",
            "d",
            "fill",
            "stroke",
            "stroke-width",
            "stroke-linecap",
            "stroke-linejoin",
            "filter",
        },
        "text": {
            "x",
            "y",
            "text-anchor",
            "font-size",
            "font-weight",
            "fill",
            "transform",
        },
    }
    exact_attribute_values: dict[str, set[str]] = {
        "filter": {"url(#xkcdify)"},
        "fill": {
            "none",
            "#ffffff",
            "#000000",
            "#0d1117",
            "#dd4528",
            "#ff6b6b",
            "#666666",
        },
        "stroke": {
            "#ffffff",
            "#000000",
            "#dd4528",
            "#ff6b6b",
        },
        "font-family": {"xkcd"},
        "class": {"xkcd-chart-xyline"},
        "id": {"title", "desc", "xkcdify", "clip-circle-title"},
        "role": {"img"},
        "aria-labelledby": {"title desc"},
        "preserveAspectRatio": {"xMidYMid meet"},
        "filterUnits": {"userSpaceOnUse"},
        "type": {"fractalNoise"},
        "result": {"noise"},
        "in": {"SourceGraphic"},
        "in2": {"noise"},
        "xChannelSelector": {"R"},
        "yChannelSelector": {"G"},
        "baseFrequency": {"0.05"},
        "scale": {"5"},
        "fill-opacity": {"0.92"},
        "stroke-linecap": {"round"},
        "stroke-linejoin": {"round"},
        "text-anchor": {"start", "middle", "end"},
        "font-size": {"15", "16", "17", "20"},
        "font-weight": {"700"},
        "transform": {"rotate(-90 22 272)"},
    }
    avatar_count = 0
    watermark_count = 0
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(svg_namespace):
            raise StarHistoryError("generated SVG contains a foreign namespace")
        local_name = element.tag[len(svg_namespace) :]
        allowed_for_element = allowed_attributes.get(local_name)
        if allowed_for_element is None:
            raise StarHistoryError("generated SVG contains a forbidden element")
        if local_name == "image":
            avatar_attributes = {
                "x": "316",
                "y": "12",
                "width": "22",
                "height": "22",
                "href": OWNER_AVATAR_DATA_URI,
                "clip-path": "url(#clip-circle-title)",
            }
            watermark_attributes = {
                "x": "635",
                "y": "508.333",
                "width": "20",
                "height": "20",
                "href": WATERMARK_LOGO_DATA_URI,
            }
            if element.attrib == avatar_attributes:
                avatar_count += 1
            elif element.attrib == watermark_attributes:
                watermark_count += 1
            else:
                raise StarHistoryError("generated SVG contains an unreviewed image")
        for raw_name, value in element.attrib.items():
            if raw_name.startswith("{") or raw_name not in allowed_for_element:
                raise StarHistoryError("generated SVG contains a forbidden attribute")
            if (
                not value.isascii()
                or "\\" in value
                or "/*" in value
                or "*/" in value
                or any(ord(character) < 0x20 for character in value)
            ):
                raise StarHistoryError("generated SVG contains an unsafe attribute value")
            exact_values = exact_attribute_values.get(raw_name)
            if exact_values is not None and value not in exact_values:
                raise StarHistoryError("generated SVG contains an unsafe attribute value")
            if raw_name == "href":
                if local_name != "image" or value not in {
                    OWNER_AVATAR_DATA_URI,
                    WATERMARK_LOGO_DATA_URI,
                }:
                    raise StarHistoryError("generated SVG contains an external resource")
            lowered = value.lower().replace(" ", "")
            if "url(" in lowered and lowered not in {
                "url(#xkcdify)",
                "url(#clip-circle-title)",
            }:
                raise StarHistoryError("generated SVG contains an external resource")
            if lowered.startswith(("http:", "https:", "//")):
                raise StarHistoryError("generated SVG contains an external resource")
    if avatar_count != 1 or watermark_count != 1:
        raise StarHistoryError("generated SVG must contain both reviewed images")
    try:
        avatar = base64.b64decode(OWNER_AVATAR_BASE64, validate=True)
    except ValueError as exc:
        raise StarHistoryError("reviewed avatar data is invalid") from exc
    if (
        len(avatar) > MAX_INLINE_AVATAR_BYTES
        or hashlib.sha256(avatar).hexdigest() != OWNER_AVATAR_SHA256
        or _reviewed_avatar_dimensions(avatar) != OWNER_AVATAR_DIMENSIONS
    ):
        raise StarHistoryError("reviewed avatar data is invalid")
    try:
        watermark = base64.b64decode(WATERMARK_LOGO_BASE64, validate=True)
    except ValueError as exc:
        raise StarHistoryError("reviewed watermark data is invalid") from exc
    png_header = (
        watermark.startswith(b"\x89PNG\r\n\x1a\n")
        and watermark[8:12] == (13).to_bytes(4, "big")
        and watermark[12:16] == b"IHDR"
        and len(watermark) >= 33
    )
    watermark_dimensions = (
        (
            int.from_bytes(watermark[16:20], "big"),
            int.from_bytes(watermark[20:24], "big"),
        )
        if png_header
        else None
    )
    if (
        len(watermark) > MAX_INLINE_WATERMARK_BYTES
        or not png_header
        or watermark_dimensions != WATERMARK_LOGO_DIMENSIONS
        or watermark[24:29] != bytes((8, 6, 0, 0, 0))
        or not watermark.endswith(b"IEND\xaeB`\x82")
        or hashlib.sha256(watermark).hexdigest() != WATERMARK_LOGO_SHA256
    ):
        raise StarHistoryError("reviewed watermark data is invalid")


def _output_payloads(state: Mapping[str, Any]) -> dict[Path, bytes]:
    return {
        STATE_RELATIVE: canonical_state_bytes(state),
        LIGHT_SVG_RELATIVE: render_svg(state, "light"),
        DARK_SVG_RELATIVE: render_svg(state, "dark"),
    }


def _write_outputs(workspace: Path, state: Mapping[str, Any]) -> bool:
    payloads = _output_payloads(state)
    targets = {
        relative: _safe_target(workspace, relative, create_parent=True)
        for relative in OUTPUT_RELATIVES
    }
    if all(
        target.exists() and target.read_bytes() == payloads[relative]
        for relative, target in targets.items()
    ):
        return False

    temporary_paths: dict[Path, Path] = {}
    try:
        for relative in OUTPUT_RELATIVES:
            target = targets[relative]
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payloads[relative])
                handle.flush()
                os.fsync(handle.fileno())
                temporary_paths[relative] = Path(handle.name)
            os.chmod(temporary_paths[relative], 0o644)

        _validate_svg(temporary_paths[LIGHT_SVG_RELATIVE].read_bytes())
        _validate_svg(temporary_paths[DARK_SVG_RELATIVE].read_bytes())
        json.loads(temporary_paths[STATE_RELATIVE].read_bytes())

        for relative in OUTPUT_RELATIVES:
            checked_target = _safe_target(workspace, relative, create_parent=False)
            if checked_target != targets[relative]:
                raise StarHistoryError("output path changed during update")
            os.replace(temporary_paths[relative], targets[relative])
            temporary_paths.pop(relative, None)
    except OSError as exc:
        raise StarHistoryError("could not atomically replace Star History outputs") from exc
    finally:
        for temporary in temporary_paths.values():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    check_workspace(workspace)
    return True


def check_workspace(workspace: Path) -> None:
    state = load_state(workspace, require_canonical=True)
    expected = _output_payloads(state)
    for relative in OUTPUT_RELATIVES[1:]:
        target = _safe_target(workspace, relative, create_parent=False)
        actual = _read_limited(target, MAX_STATE_BYTES, str(relative))
        _validate_svg(actual)
        if actual != expected[relative]:
            raise StarHistoryError(f"{relative} is not synchronized with history.json")


def execute(
    command: str,
    *,
    github: GitHubGateway | None,
    clock: Clock,
    workspace: Path,
    force: bool = False,
    star_count: int | None = None,
) -> Result:
    root = _safe_workspace(workspace)
    now = _normalize_now(clock.now())

    if command == "backfill":
        state_target = _safe_target(root, STATE_RELATIVE, create_parent=False)
        if state_target.exists():
            raise StarHistoryError("history state already exists; refusing to overwrite backfill")
        if github is None:
            raise StarHistoryError("GitHub access is required for backfill")
        state = _build_backfill_state(github, now)
        changed = _write_outputs(root, state)
        return Result(changed, True, "historical Star data was reconstructed")

    if command == "initialize":
        state_target = _safe_target(root, STATE_RELATIVE, create_parent=False)
        if state_target.exists():
            raise StarHistoryError("history state already exists; refusing to overwrite it")
        if star_count is None:
            raise StarHistoryError("a fetched Star count is required for initialization")
        state = _build_initial_state(now, star_count)
        changed = _write_outputs(root, state)
        return Result(changed, True, "aggregate-only Star history was initialized")

    if command == "due":
        state = load_state(root)
        due = _snapshot_due(state, now)
        return Result(False, due, "true" if due else "false")

    if command == "record":
        state = load_state(root)
        due = _snapshot_due(state, now)
        if not due and not force:
            return Result(False, False, "snapshot is not due")
        if star_count is None:
            raise StarHistoryError("a fetched Star count is required for recording")
        checked_count = _strict_non_negative_int(star_count, "stargazers_count")
        if checked_count > MAX_STAR_COUNT:
            raise StarHistoryError("Star count exceeded the supported range")
        updated = _updated_with_snapshot(state, now, checked_count)
        if updated == state:
            return Result(False, due, "same-day snapshot is unchanged")
        changed = _write_outputs(root, updated)
        return Result(changed, due, "Star snapshot and charts were updated")

    if command == "check":
        check_workspace(root)
        return Result(False, None, "Star History outputs are valid")

    raise StarHistoryError("unknown Star History command")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _production_gateway(command: str) -> GitHubGateway | None:
    if command == "backfill":
        return GhGraphQLGateway()
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backfill", help="reconstruct history using maintainer access")
    initialize = subparsers.add_parser(
        "initialize", help="start an honest history from one aggregate count"
    )
    initialize.add_argument(
        "--count-file", required=True, type=Path, help="file containing one decimal count"
    )
    subparsers.add_parser(
        "due", help=f"print whether a {INTERVAL_DAYS}-day snapshot is due"
    )
    record = subparsers.add_parser(
        "record", help="apply a fetched aggregate count without GitHub credentials"
    )
    record.add_argument(
        "--count-file", required=True, type=Path, help="file containing one decimal count"
    )
    record.add_argument(
        "--force",
        action="store_true",
        help=f"record before {INTERVAL_DAYS} days",
    )
    subparsers.add_parser("check", help="verify state and deterministic SVG files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        star_count = (
            load_star_count_file(arguments.count_file)
            if arguments.command in {"initialize", "record"}
            else None
        )
        result = execute(
            arguments.command,
            github=_production_gateway(arguments.command),
            clock=SystemClock(),
            workspace=_repository_root(),
            force=bool(getattr(arguments, "force", False)),
            star_count=star_count,
        )
    except StarHistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # Defensive: never print exception data that may hold a token.
        print(f"error: unexpected internal error ({type(exc).__name__})", file=sys.stderr)
        return 1

    if arguments.command == "due":
        print("true" if result.due else "false")
    else:
        print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
