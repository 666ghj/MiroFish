"""Tests for the gate-8 example extractor (scripts/extract_examples.py)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import extract_examples as ex  # noqa: E402

VARIANT_B = Path(__file__).resolve().parent.parent / "artifacts" / "v15" / "variant_B.json"


def _run_main(tmp_path, artifact_path):
    out = tmp_path / "examples.json"
    rc = ex.main(["--artifact", str(artifact_path), "--output", str(out)])
    return rc, out


def test_runs_on_variant_B_and_produces_output(tmp_path):
    rc, out = _run_main(tmp_path, VARIANT_B)
    assert rc == 0
    assert out.exists() and out.stat().st_size > 0
    report = json.loads(out.read_text())
    for cat in ex.REQUIRED:
        assert cat in report["categories"], f"missing category {cat}"
        body = report["categories"][cat]
        assert "examples" in body and "required" in body and "found" in body
        for e in body["examples"]:
            for field in ("fundamentals", "initial_view", "final_view", "reason"):
                assert field in e, f"{cat} example missing {field}"


def test_variant_B_satisfies_all_gate8_categories(tmp_path):
    report = ex.extract_examples(json.loads(VARIANT_B.read_text()))
    assert report["shortfalls"] == [], f"unexpected shortfalls: {report['shortfalls']}"
    for cat, req in ex.REQUIRED.items():
        assert len(report["categories"][cat]["examples"]) >= req, cat


def _minimal_artifact(missing_flips: bool) -> dict:
    """Tiny artifact; when missing_flips, r2 == r1 so no flips exist."""
    dd = ["CO1"]
    agents = [{"agent_id": i, "ticker": "CO1", "role": r, "tier": "deepdive"}
              for i, r in enumerate(["growth", "value", "contrarian",
                                     "quality", "risk", "ownership"])]
    r1 = {str(i): {"view": "neutral", "score": 5, "confidence": 0.5,
                   "thesis": "signal=0.00 lean=neutral", "note": "n",
                   "agent_id": i} for i in range(6)}
    r2 = r1 if missing_flips else {str(i): {"view": "bearish", "score": 3,
                                   "confidence": 0.5, "thesis": "signal=0.00",
                                   "note": "n", "agent_id": i,
                                   "revision_reason": "peer majority"} for i in range(6)}
    return {
        "meta": {"variant": "B", "agent_count": 6, "tier_meta": {"deepdive_tickers": dd}},
        "rounds": {"r1": r1, "r2": r2},
        "company_consensus": {"CO1": {"view": "bearish", "score": 3,
                                      "confidence": 0.5, "winner_agent_id": 0,
                                      "n": 6, "agents": [{"agent_id": i,
                                                          "view": "bearish"} for i in range(6)]}},
        "agents": agents,
    }


def test_does_not_crash_on_missing_categories_and_notes_shortfall(tmp_path):
    art = _minimal_artifact(missing_flips=True)
    # no opposing roles (all neutral), no flips, no tie-break (unanimous), no screen
    report = ex.extract_examples(art)
    # must not raise; shortfalls recorded honestly
    assert report["shortfalls"], "expected shortfalls on a near-empty artifact"
    for cat in ex.REQUIRED:
        body = report["categories"][cat]
        assert body["found"] == len(body["examples"])  # never fabricated
    # write via main to confirm the runnable path does not crash either
    p = tmp_path / "art.json"
    p.write_text(json.dumps(art))
    out = tmp_path / "out.json"
    rc = ex.main(["--artifact", str(p), "--output", str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 0
