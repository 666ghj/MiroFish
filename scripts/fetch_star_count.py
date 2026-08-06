#!/usr/bin/env python3
"""Fetch one repository's aggregate GitHub Star count without loading the renderer.

The successful stdout contract is deliberately tiny: one non-negative decimal
integer followed by a newline. Errors are fixed, sanitized messages on stderr.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


REPOSITORY = "666ghj/MiroFish"
API_URL = f"https://api.github.com/repos/{REPOSITORY}"
API_VERSION = "2026-03-10"
MAX_HTTP_BYTES = 1_000_000
TIMEOUT_SECONDS = 20


class FetchError(RuntimeError):
    """A safe error whose message never includes response or secret data."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so credentials cannot be forwarded elsewhere."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(NoRedirectHandler())


def _status_error(status: int) -> FetchError:
    if status in {301, 302, 303, 307, 308}:
        return FetchError("GitHub API redirect was refused")
    if status == 401:
        return FetchError("GitHub API authentication failed")
    if status == 403:
        return FetchError("GitHub API request was denied")
    if status == 404:
        return FetchError("repository metadata was not found")
    if status == 429:
        return FetchError("GitHub API rate limit was exhausted")
    if 500 <= status <= 599:
        return FetchError("GitHub API is unavailable")
    return FetchError("GitHub API request failed")


def _read_response(response: Any) -> bytes:
    raw_length = response.headers.get("Content-Length")
    if raw_length is not None:
        try:
            content_length = int(raw_length, 10)
        except (TypeError, ValueError) as exc:
            raise FetchError("GitHub API returned invalid response metadata") from exc
        if content_length < 0 or content_length > MAX_HTTP_BYTES:
            raise FetchError("GitHub API response exceeded the size limit")

    payload = response.read(MAX_HTTP_BYTES + 1)
    if len(payload) > MAX_HTTP_BYTES:
        raise FetchError("GitHub API response exceeded the size limit")
    return payload


def fetch_star_count(token: str, opener: Any | None = None) -> int:
    if not token or len(token) > 4_096 or "\r" in token or "\n" in token:
        raise FetchError("GITHUB_TOKEN is missing or invalid")

    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Repository-Star-History-Fetcher",
            "X-GitHub-Api-Version": API_VERSION,
        },
        method="GET",
    )
    client = opener or _build_opener()
    try:
        response = client.open(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise _status_error(status) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise FetchError("GitHub API network request failed") from None
    except Exception:
        raise FetchError("GitHub API request could not be started") from None

    try:
        with response:
            if response.geturl() != API_URL:
                raise FetchError("GitHub API redirect was refused")
            status = response.getcode()
            if status != 200:
                raise _status_error(status)
            payload = _read_response(response)
    except FetchError:
        raise
    except (TimeoutError, OSError):
        raise FetchError("GitHub API response could not be read") from None
    except Exception:
        raise FetchError("GitHub API response could not be processed") from None

    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise FetchError("GitHub API returned malformed JSON") from None
    if not isinstance(document, dict):
        raise FetchError("GitHub API response had an unexpected shape")

    count = document.get("stargazers_count")
    if type(count) is not int or count < 0:
        raise FetchError("GitHub API returned an invalid stargazers_count")
    return count


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print("error: this command accepts no arguments", file=sys.stderr)
        return 2

    try:
        count = fetch_star_count(os.environ.get("GITHUB_TOKEN", ""))
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("error: unexpected internal failure", file=sys.stderr)
        return 1

    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
