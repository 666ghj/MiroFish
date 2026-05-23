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


def test_agent_to_entity_from_reddit_json(tmp_path):
    """C5: ``FileSystemPersonaProvider.agent_to_entity()`` must reconstruct the
    ``{agent_id: zep_entity_uuid}`` map from a reddit_profiles.json that
    includes ``source_entity_uuid``.
    """
    data = [
        {"user_id": 0, "user_name": "fischer1", "name": "Fischer Müller",
         "persona": "p", "profession": "fisher",
         "source_entity_uuid": "uuid-zero"},
        {"user_id": 1, "user_name": "ngo1", "name": "Ines NGO",
         "persona": "p", "profession": "ngo_staff",
         "source_entity_uuid": "uuid-one"},
        # Row with no uuid must be skipped.
        {"user_id": 2, "user_name": "gov1", "name": "Gov Agent",
         "persona": "p", "profession": "official"},
    ]
    p = tmp_path / "reddit_profiles.json"
    p.write_text(json.dumps(data), encoding="utf-8")

    provider = FileSystemPersonaProvider(reddit_path=p, twitter_path=None)
    mapping = provider.agent_to_entity()

    assert mapping == {0: "uuid-zero", 1: "uuid-one"}
    # Map values are strings, keys are ints.
    for k, v in mapping.items():
        assert isinstance(k, int)
        assert isinstance(v, str)


def test_agent_to_entity_empty_when_no_field(tmp_path):
    """C5: if no row has ``source_entity_uuid``, return an empty dict — not
    a crash, not partial garbage."""
    data = [{"user_id": 0, "user_name": "u", "name": "A", "persona": "p"}]
    p = tmp_path / "reddit_profiles.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    provider = FileSystemPersonaProvider(reddit_path=p, twitter_path=None)
    assert provider.agent_to_entity() == {}


def test_agent_to_entity_falls_back_to_twitter_csv(tmp_path):
    """C5: when only twitter_profiles.csv exists, the helper must still
    extract uuids from the CSV's ``source_entity_uuid`` column.
    """
    p = tmp_path / "twitter_profiles.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "name", "username", "user_char", "description", "source_entity_uuid"])
        writer.writerow([0, "A0", "u0", "char", "desc", "uuid-zero"])
        writer.writerow([1, "A1", "u1", "char", "desc", ""])  # skipped (blank uuid)
        writer.writerow([2, "A2", "u2", "char", "desc", "uuid-two"])

    provider = FileSystemPersonaProvider(reddit_path=None, twitter_path=p)
    assert provider.agent_to_entity() == {0: "uuid-zero", 2: "uuid-two"}


def test_agent_to_entity_reddit_takes_precedence(tmp_path):
    """C5: when both files exist, Reddit JSON wins; Twitter CSV only fills
    agents not already mapped."""
    reddit = tmp_path / "reddit_profiles.json"
    reddit.write_text(json.dumps([
        {"user_id": 0, "user_name": "u0", "name": "A0", "persona": "p",
         "source_entity_uuid": "reddit-zero"},
    ]), encoding="utf-8")

    twitter = tmp_path / "twitter_profiles.csv"
    with twitter.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "name", "username", "user_char", "description", "source_entity_uuid"])
        writer.writerow([0, "A0", "u0", "char", "desc", "twitter-zero"])  # ignored
        writer.writerow([1, "A1", "u1", "char", "desc", "twitter-one"])  # used

    provider = FileSystemPersonaProvider(reddit_path=reddit, twitter_path=twitter)
    assert provider.agent_to_entity() == {0: "reddit-zero", 1: "twitter-one"}
