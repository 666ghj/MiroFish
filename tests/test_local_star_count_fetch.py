import ast
import io
import json
import os
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts import fetch_star_count


TOKEN_SENTINEL = "TOKEN_FETCH_ONLY_DO_NOT_LEAK_7z9"


class RecordingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(
            {"path": self.path, "headers": dict(self.headers.items())}
        )
        response = self.server.response
        self.send_response(response["status"])
        for name, value in response.get("headers", {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(response.get("body", b""))
        except BrokenPipeError:
            pass

    def log_message(self, *_args):
        return


class LocalHttpServer:
    def __init__(self, *, status=200, headers=None, body=b""):
        self.response = {
            "status": status,
            "headers": headers or {},
            "body": body,
        }

    def __enter__(self):
        self.server = HTTPServer(("127.0.0.1", 0), RecordingHandler)
        self.server.requests = []
        self.server.response = self.response
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/repository"
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class FetchStarCountTests(unittest.TestCase):
    def run_main(self, api_url):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(fetch_star_count, "API_URL", api_url),
            patch.dict(os.environ, {"GITHUB_TOKEN": TOKEN_SENTINEL}, clear=False),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = fetch_star_count.main([])
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_fetcher_is_standalone_stdlib_only_and_has_fixed_api(self):
        source_path = Path(fetch_star_count.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])

        self.assertNotIn("scripts", imported_roots)
        self.assertNotIn("star_history", imported_roots)
        self.assertEqual(
            fetch_star_count.API_URL,
            "https://api.github.com/repos/666ghj/MiroFish",
        )

    def test_success_stdout_is_only_one_decimal_count(self):
        body = json.dumps({"stargazers_count": 41782}).encode()
        with LocalHttpServer(body=body) as server:
            exit_code, stdout, stderr = self.run_main(server.url)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "41782\n")
        self.assertEqual(stderr, "")
        self.assertEqual(len(server.server.requests), 1)
        request = server.server.requests[0]
        self.assertEqual(request["path"], "/repository")
        self.assertEqual(
            request["headers"]["Authorization"], f"Bearer {TOKEN_SENTINEL}"
        )

    def test_redirect_is_refused_without_forwarding_token(self):
        with LocalHttpServer(body=b'{"stargazers_count": 99}') as target:
            with LocalHttpServer(
                status=302,
                headers={"Location": target.url},
                body=f"unsafe-body {TOKEN_SENTINEL}".encode(),
            ) as source:
                exit_code, stdout, stderr = self.run_main(source.url)

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(target.server.requests, [])
        self.assertIn("redirect was refused", stderr)
        self.assertNotIn(TOKEN_SENTINEL, stderr)
        self.assertNotIn("unsafe-body", stderr)

    def test_malformed_oversized_and_invalid_counts_are_sanitized(self):
        bodies = [
            b"not-json " + TOKEN_SENTINEL.encode(),
            b"x" * (fetch_star_count.MAX_HTTP_BYTES + 1),
            json.dumps([]).encode(),
            json.dumps({}).encode(),
            json.dumps({"stargazers_count": True}).encode(),
            json.dumps({"stargazers_count": -1}).encode(),
            json.dumps({"stargazers_count": 1.5}).encode(),
            json.dumps({"stargazers_count": "1"}).encode(),
        ]
        for body in bodies:
            with self.subTest(body_prefix=body[:32]):
                with LocalHttpServer(body=body) as server:
                    exit_code, stdout, stderr = self.run_main(server.url)

                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("error: "))
                self.assertNotIn(TOKEN_SENTINEL, stderr)
                self.assertNotIn("not-json", stderr)

    def test_status_and_network_errors_do_not_echo_exception_data(self):
        with LocalHttpServer(
            status=500,
            body=f"unsafe-body {TOKEN_SENTINEL}".encode(),
        ) as server:
            exit_code, stdout, stderr = self.run_main(server.url)

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("unavailable", stderr)
        self.assertNotIn(TOKEN_SENTINEL, stderr)
        self.assertNotIn("unsafe-body", stderr)

        class FailingOpener:
            def open(self, *_args, **_kwargs):
                raise OSError(TOKEN_SENTINEL)

        with self.assertRaises(fetch_star_count.FetchError) as captured:
            fetch_star_count.fetch_star_count(TOKEN_SENTINEL, FailingOpener())
        self.assertNotIn(TOKEN_SENTINEL, str(captured.exception))

    def test_missing_or_newline_token_is_rejected_without_stdout(self):
        for token in ("", "bad\ntoken", "bad\rtoken"):
            with self.subTest(token=repr(token)):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch.dict(os.environ, {"GITHUB_TOKEN": token}, clear=False),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    exit_code = fetch_star_count.main([])
                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout.getvalue(), "")
                if token:
                    self.assertNotIn(token, stderr.getvalue())

    def test_workflow_keeps_credentials_out_of_record_and_render_steps(self):
        repository = Path(__file__).resolve().parents[1]
        workflow = (
            repository / ".github/workflows/update-star-history.yml"
        ).read_text(encoding="utf-8")
        renderer = (repository / "scripts/star_history.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("cron: '17 3 1,16 * *'", workflow)
        self.assertIn("timezone: 'UTC'", workflow)
        trigger_block = workflow.split("\non:\n", 1)[1].split(
            "\npermissions:\n", 1
        )[0]
        self.assertEqual(
            trigger_block,
            "  schedule:\n"
            "    - cron: '17 3 1,16 * *'\n"
            "      timezone: 'UTC'\n"
            "  workflow_dispatch:",
        )
        self.assertNotIn("due-check:", workflow)
        self.assertNotIn("star_history.py due", workflow)
        self.assertNotIn("inputs.force", workflow)
        self.assertNotIn("actions/checkout", workflow)
        self.assertNotIn("uses:", workflow)
        self.assertNotIn("\n  pull_request:", workflow)
        self.assertNotIn("\n  pull_request_target:", workflow)
        self.assertNotIn("\n  workflow_run:", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertIn("sha256sum --check --strict", workflow)
        self.assertIn("-c core.hooksPath=/dev/null", workflow)
        self.assertNotIn("star_history.py sample", workflow)
        self.assertNotIn('os.environ.get("GITHUB_TOKEN"', renderer)
        self.assertNotIn('subparsers.add_parser("sample"', renderer)

        token_steps = [
            section
            for section in workflow.split("\n      - name: ")
            if "GITHUB_TOKEN: ${{ github.token }}" in section
        ]
        self.assertEqual(len(token_steps), 2)
        for section in token_steps:
            step_name = section.splitlines()[0]
            self.assertTrue(
                step_name.startswith("Fetch aggregate Star count only")
                or step_name.startswith(
                    "Publish through a verified pull request with an ephemeral credential"
                )
            )

        record_steps = [
            section
            for section in workflow.split("\n      - name: ")
            if "star_history.py record" in section
        ]
        self.assertEqual(len(record_steps), 1)
        for section in record_steps:
            self.assertIn("GITHUB_TOKEN: ''", section)
            self.assertIn("GH_TOKEN: ''", section)
            self.assertNotIn("${{ github.token }}", section)
            self.assertIn("--force", section)

    def test_workflow_submits_a_verified_pull_request_for_manual_merge(self):
        repository = Path(__file__).resolve().parents[1]
        workflow = (
            repository / ".github/workflows/update-star-history.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("contents: write", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertIn("id: count", workflow)
        self.assertIn("printf 'value=%s\\n' \"${lines[0]}\"", workflow)
        self.assertIn('[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ ]]', workflow)
        self.assertIn('[[ "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]', workflow)
        self.assertIn(
            'update_branch="automation/star-history/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
            workflow,
        )
        self.assertIn("ls-remote \\", workflow)
        self.assertIn("--exit-code \\", workflow)
        self.assertIn("--heads \\", workflow)
        self.assertIn('"refs/heads/$update_branch" >/dev/null', workflow)
        self.assertIn('"HEAD:refs/heads/$update_branch"', workflow)
        self.assertEqual(workflow.count("\n            push \\"), 1)
        self.assertNotIn('"HEAD:$GITHUB_REF"', workflow)
        self.assertNotIn("HEAD:refs/heads/main", workflow)

        self.assertIn(
            'gh api --method POST "repos/$EXPECTED_REPOSITORY/pulls"', workflow
        )
        self.assertIn('[[ "$pr_state" == "open" ]]', workflow)
        self.assertIn('[[ "$pr_draft" == "false" ]]', workflow)
        self.assertIn(
            '[[ "${pr_base_repo,,}" == "${EXPECTED_REPOSITORY,,}" ]]', workflow
        )
        self.assertIn('[[ "$pr_base_ref" == "$EXPECTED_DEFAULT_BRANCH" ]]', workflow)
        self.assertIn('[[ "$pr_base_sha" == "$base" ]]', workflow)
        self.assertIn(
            '[[ "${pr_head_repo,,}" == "${EXPECTED_REPOSITORY,,}" ]]', workflow
        )
        self.assertIn('[[ "$pr_head_ref" == "$update_branch" ]]', workflow)
        self.assertIn('[[ "$pr_head_sha" == "$head" ]]', workflow)
        self.assertIn('cmp --silent "$expected_files" "$pr_files"', workflow)
        self.assertGreaterEqual(workflow.count("          validate_open_pr\n"), 2)
        self.assertIn("Please review and merge this pull request manually.", workflow)
        self.assertIn("$GITHUB_STEP_SUMMARY", workflow)
        self.assertIn("existing automated Star History pull request", workflow)
        self.assertNotIn("pulls/$pr_number/merge", workflow)
        self.assertNotIn("gh pr merge", workflow)
        self.assertNotIn("merge_method=", workflow)
        self.assertNotIn("pulls/$pr_number/reviews", workflow)
        self.assertNotIn("git/refs/heads/$update_branch", workflow)
        self.assertNotIn("Verify published main without tokens", workflow)
        self.assertNotIn("Delete verified temporary branch", workflow)
        self.assertNotIn("merged_by", workflow)
        self.assertNotIn("GIT_TRACE:", workflow)
        self.assertNotIn("GIT_TRACE_CURL:", workflow)
        self.assertNotIn("GIT_TRACE_PACKET:", workflow)
        self.assertNotIn("GIT_CURL_VERBOSE:", workflow)

        duplicate_guard_index = workflow.index(
            "pulls?state=open&base=$EXPECTED_DEFAULT_BRANCH&per_page=100"
        )
        push_index = workflow.index('"HEAD:refs/heads/$update_branch"')
        create_index = workflow.index(
            'gh api --method POST "repos/$EXPECTED_REPOSITORY/pulls"'
        )
        files_index = workflow.index(
            '"repos/$EXPECTED_REPOSITORY/pulls/$pr_number/files?per_page=100"'
        )
        revalidate_index = workflow.rindex("          validate_open_pr\n")
        remote_head_index = workflow.rindex(
            '"repos/$EXPECTED_REPOSITORY/git/ref/heads/$update_branch"'
        )
        summary_index = workflow.index("$GITHUB_STEP_SUMMARY")
        self.assertLess(duplicate_guard_index, push_index)
        self.assertLess(push_index, create_index)
        self.assertLess(create_index, files_index)
        self.assertLess(files_index, summary_index)
        self.assertLess(files_index, revalidate_index)
        self.assertLess(revalidate_index, remote_head_index)
        self.assertLess(remote_head_index, summary_index)


if __name__ == "__main__":
    unittest.main()
