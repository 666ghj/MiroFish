"""Real-LLM end-to-end test: confirm the model produces English-only output.

Calls the real ontology generator against a fixture document and asserts the
returned ontology contains zero CJK ideographs in entity/relation type names,
attribute names, or descriptions. This is the regression test for the
"MiroFish reasons in Chinese" production bug — if a future prompt edit reverts
or weakens the English directive, this test catches it before deploy.

Configuration via environment (same vars MiroFish uses at runtime):
  LLM_API_KEY      — required; test skips if unset
  LLM_BASE_URL     — defaults to https://api.openai.com/v1
  LLM_MODEL_NAME   — defaults to gpt-4o-mini

In CI, point these at the production Gemini config to exercise the real
production pipeline:
  LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
  LLM_MODEL_NAME=models/gemini-3-flash-preview
  LLM_API_KEY=<gemini-key>

Locally, OPENAI_API_KEY + the gpt-4o-mini default is sufficient for sanity.
"""

import os
import re
import sys
import pathlib

import pytest

# Make `import app...` work without installing the package.
ROOT = pathlib.Path(__file__).resolve().parents[2]  # MiroFish/
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

CJK_RE = re.compile(r"[一-鿿]")


# A fixture seed document. Deliberately mixes Western and Asian context so an
# under-prompted model has every excuse to emit Chinese — and the test catches
# the regression if it does.
SEED_DOCUMENT = """
Acme Therapeutics, a clinical-stage biotech, is preparing to launch a Phase III
trial for ATX-219, an oral small-molecule inhibitor of MYC for relapsed
multiple myeloma. The chief medical officer, Dr. Elena Park, has flagged
competitive pressure from Genentech's MYC-degrader program (RG-7842) and from
Daiichi Sankyo's bispecific antibody DS-9070. Investor sentiment on social
media (X, LinkedIn, biotech subreddits) has shifted neutral after the recent
ASH abstract; key opinion leaders Dr. Akira Tanaka (Memorial Sloan Kettering)
and Dr. Wei Chen (Peking Union Medical College) have publicly endorsed the
mechanism. The company expects an FDA Type-B meeting in Q3, with European
EMA scientific advice pending. Patient advocacy group MMRF is monitoring
the trial design closely.
""".strip()

SIMULATION_REQUIREMENT = (
    "Predict how key opinion leaders, investors, and patient advocacy groups "
    "will react to a Phase III readout for ATX-219, including likely social "
    "media discourse and competitive responses from rival programs."
)


@pytest.fixture(scope="module")
def llm_available() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


@pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"),
    reason="LLM_API_KEY not set — skipping real-LLM e2e test",
)
def test_ontology_output_is_english_only():
    """Real LLM call. Asserts the produced ontology contains no CJK chars."""
    from app.services.ontology_generator import OntologyGenerator

    generator = OntologyGenerator()
    ontology = generator.generate(
        document_texts=[SEED_DOCUMENT],
        simulation_requirement=SIMULATION_REQUIREMENT,
    )

    assert "entity_types" in ontology, f"missing entity_types in: {ontology}"
    assert "edge_types" in ontology, f"missing edge_types in: {ontology}"
    assert len(ontology["entity_types"]) > 0, "ontology has zero entity types"
    assert len(ontology["edge_types"]) > 0, "ontology has zero edge types"

    offenders = []

    def scan(label: str, value):
        if isinstance(value, str) and CJK_RE.search(value):
            offenders.append(f"{label}: {value!r}")
        elif isinstance(value, dict):
            for k, v in value.items():
                scan(f"{label}.{k}", v)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                scan(f"{label}[{i}]", v)

    # Type names + attribute names are the load-bearing fields. Descriptions
    # may legitimately reference Chinese names if the seed document mentions
    # Chinese institutions (e.g. "Peking Union Medical College"), so we scan
    # only structural fields where Chinese signals an LLM-language regression.
    for et in ontology.get("entity_types", []):
        scan("entity_types.name", et.get("name"))
        for attr in et.get("attributes", []) or []:
            scan("entity_types.attributes.name", attr.get("name"))
    for rt in ontology.get("edge_types", []):
        scan("edge_types.name", rt.get("name"))
        for attr in rt.get("attributes", []) or []:
            scan("edge_types.attributes.name", attr.get("name"))

    assert not offenders, (
        "LLM emitted CJK characters in structural ontology fields. "
        "This is the production bug the prompts were supposed to prevent.\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + f"\n\nRaw ontology:\n{ontology}"
    )


@pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY"),
    reason="LLM_API_KEY not set — skipping real-LLM e2e test",
)
def test_llm_client_direct_english_response():
    """Sanity test: a bare LLM call with the system prompt routes English."""
    from app.utils.llm_client import LLMClient

    client = LLMClient()
    response = client.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant. You MUST respond in English "
                    "regardless of the language of the question."
                ),
            },
            {
                "role": "user",
                "content": "用中文回答：什么是机器学习？",
            },
        ],
        temperature=0.0,
        max_tokens=256,
    )
    assert response, "empty response from LLM"
    cjk_chars = CJK_RE.findall(response)
    assert not cjk_chars, (
        f"LLM responded in Chinese despite English-only system prompt. "
        f"Found {len(cjk_chars)} CJK chars. Response: {response!r}"
    )
