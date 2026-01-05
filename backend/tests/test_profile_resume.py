import json
import random

from app.config import Config
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode


def test_profile_generation_resumes_from_existing_realtime_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-4o-mini")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)

    sim_dir = tmp_path / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    profiles_path = sim_dir / "reddit_profiles.json"

    profiles_path.write_text(
        json.dumps(
            [
                {
                    "user_id": 0,
                    "username": "u0",
                    "name": "A",
                    "bio": "bio0",
                    "persona": "p0",
                    "karma": 1000,
                    "created_at": "2026-01-01",
                },
                {
                    "user_id": 2,
                    "username": "u2",
                    "name": "C",
                    "bio": "bio2",
                    "persona": "p2",
                    "karma": 1000,
                    "created_at": "2026-01-01",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    entities = [
        EntityNode(uuid="e0", name="A", labels=["Entity", "Person"], summary="s0", attributes={}),
        EntityNode(uuid="e1", name="B", labels=["Entity", "Person"], summary="s1", attributes={}),
        EntityNode(uuid="e2", name="C", labels=["Entity", "Person"], summary="s2", attributes={}),
    ]

    random.seed(0)
    gen = OasisProfileGenerator(graph_id=None)
    profiles = gen.generate_profiles_from_entities(
        entities=entities,
        use_llm=False,
        parallel_count=1,
        realtime_output_path=str(profiles_path),
        output_platform="reddit",
    )

    assert len(profiles) == 3
    assert profiles[0].user_name == "u0"
    assert profiles[2].user_name == "u2"
    assert profiles[1].user_id == 1

    saved = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert sorted([p["user_id"] for p in saved]) == [0, 1, 2]

