from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode


def _entity(name, labels):
    return EntityNode(
        uuid=f"uuid-{name}",
        name=name,
        labels=labels,
        summary=f"{name} summary",
        attributes={},
    )


def test_agent_persona_filter_keeps_only_person_entities_by_default():
    entities = [
        _entity("Alice", ["Entity", "Person"]),
        _entity("MiroFish", ["Entity", "Company"]),
        _entity("market event", ["Entity", "Topic"]),
        _entity("Bob", ["Entity", "PublicFigure"]),
        _entity("raw fragment", ["Entity"]),
    ]

    filtered = OasisProfileGenerator.filter_agent_persona_entities(entities)

    assert [entity.name for entity in filtered] == ["Alice", "Bob"]


def test_agent_persona_filter_can_keep_group_accounts_when_requested():
    entities = [
        _entity("Alice", ["Entity", "Person"]),
        _entity("MiroFish", ["Entity", "Company"]),
        _entity("market event", ["Entity", "Topic"]),
    ]

    filtered = OasisProfileGenerator.filter_agent_persona_entities(
        entities,
        allow_group_accounts=True,
    )

    assert [entity.name for entity in filtered] == ["Alice", "MiroFish"]


def test_generate_profiles_from_entities_skips_non_person_entities(monkeypatch):
    entities = [
        _entity("Alice", ["Entity", "Person"]),
        _entity("MiroFish", ["Entity", "Company"]),
        _entity("market event", ["Entity", "Topic"]),
        _entity("Bob", ["Entity", "Person"]),
    ]
    generator = object.__new__(OasisProfileGenerator)
    generator.graph_id = None

    monkeypatch.setattr(generator, "_print_generated_profile", lambda *args: None)

    def generate_profile(entity, user_id, use_llm):
        return type(
            "Profile",
            (),
            {
                "name": entity.name,
                "user_id": user_id,
                "to_reddit_format": lambda self: {"name": self.name},
            },
        )()

    monkeypatch.setattr(generator, "generate_profile_from_entity", generate_profile)

    profiles = generator.generate_profiles_from_entities(
        entities,
        use_llm=False,
        parallel_count=1,
        allow_group_accounts=False,
    )

    assert [profile.name for profile in profiles] == ["Alice", "Bob"]
    assert [profile.user_id for profile in profiles] == [0, 1]
