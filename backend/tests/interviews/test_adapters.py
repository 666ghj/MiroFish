import csv
import json
from pathlib import Path
from app.services.interviews.adapters import (
    FileSystemPersonaProvider, ZepMemoryProvider,
)

def _write_reddit_profiles(tmp_path: Path):
    data = [
        {"user_id": 0, "user_name": "fischer1", "name": "Fischer Müller",
         "persona": "I am a small-scale Baltic fisher.", "profession": "fisher", "bio": ""},
        {"user_id": 1, "user_name": "ngo1", "name": "Ines NGO",
         "persona": "I work for an environmental NGO.", "profession": "ngo_staff", "bio": ""},
    ]
    p = tmp_path / "reddit_profiles.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p

def test_file_system_persona_provider_reads_reddit_json(tmp_path):
    p = _write_reddit_profiles(tmp_path)
    provider = FileSystemPersonaProvider(reddit_path=p, twitter_path=None)
    personas = provider.all()
    assert len(personas) == 2
    assert personas[0].name == "Fischer Müller"
    assert personas[0].agent_id == 0

def test_zep_memory_provider_returns_empty_when_unavailable():
    class _BrokenReader:
        def get_entity_with_context(self, *a, **kw):
            raise RuntimeError("offline")
    prov = ZepMemoryProvider(entity_reader=_BrokenReader(), graph_id="g1",
                             agent_to_entity={0: "uuid-zero"})
    d = prov.get_digest(0)
    assert d.available is False
    assert d.text != ""

def test_zep_memory_provider_truncates_to_max_chars():
    class _R:
        def get_entity_with_context(self, *a, **kw):
            class _Ctx:
                name = "X"; summary = "Y"
                related_edges = [{"fact": "very long fact " * 200}]
            return _Ctx()
    prov = ZepMemoryProvider(entity_reader=_R(), graph_id="g1",
                             agent_to_entity={5: "uuid-five"})
    d = prov.get_digest(5, max_chars=300)
    assert d.available is True
    assert len(d.text) <= 300
