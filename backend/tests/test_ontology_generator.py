from app.services.ontology_generator import OntologyGenerator


class RecordingLLMClient:
    def __init__(self):
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "entity_types": [],
            "edge_types": [],
            "analysis_summary": "ok",
        }


def _generator_for_test() -> OntologyGenerator:
    generator = OntologyGenerator(llm_client=object())
    generator.MAX_TEXT_LENGTH_FOR_LLM = 2000
    generator.LONG_TEXT_CHUNK_SIZE = 500
    generator.LONG_TEXT_CHUNK_OVERLAP = 0
    generator.MAX_LONG_TEXT_CHUNKS = 3
    generator.MIN_LONG_TEXT_EXCERPT = 120
    return generator


def test_short_ontology_context_keeps_original_text():
    generator = _generator_for_test()

    context = generator._build_document_context(["short document body"])

    assert context == "short document body"
    assert "长文本自动分块摘要" not in context


def test_long_ontology_context_samples_across_document():
    generator = _generator_for_test()
    long_text = "BEGIN" + ("a" * 1050) + "MIDDLE" + ("b" * 1050) + "END"

    context = generator._build_document_context([long_text])

    assert len(context) <= generator.MAX_TEXT_LENGTH_FOR_LLM
    assert "长文本自动分块摘要" in context
    assert "BEGIN" in context
    assert "MIDDLE" in context
    assert "END" in context
    assert "分块 1/" in context
    assert "分块 3/" in context
    assert "分块 5/" in context


def test_very_long_ontology_context_selects_representative_chunks():
    generator = _generator_for_test()
    chunks = ["BEGIN"] + [
        f"CHUNK{i:02d}-" + (str(i) * 490)
        for i in range(12)
    ] + ["FINALEND"]
    long_text = "".join(chunks)

    context = generator._build_document_context([long_text])

    assert len(context) <= generator.MAX_TEXT_LENGTH_FOR_LLM
    assert "BEGIN" in context
    assert "FINALEND" in context
    assert context.count("--- 文档 1 / 分块") == generator.MAX_LONG_TEXT_CHUNKS


def test_ontology_generation_does_not_cap_structured_output_tokens():
    llm = RecordingLLMClient()
    generator = OntologyGenerator(llm_client=llm)

    result = generator.generate(
        document_texts=["A short source document."],
        simulation_requirement="Simulate the public discussion.",
    )

    assert result["analysis_summary"] == "ok"
    assert llm.calls[0]["max_tokens"] is None
    assert llm.calls[0]["max_attempts"] == 2


def test_entity_cap_preserves_an_existing_person_fallback_and_its_edges():
    generator = _generator_for_test()
    person = {"name": "Person", "description": "Original person description"}
    result = generator._validate_and_process({
        "entity_types": [{"name": f"Type{i}"} for i in range(9)] + [person],
        "edge_types": [{
            "name": "WORKS_FOR",
            "source_targets": [{"source": "Person", "target": "Organization"}],
        }],
    })

    entities = {entity["name"]: entity for entity in result["entity_types"]}
    assert len(entities) == 10
    assert {"Person", "Organization"} <= entities.keys()
    assert entities["Person"]["description"] == person["description"]
    assert result["edge_types"][0]["source_targets"] == [
        {"source": "Person", "target": "Organization"}
    ]
    assert "Type7" in entities
    assert "Type8" not in entities


def test_entity_cap_preserves_both_existing_fallbacks_beyond_the_cap():
    generator = _generator_for_test()
    result = generator._validate_and_process({
        "entity_types": [{"name": f"Type{i}"} for i in range(10)] + [
            {"name": "Person"}, {"name": "Organization"},
        ],
        "edge_types": [],
    })

    assert [entity["name"] for entity in result["entity_types"]] == [
        *[f"Type{i}" for i in range(8)], "Person", "Organization",
    ]


def test_entity_cap_preserves_an_existing_organization_fallback():
    generator = _generator_for_test()
    result = generator._validate_and_process({
        "entity_types": [{"name": f"Type{i}"} for i in range(9)] + [
            {"name": "Organization"},
        ],
        "edge_types": [],
    })

    names = [entity["name"] for entity in result["entity_types"]]
    assert len(names) == 10
    assert names[-2:] == ["Organization", "Person"]


def test_entity_cap_adds_missing_fallbacks_without_changing_specific_type_order():
    generator = _generator_for_test()
    result = generator._validate_and_process({
        "entity_types": [{"name": f"Type{i}"} for i in range(11)],
        "edge_types": [],
    })

    assert [entity["name"] for entity in result["entity_types"]] == [
        *[f"Type{i}" for i in range(8)], "Person", "Organization",
    ]


def test_entity_cap_keeps_existing_types_unchanged_when_they_fit():
    generator = _generator_for_test()
    result = generator._validate_and_process({
        "entity_types": [{"name": "Person"}, {"name": "Company"},
                         {"name": "Organization"}],
        "edge_types": [],
    })

    assert [entity["name"] for entity in result["entity_types"]] == [
        "Person", "Company", "Organization",
    ]
