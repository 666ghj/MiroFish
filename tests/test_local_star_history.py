import base64
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import star_history


UTC = timezone.utc
TOKEN_SENTINEL = "TOKEN_TEST_DO_NOT_LEAK_7z9"


class FixedClock:
    def __init__(self, value: str):
        self.value = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )

    def now(self):
        return self.value


class FakeGitHub:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.page_calls = []

    def fetch_stargazer_page(self, after):
        self.page_calls.append(after)
        return self.pages[after]


class FakeRunner:
    def __init__(self, completed):
        self.completed = completed
        self.arguments = None

    def run(self, arguments):
        self.arguments = list(arguments)
        return self.completed


def edge(cursor, timestamp):
    return star_history.StargazerEdge(
        cursor,
        datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
    )


def page(total, edges, has_next=False, end_cursor=None, remaining=1_000):
    return star_history.StargazerPage(
        total_count=total,
        edges=tuple(edges),
        has_next_page=has_next,
        end_cursor=end_cursor,
        rate_remaining=remaining,
    )


def state_with_snapshots(snapshots=None):
    return {
        "schema_version": 1,
        "repository": "666ghj/MiroFish",
        "timezone": "UTC",
        "ongoing_interval_days": 13,
        "reconstruction": {
            "method": "current_stargazers_starred_at",
            "generated_at": "2026-07-01T00:00:00Z",
            "daily": [],
        },
        "snapshots": snapshots or [],
    }


def seed_workspace(workspace, state):
    state_path = workspace / ".github/star-history/history.json"
    light_path = workspace / "static/image/star-history-light.svg"
    dark_path = workspace / "static/image/star-history-dark.svg"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    light_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_bytes(star_history.canonical_state_bytes(state))
    light_path.write_bytes(star_history.render_svg(state, "light"))
    dark_path.write_bytes(star_history.render_svg(state, "dark"))
    return state_path, light_path, dark_path


class StarHistoryBehaviorTests(unittest.TestCase):
    def test_backfill_writes_hand_computed_completed_daily_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            edges = [
                edge("c6", "2026-03-02T00:01:00Z"),
                edge("c5", "2026-03-01T00:00:00Z"),
                edge("c4", "2026-02-28T23:59:59Z"),
                edge("c3", "2026-02-28T23:59:59Z"),
                edge("c2", "2026-02-27T10:00:00Z"),
                edge("c1", "2026-02-25T12:00:00Z"),
            ]
            github = FakeGitHub({None: page(6, edges)})

            result = star_history.execute(
                "backfill",
                github=github,
                clock=FixedClock("2026-03-02T12:00:00Z"),
                workspace=workspace,
            )

            self.assertTrue(result.changed)
            state = json.loads(
                (workspace / ".github/star-history/history.json").read_text()
            )
            self.assertEqual(
                state["reconstruction"]["daily"],
                [
                    {"date": "2026-02-25", "stars": 1},
                    {"date": "2026-02-27", "stars": 2},
                    {"date": "2026-02-28", "stars": 4},
                    {"date": "2026-03-01", "stars": 5},
                ],
            )
            self.assertEqual(state["snapshots"], [])
            star_history.check_workspace(workspace)

    def test_backfill_reads_101_edges_across_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            january_first = [
                edge(f"jan1-{index}", f"2026-01-01T00:00:{index % 60:02d}Z")
                for index in range(100)
            ]
            first_edges = [edge("jan2", "2026-01-02T00:00:00Z")] + january_first[:99]
            github = FakeGitHub(
                {
                    None: page(101, first_edges, True, "next-page"),
                    "next-page": page(101, january_first[99:]),
                }
            )

            star_history.execute(
                "backfill",
                github=github,
                clock=FixedClock("2026-01-03T00:00:00Z"),
                workspace=workspace,
            )

            state = json.loads(
                (workspace / ".github/star-history/history.json").read_text()
            )
            self.assertEqual(github.page_calls, [None, "next-page"])
            self.assertEqual(
                state["reconstruction"]["daily"],
                [
                    {"date": "2026-01-01", "stars": 100},
                    {"date": "2026-01-02", "stars": 101},
                ],
            )

    def test_backfill_fails_closed_on_cursor_or_count_inconsistency(self):
        cases = {
            "duplicate edge": page(
                2,
                [edge("same", "2026-01-01T00:00:00Z"), edge("same", "2026-01-02T00:00:00Z")],
            ),
            "count mismatch": page(2, [edge("only", "2026-01-01T00:00:00Z")]),
        }
        for label, first_page in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                with self.assertRaises(star_history.StarHistoryError):
                    star_history.execute(
                        "backfill",
                        github=FakeGitHub({None: first_page}),
                        clock=FixedClock("2026-01-03T00:00:00Z"),
                        workspace=workspace,
                    )
                self.assertFalse(
                    (workspace / ".github/star-history/history.json").exists()
                )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            github = FakeGitHub(
                {
                    None: page(
                        2,
                        [edge("first", "2026-01-02T00:00:00Z")],
                        True,
                        "repeated-page",
                    ),
                    "repeated-page": page(
                        2,
                        [edge("second", "2026-01-01T00:00:00Z")],
                        False,
                        "repeated-page",
                    ),
                }
            )
            with self.assertRaises(star_history.StarHistoryError):
                star_history.execute(
                    "backfill",
                    github=github,
                    clock=FixedClock("2026-01-03T00:00:00Z"),
                    workspace=workspace,
                )
            self.assertFalse(
                (workspace / ".github/star-history/history.json").exists()
            )

    def test_backfill_accepts_exact_rate_limit_reserve_after_first_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            github = FakeGitHub(
                {
                    None: page(
                        1,
                        [edge("only", "2026-01-01T00:00:00Z")],
                        remaining=star_history.RATE_LIMIT_RESERVE,
                    )
                }
            )

            result = star_history.execute(
                "backfill",
                github=github,
                clock=FixedClock("2026-01-02T00:00:00Z"),
                workspace=workspace,
            )

            self.assertTrue(result.changed)
            self.assertEqual(github.page_calls, [None])

    def test_backfill_refuses_dangling_output_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_path = workspace / ".github/star-history/history.json"
            state_path.parent.mkdir(parents=True)
            state_path.symlink_to(workspace / "missing-history.json")

            with self.assertRaises(star_history.StarHistoryError):
                star_history.execute(
                    "backfill",
                    github=FakeGitHub({None: page(0, [])}),
                    clock=FixedClock("2026-01-02T00:00:00Z"),
                    workspace=workspace,
                )

            self.assertTrue(state_path.is_symlink())

    def test_initialize_starts_from_one_honest_aggregate_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = star_history.execute(
                "initialize",
                github=None,
                clock=FixedClock("2026-07-20T05:00:00Z"),
                workspace=workspace,
                star_count=42,
            )

            self.assertTrue(result.changed)
            state = star_history.load_state(workspace)
            self.assertEqual(
                state["reconstruction"]["method"], "aggregate_snapshot_only"
            )
            self.assertEqual(state["reconstruction"]["daily"], [])
            self.assertEqual(
                state["snapshots"],
                [{"at": "2026-07-20T05:00:00Z", "stars": 42}],
            )
            star_history.check_workspace(workspace)

    def test_due_boundary_matches_configured_interval(self):
        baseline = state_with_snapshots(
            [{"at": "2026-07-20T05:00:00Z", "stars": 100}]
        )
        latest = datetime(2026, 7, 20, 5, 0, 0, tzinfo=UTC)
        boundary = latest + star_history.timedelta(
            days=star_history.INTERVAL_DAYS
        )
        cases = [
            (
                (boundary - star_history.timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                False,
            ),
            (boundary.strftime("%Y-%m-%dT%H:%M:%SZ"), True),
        ]
        for now, expected in cases:
            with self.subTest(now=now), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                seed_workspace(workspace, baseline)
                result = star_history.execute(
                    "due",
                    github=None,
                    clock=FixedClock(now),
                    workspace=workspace,
                )
                self.assertIs(result.due, expected)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            seed_workspace(workspace, state_with_snapshots())
            result = star_history.execute(
                "due",
                github=None,
                clock=FixedClock("2026-07-20T05:00:00Z"),
                workspace=workspace,
            )
            self.assertTrue(result.due)

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            future_state = state_with_snapshots()
            future_state["reconstruction"]["generated_at"] = "2026-08-01T00:00:00Z"
            seed_workspace(workspace, future_state)
            with self.assertRaises(star_history.StarHistoryError):
                star_history.execute(
                    "due",
                    github=None,
                    clock=FixedClock("2026-07-20T05:00:00Z"),
                    workspace=workspace,
                )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            seed_workspace(workspace, baseline)
            with self.assertRaises(star_history.StarHistoryError):
                star_history.execute(
                    "due",
                    github=None,
                    clock=FixedClock("2026-07-20T04:59:59Z"),
                    workspace=workspace,
                )

    def test_record_before_due_does_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_path, light_path, dark_path = seed_workspace(
                workspace,
                state_with_snapshots(
                    [{"at": "2026-07-20T05:00:00Z", "stars": 100}]
                ),
            )
            before = tuple(path.read_bytes() for path in (state_path, light_path, dark_path))
            latest = datetime(2026, 7, 20, 5, 0, 0, tzinfo=UTC)
            before_due = latest + star_history.timedelta(
                days=star_history.INTERVAL_DAYS
            ) - star_history.timedelta(seconds=1)
            result = star_history.execute(
                "record",
                github=None,
                clock=FixedClock(before_due.strftime("%Y-%m-%dT%H:%M:%SZ")),
                workspace=workspace,
                star_count=101,
            )

            self.assertFalse(result.changed)
            self.assertEqual(
                before,
                tuple(path.read_bytes() for path in (state_path, light_path, dark_path)),
            )

    def test_record_applies_count_file_without_github_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_path, light_path, dark_path = seed_workspace(
                workspace, state_with_snapshots()
            )
            count_file = workspace / "fetched-count"
            count_file.write_bytes(b"123\n")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"GITHUB_TOKEN": TOKEN_SENTINEL, "GH_TOKEN": TOKEN_SENTINEL},
                    clear=False,
                ),
                patch.object(star_history, "_repository_root", return_value=workspace),
                patch.object(
                    star_history,
                    "SystemClock",
                    return_value=FixedClock("2026-07-20T05:00:00Z"),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = star_history.main(
                    ["record", "--count-file", str(count_file), "--force"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn(TOKEN_SENTINEL, stdout.getvalue())
            self.assertEqual(
                star_history.load_state(workspace)["snapshots"],
                [{"at": "2026-07-20T05:00:00Z", "stars": 123}],
            )
            for output in (state_path, light_path, dark_path):
                self.assertNotIn(TOKEN_SENTINEL.encode(), output.read_bytes())
            star_history.check_workspace(workspace)

    def test_count_file_rejects_symlinks_malformed_and_extreme_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid"
            valid.write_bytes(b"0\n")
            self.assertEqual(star_history.load_star_count_file(valid), 0)

            cases = {
                "empty": b"",
                "negative": b"-1\n",
                "leading-zero": b"01\n",
                "json": b'{"stargazers_count": 1}\n',
                "too-large": b"9" * (star_history.MAX_COUNT_FILE_BYTES + 1),
                "out-of-range": str(star_history.MAX_STAR_COUNT + 1).encode() + b"\n",
            }
            for name, payload in cases.items():
                path = root / name
                path.write_bytes(payload)
                with self.subTest(name=name), self.assertRaises(
                    star_history.StarHistoryError
                ):
                    star_history.load_star_count_file(path)

            link = root / "link"
            link.symlink_to(valid)
            with self.assertRaises(star_history.StarHistoryError):
                star_history.load_star_count_file(link)

    def test_force_same_day_same_count_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state_path, light_path, dark_path = seed_workspace(
                workspace,
                state_with_snapshots(
                    [{"at": "2026-07-20T05:00:00Z", "stars": 100}]
                ),
            )
            before = tuple(path.read_bytes() for path in (state_path, light_path, dark_path))

            result = star_history.execute(
                "record",
                github=None,
                clock=FixedClock("2026-07-20T06:00:00Z"),
                workspace=workspace,
                force=True,
                star_count=100,
            )

            self.assertFalse(result.changed)
            self.assertEqual(
                before,
                tuple(path.read_bytes() for path in (state_path, light_path, dark_path)),
            )

    def test_force_same_day_changed_count_replaces_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            seed_workspace(
                workspace,
                state_with_snapshots(
                    [{"at": "2026-07-20T05:00:00Z", "stars": 100}]
                ),
            )

            result = star_history.execute(
                "record",
                github=None,
                clock=FixedClock("2026-07-20T06:00:00Z"),
                workspace=workspace,
                force=True,
                star_count=101,
            )

            self.assertTrue(result.changed)
            state = star_history.load_state(workspace)
            self.assertEqual(
                state["snapshots"],
                [{"at": "2026-07-20T06:00:00Z", "stars": 101}],
            )

    def test_new_date_appends_even_when_count_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            seed_workspace(
                workspace,
                state_with_snapshots(
                    [{"at": "2026-07-20T05:00:00Z", "stars": 100}]
                ),
            )

            result = star_history.execute(
                "record",
                github=None,
                clock=FixedClock("2026-08-04T05:00:00Z"),
                workspace=workspace,
                star_count=100,
            )

            self.assertTrue(result.changed)
            self.assertEqual(
                star_history.load_state(workspace)["snapshots"],
                [
                    {"at": "2026-07-20T05:00:00Z", "stars": 100},
                    {"at": "2026-08-04T05:00:00Z", "stars": 100},
                ],
            )

    def test_schema_rejects_unknown_identity_fields_and_boolean_counts(self):
        baseline = state_with_snapshots()
        cases = []
        top = deepcopy(baseline)
        top["login"] = "secret-user"
        cases.append(top)
        reconstruction = deepcopy(baseline)
        reconstruction["reconstruction"]["avatar"] = "secret-avatar"
        cases.append(reconstruction)
        daily = deepcopy(baseline)
        daily["reconstruction"]["daily"] = [
            {"date": "2026-06-30", "stars": 1, "user": "secret-user"}
        ]
        cases.append(daily)
        snapshot = deepcopy(baseline)
        snapshot["snapshots"] = [
            {"at": "2026-07-20T05:00:00Z", "stars": 1, "profile_url": "secret"}
        ]
        cases.append(snapshot)
        boolean_count = deepcopy(baseline)
        boolean_count["snapshots"] = [
            {"at": "2026-07-20T05:00:00Z", "stars": True}
        ]
        cases.append(boolean_count)

        for state in cases:
            with self.subTest(state=state), self.assertRaises(
                star_history.StarHistoryError
            ):
                star_history.validate_state(state)

    def test_svg_is_accessible_self_contained_and_deterministic(self):
        state = {
            "schema_version": 1,
            "repository": "666ghj/MiroFish",
            "timezone": "UTC",
            "ongoing_interval_days": 13,
            "reconstruction": {
                "method": "current_stargazers_starred_at",
                "generated_at": "2026-01-04T00:00:00Z",
                "daily": [
                    {"date": "2026-01-01", "stars": 1},
                    {"date": "2026-01-03", "stars": 3},
                ],
            },
            "snapshots": [
                {"at": "2026-01-20T10:00:00Z", "stars": 3},
                {"at": "2026-02-04T10:00:00Z", "stars": 2},
            ],
        }

        light = star_history.render_svg(state, "light")
        dark = star_history.render_svg(state, "dark")

        self.assertEqual(light, star_history.render_svg(state, "light"))
        self.assertNotEqual(light, dark)
        self.assertIn(b"viewBox=\"0 0 800 533.333\"", light)
        self.assertIn(b"Star History", light)
        self.assertIn(b"666ghj/MiroFish", light)
        self.assertIn(b"star-history.com", light)
        self.assertIn(b"feTurbulence", light)
        self.assertIn(b"feDisplacementMap", light)
        self.assertIn(b"filter=\"url(#xkcdify)\"", light)
        self.assertNotIn(b"stroke-dasharray", light)
        self.assertNotIn(b"<polyline", light)
        self.assertNotIn(TOKEN_SENTINEL.encode(), light)
        root = ET.fromstring(light)
        names = {element.tag.rsplit("}", 1)[-1] for element in root.iter()}
        self.assertIn("title", names)
        self.assertIn("desc", names)
        self.assertIn("filter", names)
        self.assertIn("image", names)
        self.assertTrue(names.isdisjoint({"script", "foreignObject"}))
        images = [
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "image"
        ]
        self.assertEqual(len(images), 2)
        images_by_href = {element.attrib["href"]: element for element in images}
        avatar_image = images_by_href[star_history.OWNER_AVATAR_DATA_URI]
        watermark_image = images_by_href[star_history.WATERMARK_LOGO_DATA_URI]
        self.assertEqual(
            avatar_image.attrib["href"], star_history.OWNER_AVATAR_DATA_URI
        )
        self.assertEqual(avatar_image.attrib["width"], "22")
        self.assertEqual(avatar_image.attrib["height"], "22")
        avatar = base64.b64decode(
            star_history.OWNER_AVATAR_BASE64, validate=True
        )
        self.assertLessEqual(len(avatar), star_history.MAX_INLINE_AVATAR_BYTES)
        self.assertEqual(
            hashlib.sha256(avatar).hexdigest(),
            star_history.OWNER_AVATAR_SHA256,
        )
        self.assertEqual(
            star_history._reviewed_avatar_dimensions(avatar),
            star_history.OWNER_AVATAR_DIMENSIONS,
        )
        watermark = base64.b64decode(
            star_history.WATERMARK_LOGO_BASE64, validate=True
        )
        self.assertEqual(len(watermark), 4_185)
        self.assertEqual(
            hashlib.sha256(watermark).hexdigest(),
            star_history.WATERMARK_LOGO_SHA256,
        )
        self.assertEqual(
            (
                int.from_bytes(watermark[16:20], "big"),
                int.from_bytes(watermark[20:24], "big"),
            ),
            star_history.WATERMARK_LOGO_DIMENSIONS,
        )
        self.assertEqual(watermark_image.attrib["width"], "20")
        self.assertEqual(watermark_image.attrib["height"], "20")
        curves = [
            element
            for element in root.iter()
            if element.attrib.get("class") == "xkcd-chart-xyline"
        ]
        self.assertEqual(len(curves), 1)
        self.assertFalse(curves[0].attrib["d"].startswith("M70,483.33"))
        self.assertIn("C", curves[0].attrib["d"])
        visible_labels = [
            element.text or ""
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "text"
        ]
        self.assertFalse(
            any(
                word in label.lower()
                for label in visible_labels
                for word in ("reconstructed", "snapshot")
            )
        )
        legend_labels = [
            element.text
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "text"
            and element.text == "666ghj/MiroFish"
        ]
        self.assertEqual(legend_labels, ["666ghj/MiroFish"])
        for element in root.iter():
            for name, value in element.attrib.items():
                local = name.rsplit("}", 1)[-1].lower()
                self.assertFalse(local.startswith("on"))
                self.assertNotEqual(local, "src")
                if local == "href":
                    self.assertIn(
                        value,
                        {
                            star_history.OWNER_AVATAR_DATA_URI,
                            star_history.WATERMARK_LOGO_DATA_URI,
                        },
                    )
                self.assertFalse(value.lower().startswith(("http:", "https:", "//")))

        single_point = star_history.render_svg(
            state_with_snapshots(
                [{"at": "2026-07-20T05:00:00Z", "stars": 42}]
            ),
            "light",
        )
        single_root = ET.fromstring(single_point)
        single_curve = next(
            element
            for element in single_root.iter()
            if element.attrib.get("class") == "xkcd-chart-xyline"
        )
        self.assertEqual(single_curve.attrib["d"], "M416,60H424")
        self.assertNotIn("483.33", single_curve.attrib["d"])
        self.assertNotIn("L", single_curve.attrib["d"])
        self.assertNotIn("C", single_curve.attrib["d"])
        single_text = [
            element.text
            for element in single_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "text"
        ]
        self.assertEqual(
            [
                label
                for label in single_text
                if label in {"Sun 19", "Mon 20", "Tue 21"}
            ],
            ["Sun 19", "Mon 20", "Tue 21"],
        )

        medium_window = state_with_snapshots(
            [
                {"at": "2026-01-01T00:00:00Z", "stars": 1},
                {"at": "2026-04-01T00:00:00Z", "stars": 2},
            ]
        )
        medium_window["reconstruction"]["generated_at"] = "2026-01-01T00:00:00Z"
        medium_text = [
            element.text or ""
            for element in ET.fromstring(
                star_history.render_svg(medium_window, "light")
            ).iter()
            if element.tag.rsplit("}", 1)[-1] == "text"
        ]
        date_ticks = [
            label
            for label in medium_text
            if len(label.split()) == 2
            and label.split()[0].isdigit()
            and len(label.split()[1]) == 3
        ]
        self.assertEqual(len(date_ticks), 6)
        self.assertEqual(len(set(date_ticks)), 6)

        short_window = {
            "schema_version": 1,
            "repository": "666ghj/MiroFish",
            "timezone": "UTC",
            "ongoing_interval_days": 13,
            "reconstruction": {
                "method": "current_stargazers_starred_at",
                "generated_at": "2026-01-02T00:00:00Z",
                "daily": [{"date": "2026-01-01", "stars": 1}],
            },
            "snapshots": [{"at": "2026-01-02T05:00:00Z", "stars": 2}],
        }
        short_text = [
            element.text or ""
            for element in ET.fromstring(
                star_history.render_svg(short_window, "light")
            ).iter()
            if element.tag.rsplit("}", 1)[-1] == "text"
        ]
        weekday_ticks = [
            label
            for label in short_text
            if label.split()[0]
            in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        ]
        self.assertEqual(weekday_ticks, ["Fri 02"])

        earliest_state = state_with_snapshots()
        earliest_state["reconstruction"]["generated_at"] = "0001-01-01T00:00:00Z"
        self.assertIn(
            b"Star History", star_history.render_svg(earliest_state, "light")
        )

        empty_root = ET.fromstring(
            star_history.render_svg(state_with_snapshots(), "light")
        )
        empty_y_ticks = [
            float(element.attrib["y1"])
            for element in empty_root.iter()
            if element.tag.rsplit("}", 1)[-1] == "line"
            and element.attrib.get("x1") == "69"
            and element.attrib.get("x2") == "70"
        ]
        self.assertEqual(len(empty_y_ticks), 5)
        self.assertTrue(all(60 <= value <= 483.333 for value in empty_y_ticks))

    def test_svg_validator_rejects_unreviewed_or_active_content(self):
        reviewed_avatar = (
            '<image x="316" y="12" width="22" height="22" href="'
            + star_history.OWNER_AVATAR_DATA_URI
            + '" clip-path="url(#clip-circle-title)"/>'
        )
        reviewed_watermark = (
            '<image x="635" y="508.333" width="20" height="20" href="'
            + star_history.WATERMARK_LOGO_DATA_URI
            + '"/>'
        )
        valid_shell = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            + reviewed_avatar
            + reviewed_watermark
            + "</svg>"
        )
        processing_instruction = (
            '<?xml-stylesheet href="https://example.invalid/x.css"?>'
            + valid_shell
        )
        unsafe_payloads = [
            b'<svg><image href="https://example.invalid/avatar.jpg"/></svg>',
            b'<svg><image href="data:image/jpeg;base64,/9j/2Q=="/></svg>',
            b'<svg onload="alert(1)"></svg>',
            b'<svg><script>unsafe</script></svg>',
            b'<svg><path filter="url(https://example.invalid/filter.svg)"/></svg>',
            (
                '<svg xmlns="http://www.w3.org/2000/svg">'
                + reviewed_avatar
                + '<style>@import url(https://example.invalid/x.css)</style></svg>'
            ).encode(),
            (
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'style="background:url(https://example.invalid/x.png)">'
                + reviewed_avatar
                + "</svg>"
            ).encode(),
            processing_instruction.encode(),
            processing_instruction.encode("utf-16"),
            processing_instruction.encode("utf-16-be"),
            b"\xef\xbb\xbf" + valid_shell.encode(),
            (
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<image href="'
                + star_history.OWNER_AVATAR_DATA_URI
                + '"/></svg>'
            ).encode(),
            valid_shell.replace(
                "</svg>",
                '<path filter="u\\72l(https://example.invalid/f.svg)"/></svg>',
            ).encode(),
            valid_shell.replace(
                "</svg>",
                '<path filter="u/**/rl(https://example.invalid/f.svg)"/></svg>',
            ).encode(),
            valid_shell.replace(
                "</svg>",
                '<path fill="u\\000072l(https://example.invalid/f.svg)"/></svg>',
            ).encode(),
            valid_shell.replace(
                "</svg>",
                '<path filter="URL(HTTPS://example.invalid/f.svg)"/></svg>',
            ).encode(),
        ]
        for payload in unsafe_payloads:
            with self.subTest(payload=payload), self.assertRaises(
                star_history.StarHistoryError
            ):
                star_history._validate_svg(payload)

    def test_check_detects_svg_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            _, light_path, _ = seed_workspace(workspace, state_with_snapshots())
            light_path.write_bytes(
                light_path.read_bytes().replace(b"Star History", b"Star Historx", 1)
            )
            with self.assertRaises(star_history.StarHistoryError):
                star_history.execute(
                    "check",
                    github=None,
                    clock=FixedClock("2026-07-20T05:00:00Z"),
                    workspace=workspace,
                )


class GitHubAdapterTests(unittest.TestCase):
    def test_graphql_gateway_uses_identity_free_paginated_query(self):
        payload = {
            "data": {
                "repository": {
                    "stargazers": {
                        "totalCount": 1,
                        "edges": [
                            {"cursor": "edge-cursor", "starredAt": "2026-01-01T00:00:00Z"}
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": "edge-cursor"},
                    }
                },
                "rateLimit": {"cost": 1, "remaining": 4999, "resetAt": "2026-01-01T01:00:00Z"},
            }
        }
        runner = FakeRunner(
            subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        )
        gateway = star_history.GhGraphQLGateway(runner)

        result = gateway.fetch_stargazer_page("previous-page")

        arguments = "\n".join(runner.arguments)
        self.assertEqual(result.total_count, 1)
        self.assertIn("first: 100", arguments)
        self.assertIn("after: $after", arguments)
        self.assertIn("after=previous-page", arguments)
        expected_query = """\
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
        self.assertEqual(star_history.GRAPHQL_QUERY, expected_query)
        for forbidden in (
            "nodes",
            " node ",
            " login ",
            " avatar ",
            " databaseId ",
            " email ",
            " url ",
            TOKEN_SENTINEL,
        ):
            self.assertNotIn(forbidden, arguments)

    def test_graphql_gateway_rejects_malformed_nested_shape(self):
        payload = {
            "data": {
                "repository": {
                    "stargazers": {
                        "totalCount": 0,
                        "edges": [],
                        "pageInfo": [],
                    }
                },
                "rateLimit": {"remaining": 4999},
            }
        }
        gateway = star_history.GhGraphQLGateway(
            FakeRunner(subprocess.CompletedProcess([], 0, json.dumps(payload), ""))
        )

        with self.assertRaises(star_history.StarHistoryError):
            gateway.fetch_stargazer_page(None)

    def test_graphql_gateway_does_not_echo_failed_command_stderr(self):
        runner = FakeRunner(
            subprocess.CompletedProcess([], 1, "", f"failure {TOKEN_SENTINEL}")
        )
        gateway = star_history.GhGraphQLGateway(runner)
        with self.assertRaises(star_history.StarHistoryError) as captured:
            gateway.fetch_stargazer_page(None)
        self.assertNotIn(TOKEN_SENTINEL, str(captured.exception))

if __name__ == "__main__":
    unittest.main()
