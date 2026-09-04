"""Preflight the extraction path a graph build is about to depend on.

Two production builds died on the same class of failure and neither one said so
until it had burned most of an hour. One finished with ``failed_items=1`` and an
``APITimeoutError`` after ~50 minutes; the other, after the operator lowered
``GRAPHITI_LLM_MAX_TOKENS`` to 4096, finished with ``failed_items=4`` and a
``JSONDecodeError`` at character 4148 - one character per completion token,
which is a model emitting a runaway list of integers into an unbounded array
until the token budget cuts the JSON in half.

The check is an HTTP call into the Zep-compatible service rather than something
this process runs itself, and that is the whole point: ``grep -rn "GRAPHITI_"
backend/ --include=*.py`` finds nothing outside tests. Every knob that produced
both failures - the token budget, the structured-output mode, the request
timeout, the model itself - lives in that other process. A copy of the check
written here would exercise the backend's own LLM config with no
``response_format`` at all, pass green, and the build would still die.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from ..config import Config
from ..utils.logger import get_logger
from ..utils.zep import ZEP_CLOUD_BASE_URL, resolve_zep_base_url

logger = get_logger('sosim.graph_preflight')

# One real structured extraction, not a ping: a prompt of a few hundred tokens
# plus however long the model takes to emit its answer. Generous enough that a
# healthy but slow local box passes, short enough that a misconfigured one is
# rejected in minutes rather than the ~50 the real build took to die.
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 180.0

# The sample is a chunk of the project's own text, so the check sees the same
# prose distribution the ingest will. This is only the fallback for a project
# whose text could not be read: ordinary sentences with a handful of obvious
# entities and relations, so the extraction has something real to return.
DEFAULT_PREFLIGHT_SAMPLE_TEXT = (
    "Maria Alvarez, the operations lead at Northwind Logistics, met Daniel Osei "
    "of Harbor Freight in Rotterdam on 12 March to renegotiate the winter "
    "haulage contract. Northwind agreed to take over two of Harbor Freight's "
    "northern routes, and Daniel asked for the revised terms before Friday."
)

# Roughly one ingest chunk. Long enough to be representative, short enough that
# a failure is quick.
MAX_PREFLIGHT_SAMPLE_CHARS = 1200

# An older Zep-compatible service has no preflight route. It answers 404, or
# 405 when its own ``GET /graph/{graph_id}`` claims the path and only the method
# fails to match. Neither means the build is misconfigured, so neither may fail
# the request.
ENDPOINT_ABSENT_STATUSES = frozenset({404, 405})

# A 404 is also exactly what a ZEP_BASE_URL pointing at the wrong host answers,
# for every path - the single most common misconfiguration this check exists to
# catch. So a 404 is only read as "the route is absent" once the service has
# proved it is answering at all. The batch listing is what the ingest itself
# runs on and predates the preflight route, so a base URL that cannot serve it
# could not have served the build either.
ENDPOINT_PRESENCE_PROBE_PATH = "/batches"

# Reported straight back to the caller so a failure names the numbers that
# caused it rather than just "the build died".
REPORT_FIELDS = (
    "finish_reason",
    "completion_tokens",
    "max_tokens",
    "structured_output_mode",
    "elapsed_seconds",
)


@dataclass(frozen=True)
class GraphPreflightResult:
    """What one preflight attempt concluded.

    ``skipped`` separates "there was nothing to check here" from "the check
    passed": a skip is a warning the operator should see, not a green light
    anyone should quote as evidence the endpoint is healthy.
    """

    ok: bool
    detail: str
    skipped: bool = False
    report: Optional[Dict[str, Any]] = None


def preflight_timeout_seconds() -> float:
    """Read the preflight request budget, in seconds."""

    try:
        value = float(
            os.environ.get("GRAPH_BUILD_PREFLIGHT_TIMEOUT")
            or DEFAULT_PREFLIGHT_TIMEOUT_SECONDS
        )
    except ValueError:
        return DEFAULT_PREFLIGHT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_PREFLIGHT_TIMEOUT_SECONDS


def preflight_skipped_by_environment() -> bool:
    """Report whether the deployment has switched the preflight off."""

    return (os.environ.get("GRAPH_BUILD_SKIP_PREFLIGHT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_sample_text(source_text: Optional[str]) -> str:
    """Return a short paragraph of the project's own prose to extract from."""

    sample = (source_text or "").strip()[:MAX_PREFLIGHT_SAMPLE_CHARS].strip()
    return sample or DEFAULT_PREFLIGHT_SAMPLE_TEXT


def _describe(detail: str, report: Dict[str, Any]) -> str:
    """Append the numbers behind a verdict to the service's own message."""

    measured = ", ".join(
        f"{field}={report[field]}"
        for field in REPORT_FIELDS
        if report.get(field) is not None
    )
    if not measured:
        return detail
    return f"{detail} ({measured})" if detail else measured


def _probe_endpoint_present(
    base_url: str,
    headers: Dict[str, str],
    timeout: float,
) -> tuple[Optional[bool], str]:
    """Report whether ZEP_BASE_URL is answering as a Zep-compatible service.

    Returns True (answering), False (definitively not a Zep service) or None
    (could not tell - treat as benign; see the transport-error branch).
    """

    url = f"{base_url.rstrip('/')}{ENDPOINT_PRESENCE_PROBE_PATH}"
    try:
        response = httpx.get(
            url, params={"limit": 1}, headers=headers, timeout=timeout
        )
    except Exception as error:
        # Undetermined, NOT absent. This probe only runs after the preflight
        # route itself answered 404/405, so the service demonstrably took a
        # request moments ago; a transport failure here is far more likely to
        # be a blip than proof that ZEP_BASE_URL is wrong. Failing the build on
        # that evidence would block a healthy install, so fall back to the
        # benign reading (an older shim) and let the build proceed.
        return None, f"{type(error).__name__} calling {url}: {error}"
    if response.status_code in ENDPOINT_ABSENT_STATUSES:
        return False, f"{url} answered HTTP {response.status_code} too"
    return True, f"{url} answered HTTP {response.status_code}"


def run_graph_preflight(
    ontology: Optional[Dict[str, Any]],
    source_text: Optional[str] = None,
) -> GraphPreflightResult:
    """Run one real extraction through the service that will do the ingest.

    The ontology is passed in rather than read from the store because the
    common case is a graph that does not exist yet: the first build of a
    project has nothing on the server to read an ontology from.

    Args:
        ontology: The project ontology, as ``{entity_types, edge_types}``.
        source_text: The text about to be ingested; a slice of it is the sample.

    Returns:
        GraphPreflightResult: the verdict, a human-readable reason, and the
        numbers the service measured.
    """

    if preflight_skipped_by_environment():
        return GraphPreflightResult(
            ok=True,
            detail="GRAPH_BUILD_SKIP_PREFLIGHT is set",
            skipped=True,
        )

    base_url = resolve_zep_base_url()
    if base_url == ZEP_CLOUD_BASE_URL:
        # Bail out before the request rather than relying on the 404 handling
        # below: Zep Cloud has no such route, none of the knobs this checks are
        # its to answer for, and a slice of the project's documents has no
        # business being posted at an endpoint that does not exist.
        return GraphPreflightResult(
            ok=True,
            detail=(
                "ZEP_BASE_URL is unset, so ingestion runs on Zep Cloud, which "
                "owns its own extraction budget and exposes no preflight"
            ),
            skipped=True,
        )

    url = f"{base_url.rstrip('/')}/graph/preflight"
    payload = {
        "entity_types": (ontology or {}).get("entity_types"),
        "edge_types": (ontology or {}).get("edge_types"),
        "sample_text": build_sample_text(source_text),
    }
    headers = {}
    if Config.ZEP_API_KEY:
        headers["Authorization"] = f"Api-Key {Config.ZEP_API_KEY}"

    timeout = preflight_timeout_seconds()
    started = time.time()
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except Exception as error:
        elapsed = time.time() - started
        # Name the exception type: a connection refused, a read timeout and a
        # DNS failure each call for a different fix.
        return GraphPreflightResult(
            ok=False,
            detail=(
                f"{type(error).__name__} after {elapsed:.1f}s calling {url}: "
                f"{error}. The service ZEP_BASE_URL names is not answering, so "
                f"the ingest would fail on its first episode. Raise "
                f"GRAPH_BUILD_PREFLIGHT_TIMEOUT (currently {timeout:.0f}s) only "
                f"if the endpoint is merely slow."
            ),
        )

    if response.status_code in ENDPOINT_ABSENT_STATUSES:
        answering, probe_detail = _probe_endpoint_present(
            base_url, headers, timeout
        )
        if answering is False:
            return GraphPreflightResult(
                ok=False,
                detail=(
                    f"{url} answered HTTP {response.status_code}, and the "
                    f"batch API the ingest runs on is no better: "
                    f"{probe_detail}. ZEP_BASE_URL does not point at a "
                    f"Zep-compatible service, so the build would fail on its "
                    f"first batch."
                ),
            )
        return GraphPreflightResult(
            ok=True,
            detail=(
                f"{url} answered HTTP {response.status_code} while "
                f"{probe_detail}; this Zep-compatible service predates the "
                f"preflight endpoint, so the extraction configuration was not "
                f"checked"
            ),
            skipped=True,
        )

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code >= 400:
        served = body.get("detail") if isinstance(body, dict) else None
        return GraphPreflightResult(
            ok=False,
            detail=(
                f"HTTP {response.status_code} from {url}: "
                f"{served or response.text[:400] or 'no body'}"
            ),
        )

    if not isinstance(body, dict) or "ok" not in body:
        # A 200 that does not answer the question is a version mismatch, not
        # evidence of a broken build. Warn and let the build run.
        return GraphPreflightResult(
            ok=True,
            detail=(
                f"{url} answered HTTP {response.status_code} with a body this "
                f"build does not understand, so the extraction configuration "
                f"was not checked"
            ),
            skipped=True,
        )

    report = {field: body.get(field) for field in REPORT_FIELDS}
    detail = _describe(str(body.get("detail") or "").strip(), report)
    if body.get("ok"):
        return GraphPreflightResult(
            ok=True,
            detail=detail or "the extraction endpoint answered cleanly",
            report=report,
        )
    return GraphPreflightResult(
        ok=False,
        detail=detail or "the extraction endpoint rejected the sample",
        report=report,
    )
