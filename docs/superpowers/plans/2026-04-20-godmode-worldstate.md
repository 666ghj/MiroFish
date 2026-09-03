# God Mode + World State v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 3 God Mode interventions (inject event, modify emotion, kill character) + 3 World State primitives (locations, rules, event log) layered on top of the existing Narrative Layer.

**Architecture:** New `world_state.py` (CRUD) and `god_mode.py` (handlers) services. Extend `narrative_translator.py` prompt with 3 new fields. Extend `translate_round` to load world state and filter dead characters. 6 new API endpoints. 2 new Vue views with shared nav.

**Tech Stack:** Python 3.12, Flask, Vue 3 + Vite, existing LLM client. Builds on committed feat/narrative-layer branch.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `backend/app/services/narrative/world_state.py` | WorldStateStore class + CRUD helpers for world_state.json |
| `backend/app/services/narrative/god_mode.py` | inject_event(), modify_emotion(), kill_character() handlers |
| `backend/tests/test_world_state.py` | Unit tests for world CRUD |
| `backend/tests/test_god_mode.py` | Unit tests for interventions |
| `frontend/src/views/GodModeView.vue` | 3 action forms |
| `frontend/src/views/WorldBuilderView.vue` | Rules + locations + event log UI |

### Modified files

| File | Change |
|---|---|
| `backend/app/services/narrative/character_engine.py` | `create_initial_character()` sets `status: "alive"` |
| `backend/app/services/narrative/narrative_translator.py` | Prompt adds 3 world fields, `translate_round` loads world, filters dead chars, resolves locations, brace-escapes user text |
| `backend/app/api/narrative.py` | +6 endpoints |
| `backend/tests/test_narrative_translator.py` | +prompt inclusion test |
| `backend/tests/test_narrative_e2e.py` | +event injection + kill integration scenarios |
| `frontend/src/api/narrative.js` | +6 named exports |
| `frontend/src/router/index.js` | +2 routes |
| `frontend/src/views/StoryTimelineView.vue` | Add shared SimNav strip |

---

## Task 1: WorldStateStore — CRUD for world_state.json

**Files:**
- Create: `backend/app/services/narrative/world_state.py`
- Create: `backend/tests/test_world_state.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_world_state.py`:

```python
import os
import tempfile
import pytest
from app.services.narrative.world_state import WorldStateStore


@pytest.fixture
def temp_sim_dir():
    with tempfile.TemporaryDirectory() as d:
        sim_dir = os.path.join(d, "sim_test")
        os.makedirs(sim_dir)
        yield sim_dir


def test_load_returns_empty_world_when_missing(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    world = store.load()
    assert world == {"rules": [], "locations": {}, "event_log": []}


def test_set_rules_replaces_previous(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    store.set_rules(["rule 1", "rule 2"])
    assert store.load()["rules"] == ["rule 1", "rule 2"]
    store.set_rules(["only rule"])
    assert store.load()["rules"] == ["only rule"]


def test_upsert_location_adds_and_updates(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    store.upsert_location({"id": "tower", "name": "The Tower", "description": "tall"})
    assert store.load()["locations"]["tower"]["name"] == "The Tower"

    # Update same id
    store.upsert_location({"id": "tower", "name": "The Iron Tower", "description": "dark"})
    assert store.load()["locations"]["tower"]["name"] == "The Iron Tower"


def test_append_event_auto_ids_sequentially(temp_sim_dir):
    store = WorldStateStore(temp_sim_dir)
    e1 = store.append_event({"type": "custom", "description": "one", "round": 1})
    e2 = store.append_event({"type": "custom", "description": "two", "round": 2})

    assert e1["id"] == "evt_1"
    assert e2["id"] == "evt_2"
    assert store.load()["event_log"][-1]["description"] == "two"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/test_world_state.py -v
```
Expected: ImportError — module not created yet.

- [ ] **Step 3: Implement world_state.py**

Create `backend/app/services/narrative/world_state.py`:

```python
"""World state CRUD: rules, locations, event log.

Stored in narrative/world_state.json. Missing file is treated as an empty
world so existing simulations (from pre-God-Mode versions) continue to work
without migration.
"""
import os
import json
from typing import Optional


EMPTY_WORLD = {"rules": [], "locations": {}, "event_log": []}


class WorldStateStore:
    """Manages narrative/world_state.json for a single simulation."""

    def __init__(self, sim_dir: str):
        self.sim_dir = sim_dir
        self.narrative_dir = os.path.join(sim_dir, "narrative")
        self.path = os.path.join(self.narrative_dir, "world_state.json")

    def _ensure_dir(self) -> None:
        os.makedirs(self.narrative_dir, exist_ok=True)

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return dict(EMPTY_WORLD, rules=[], locations={}, event_log=[])
        with open(self.path, "r", encoding="utf-8") as f:
            world = json.load(f)
        # Fill in missing keys for forward compatibility
        world.setdefault("rules", [])
        world.setdefault("locations", {})
        world.setdefault("event_log", [])
        return world

    def save(self, world: dict) -> None:
        self._ensure_dir()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(world, f, ensure_ascii=False, indent=2)

    def set_rules(self, rules: list[str]) -> None:
        world = self.load()
        world["rules"] = list(rules)
        self.save(world)

    def upsert_location(self, location: dict) -> dict:
        """Insert or update a location by id. Returns the stored entry."""
        if "id" not in location:
            raise ValueError("location requires 'id'")
        world = self.load()
        world["locations"][location["id"]] = location
        self.save(world)
        return location

    def append_event(self, event: dict) -> dict:
        """Append an event to event_log, assigning evt_N id automatically."""
        world = self.load()
        event = dict(event)
        event["id"] = f"evt_{len(world['event_log']) + 1}"
        world["event_log"].append(event)
        self.save(world)
        return event
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_world_state.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/world_state.py backend/tests/test_world_state.py
git commit -m "feat(narrative): add WorldStateStore for rules, locations, and event log"
```

---

## Task 2: CharacterEngine — set `status: alive` on new characters

**Files:**
- Modify: `backend/app/services/narrative/character_engine.py`
- Modify: `backend/tests/test_character_engine.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_character_engine.py`:

```python
def test_create_initial_character_sets_status_alive():
    char = create_initial_character(char_id="x", name="X")
    assert char["status"] == "alive"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/test_character_engine.py::test_create_initial_character_sets_status_alive -v
```
Expected: FAIL — `status` key missing.

- [ ] **Step 3: Add status field**

Modify `backend/app/services/narrative/character_engine.py` in `create_initial_character`:

```python
    return {
        "id": char_id,
        "name": name,
        "backstory": backstory,
        "motivations": motivations or [],
        "personality_traits": personality or [],
        "status": "alive",                      # NEW
        "emotional_state": {
            "current": dict(INITIAL_EMOTIONAL_STATE),
            "history": [],
        },
        "relationships": {},
        "arc": {"archetype": None, "stage": "beginning", "key_moments": []},
    }
```

- [ ] **Step 4: Run full test suite to verify no regressions**

```bash
cd backend && uv run pytest tests/ -v
```
Expected: 21 passed (20 previous + 1 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/character_engine.py backend/tests/test_character_engine.py
git commit -m "feat(narrative): set status=alive on new characters"
```

---

## Task 3: God Mode — inject_event handler

**Files:**
- Create: `backend/app/services/narrative/god_mode.py`
- Create: `backend/tests/test_god_mode.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_god_mode.py`:

```python
import os
import tempfile
import pytest
from app.services.narrative.god_mode import inject_event
from app.services.narrative.story_store import StoryStore
from app.services.narrative.world_state import WorldStateStore


@pytest.fixture
def temp_sim_dir():
    with tempfile.TemporaryDirectory() as d:
        sim_dir = os.path.join(d, "sim_test")
        os.makedirs(sim_dir)
        yield sim_dir


def test_inject_event_appends_to_log(temp_sim_dir):
    evt = inject_event(temp_sim_dir, description="A storm arrives.", round_num=5)
    assert evt["description"] == "A storm arrives."
    assert evt["round"] == 5
    assert evt["id"] == "evt_1"
    assert evt["type"] == "god_mode_injection"

    log = WorldStateStore(temp_sim_dir).load()["event_log"]
    assert len(log) == 1


def test_inject_event_defaults_round_to_beats_plus_one(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    store.append_beat({"round": 3, "prose": "beat 3"})

    evt = inject_event(temp_sim_dir, description="auto round")
    assert evt["round"] == 4


def test_inject_event_defaults_round_to_one_when_no_beats(temp_sim_dir):
    evt = inject_event(temp_sim_dir, description="first event")
    assert evt["round"] == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/test_god_mode.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement god_mode.py (inject_event only)**

Create `backend/app/services/narrative/god_mode.py`:

```python
"""God Mode intervention handlers.

All handlers mutate on-disk JSON under narrative/ and return the result.
Each intervention is logged to world_state.event_log for auditability.
"""
from typing import Optional

from app.services.narrative.story_store import StoryStore
from app.services.narrative.world_state import WorldStateStore


def _current_round(sim_dir: str) -> int:
    """Return the 'current' round: last translated beat's round + 1, or 1."""
    beats = StoryStore(sim_dir).get_all_beats()
    if not beats:
        return 1
    return beats[-1].get("round", 0) + 1


def inject_event(sim_dir: str, description: str, round_num: Optional[int] = None) -> dict:
    """Append a user-described event to the world event log."""
    world = WorldStateStore(sim_dir)
    round_val = round_num if round_num is not None else _current_round(sim_dir)
    return world.append_event({
        "type": "god_mode_injection",
        "description": description,
        "round": round_val,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_god_mode.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/god_mode.py backend/tests/test_god_mode.py
git commit -m "feat(narrative): add god_mode.inject_event handler"
```

---

## Task 4: God Mode — modify_emotion handler

**Files:**
- Modify: `backend/app/services/narrative/god_mode.py`
- Modify: `backend/tests/test_god_mode.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_god_mode.py`:

```python
from app.services.narrative.god_mode import modify_emotion


def _seed_character(sim_dir, char_id="1", name="Elena"):
    store = StoryStore(sim_dir)
    neutral = {k: 0.0 for k in ["anger","fear","joy","sadness","surprise"]}
    store.save_characters([{
        "id": char_id, "name": name, "status": "alive",
        "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []},
    }])
    return store


def test_modify_emotion_overwrites_specified_emotions(temp_sim_dir):
    _seed_character(temp_sim_dir)
    result = modify_emotion(temp_sim_dir, "1", {"anger": 0.8, "joy": 0.2})

    assert result["emotional_state"]["current"]["anger"] == 0.8
    assert result["emotional_state"]["current"]["joy"] == 0.2
    # Unspecified emotion preserved
    assert result["emotional_state"]["current"]["trust"] == 0.5


def test_modify_emotion_clamps(temp_sim_dir):
    _seed_character(temp_sim_dir)
    result = modify_emotion(temp_sim_dir, "1", {"anger": 1.5, "fear": -0.3})
    assert result["emotional_state"]["current"]["anger"] == 1.0
    assert result["emotional_state"]["current"]["fear"] == 0.0


def test_modify_emotion_character_not_found_raises(temp_sim_dir):
    _seed_character(temp_sim_dir)
    with pytest.raises(ValueError, match="not found"):
        modify_emotion(temp_sim_dir, "nonexistent", {"anger": 0.5})


def test_modify_emotion_audit_logs_to_event_log(temp_sim_dir):
    _seed_character(temp_sim_dir)
    modify_emotion(temp_sim_dir, "1", {"anger": 0.8})

    log = WorldStateStore(temp_sim_dir).load()["event_log"]
    assert len(log) == 1
    assert log[0]["type"] == "god_mode_emotion_change"
    assert "Elena" in log[0]["description"]
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/test_god_mode.py -v
```
Expected: ImportError for `modify_emotion`.

- [ ] **Step 3: Implement modify_emotion**

Append to `backend/app/services/narrative/god_mode.py`:

```python
def modify_emotion(sim_dir: str, character_id: str, emotions: dict) -> dict:
    """Overwrite specified emotion values for a character. Clamps to [0,1]."""
    store = StoryStore(sim_dir)
    characters = store.load_characters()

    target = next((c for c in characters if str(c.get("id")) == str(character_id)), None)
    if target is None:
        raise ValueError(f"character not found: {character_id}")

    current = target["emotional_state"]["current"]
    changed = {}
    for emo, val in emotions.items():
        if emo in current:
            new_val = max(0.0, min(1.0, float(val)))
            changed[emo] = {"from": current[emo], "to": new_val}
            current[emo] = new_val

    store.save_characters(characters)

    # Audit log
    WorldStateStore(sim_dir).append_event({
        "type": "god_mode_emotion_change",
        "description": f"{target['name']} emotional state modified: {changed}",
        "round": _current_round(sim_dir),
    })

    return target
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_god_mode.py -v
```
Expected: 7 passed (3 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/god_mode.py backend/tests/test_god_mode.py
git commit -m "feat(narrative): add god_mode.modify_emotion with audit logging"
```

---

## Task 5: God Mode — kill_character handler

**Files:**
- Modify: `backend/app/services/narrative/god_mode.py`
- Modify: `backend/tests/test_god_mode.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_god_mode.py`:

```python
from app.services.narrative.god_mode import kill_character


def test_kill_character_sets_status_dead(temp_sim_dir):
    _seed_character(temp_sim_dir)
    result = kill_character(temp_sim_dir, "1")
    assert result["status"] == "dead"

    # Persisted
    chars = StoryStore(temp_sim_dir).load_characters()
    assert chars[0]["status"] == "dead"


def test_kill_character_auto_appends_death_event(temp_sim_dir):
    _seed_character(temp_sim_dir)
    kill_character(temp_sim_dir, "1")

    log = WorldStateStore(temp_sim_dir).load()["event_log"]
    death_events = [e for e in log if e["type"] == "god_mode_death"]
    assert len(death_events) == 1
    assert "Elena" in death_events[0]["description"]


def test_kill_character_not_found_raises(temp_sim_dir):
    _seed_character(temp_sim_dir)
    with pytest.raises(ValueError, match="not found"):
        kill_character(temp_sim_dir, "nonexistent")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/test_god_mode.py -v
```
Expected: ImportError for `kill_character`.

- [ ] **Step 3: Implement kill_character**

Append to `backend/app/services/narrative/god_mode.py`:

```python
def kill_character(sim_dir: str, character_id: str) -> dict:
    """Mark a character as dead and append a death event to the world log."""
    store = StoryStore(sim_dir)
    characters = store.load_characters()

    target = next((c for c in characters if str(c.get("id")) == str(character_id)), None)
    if target is None:
        raise ValueError(f"character not found: {character_id}")

    target["status"] = "dead"
    store.save_characters(characters)

    WorldStateStore(sim_dir).append_event({
        "type": "god_mode_death",
        "description": f"{target['name']} has died.",
        "round": _current_round(sim_dir),
    })

    return target
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_god_mode.py -v
```
Expected: 10 passed (7 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/god_mode.py backend/tests/test_god_mode.py
git commit -m "feat(narrative): add god_mode.kill_character with auto-death event"
```

---

## Task 6: Translator — load world_state, filter dead, extend prompt

**Files:**
- Modify: `backend/app/services/narrative/narrative_translator.py`
- Modify: `backend/tests/test_narrative_translator.py`

**🎯 Contains USER CONTRIBUTION POINT #1 (event enforcement strength) — paused in Step 5.**

- [ ] **Step 1: Write prompt-inclusion test**

Append to `backend/tests/test_narrative_translator.py`:

```python
def test_generate_prose_includes_world_context():
    actions = [{"agent_name": "Alice", "action_type": "CREATE_POST", "action_args": {}}]
    characters = [
        {"id": "1", "name": "Alice", "status": "alive", "location": "tower",
         "emotional_state": {"current": {"anger": 0, "fear": 0, "joy": 0,
                                          "sadness": 0, "trust": 0.5, "surprise": 0}}},
    ]
    world = {
        "rules": ["Magic is forbidden", "Winter is near"],
        "locations": {"tower": {"id": "tower", "name": "The Tower", "description": "tall"}},
        "event_log": [{"id": "evt_1", "round": 1, "type": "god_mode_injection",
                       "description": "A stranger arrived."}],
    }

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = "prose"
        generate_prose(actions, characters, tone="noir", previous_beats=[], world=world)

        prompt = mock_llm.call_args[0][0]
        assert "Magic is forbidden" in prompt
        assert "A stranger arrived" in prompt
        assert "The Tower" in prompt
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/test_narrative_translator.py::test_generate_prose_includes_world_context -v
```
Expected: FAIL — `generate_prose` doesn't accept `world` kwarg.

- [ ] **Step 3: Add brace-escape helper + world field formatters**

In `backend/app/services/narrative/narrative_translator.py`, add near the top (after imports):

```python
def _escape_braces(text: str) -> str:
    """Escape { and } in user-supplied strings before str.format()."""
    return text.replace("{", "{{").replace("}", "}}")


def _format_world_rules(world: dict) -> str:
    rules = world.get("rules", [])
    if not rules:
        return "(none)"
    return "; ".join(_escape_braces(r) for r in rules)


def _format_world_events(world: dict) -> str:
    events = world.get("event_log", [])[-3:]
    if not events:
        return "(none)"
    return "\n  ".join(
        f"(Round {e.get('round', '?')}) {_escape_braces(e.get('description', ''))}"
        for e in events
    )


def _format_world_locations(world: dict) -> str:
    locs = list(world.get("locations", {}).values())[:5]
    if not locs:
        return "(none)"
    return "\n  ".join(
        f"{_escape_braces(l.get('name', ''))} — {_escape_braces(l.get('description', ''))}"
        for l in locs
    )
```

- [ ] **Step 4: Update `_format_character_summary` to show location**

Replace the existing `_format_character_summary` with:

```python
def _format_character_summary(character: dict, locations: dict | None = None) -> str:
    emotions = character.get("emotional_state", {}).get("current", {})
    top = sorted(emotions.items(), key=lambda kv: -kv[1])[:2]
    emo_str = ", ".join(f"{e[0]}={e[1]:.1f}" for e in top) or "neutral"

    loc_id = character.get("location")
    loc_str = ""
    if loc_id and locations and loc_id in locations:
        loc_str = f" at {_escape_braces(locations[loc_id].get('name', loc_id))}"

    name = _escape_braces(character.get("name", "Unknown"))
    return f"{name} (feeling: {emo_str}){loc_str}"
```

- [ ] **Step 5: 🎯 USER CONTRIBUTION — event enforcement strength**

Replace `PROSE_PROMPT_TEMPLATE` with the extended version. The CINEMATIC DETAIL section gets a new line for events that will reference `EVENT_ENFORCEMENT_STRENGTH`.

First, add near the top of the file:

```python
# ============================================================================
# USER CONTRIBUTION POINT — how strongly to force world events into prose
# ============================================================================
# Three supported values; change this constant to tune enforcement:
#   "soft"   — "consider referencing the most recent world event if it fits"
#   "medium" — "weave the most recent event in OR acknowledge its aftermath"
#   "hard"   — "the opening line MUST reference the most recent world event"
# ============================================================================
EVENT_ENFORCEMENT_STRENGTH = "medium"

_ENFORCEMENT_PHRASES = {
    "soft":   "- Consider referencing the most recent world event if it fits naturally.",
    "medium": "- Weave the most recent world event in, OR acknowledge its aftermath. Do not ignore it.",
    "hard":   "- The OPENING LINE of this passage MUST reference the most recent world event.",
}
```

Then update `PROSE_PROMPT_TEMPLATE` to include world sections (keep all existing instructions, add the new world block and a new CINEMATIC rule):

```python
PROSE_PROMPT_TEMPLATE = """You are a screenwriter-turned-novelist. Your voice is PUNCHY, CINEMATIC, and DIALOGUE-DRIVEN.

Tone: {tone}

World grounding:
  Rules: {world_rules}
  Recent events:
  {world_events}
  Known locations:
  {world_locations}

Previous scene:
{previous}

Characters in this scene:
{characters}

Events this round (translate these into a scene — do NOT list them):
{actions}

Write a story passage following these rules:

STRUCTURE
- 2 to 3 short paragraphs. No more.
- Stay under 180 words total. Economy over explanation.
- Third-person past tense.

DIALOGUE
- Include at least 2 lines of spoken dialogue whenever characters interact.
- Dialogue does the heavy lifting — let characters reveal themselves through what they say (and don't say).
- Mix clipped lines with one longer beat. Rhythm matters.
- Use "said" sparingly. Trust the reader.

CINEMATIC DETAIL
- Open on a concrete visual: a hand, a face, an object, the weather.
- One sharp sensory detail per paragraph. Not five.
- Cut hard between beats — no connective "meanwhile" or "then."
- If a character has a known location, root the scene there.
{event_enforcement}

EMOTION
- Show it in bodies and voice — clenched jaw, dropped eyes, half-smile, a pause too long.
- Never name the emotion directly. No "she felt angry." No "he was sad."

CONTINUITY
- If previous scene exists, echo one detail from it — a word, an image, a beat. The story should feel continuous.

Write the prose only. No headings, no preamble, no meta commentary."""
```

- [ ] **Step 6: Update `generate_prose` signature + call**

Replace `generate_prose` with:

```python
def generate_prose(actions: list, characters: list, tone: str,
                   previous_beats: list, world: dict | None = None) -> str:
    """Generate a narrative passage from a round's actions via the LLM."""
    if not actions:
        return "A quiet pause settles over the scene. No one acts; no one speaks."

    world = world or {"rules": [], "locations": {}, "event_log": []}

    locations = world.get("locations", {})
    char_summaries = "\n".join(_format_character_summary(c, locations) for c in characters)
    action_lines = "\n".join(_format_action_line(a) for a in actions)
    prev_prose = "\n\n".join(_escape_braces(b.get("prose", "")) for b in previous_beats[-2:])

    enforcement = _ENFORCEMENT_PHRASES.get(EVENT_ENFORCEMENT_STRENGTH,
                                           _ENFORCEMENT_PHRASES["medium"])

    prompt = PROSE_PROMPT_TEMPLATE.format(
        tone=_escape_braces(tone),
        world_rules=_format_world_rules(world),
        world_events=_format_world_events(world),
        world_locations=_format_world_locations(world),
        characters=char_summaries or "(none)",
        actions=action_lines,
        previous=prev_prose or "(this is the first scene)",
        event_enforcement=enforcement,
    )
    return call_llm(prompt)
```

- [ ] **Step 7: Update `translate_round` to load world + filter dead**

Replace `translate_round` with:

```python
def translate_round(sim_dir: str, platform: str, target_round: int, tone: str = "neutral") -> dict:
    """Translate one round into a story beat end-to-end."""
    from app.services.narrative.story_store import StoryStore
    from app.services.narrative.character_engine import apply_action_emotional_delta
    from app.services.narrative.world_state import WorldStateStore

    store = StoryStore(sim_dir)
    world = WorldStateStore(sim_dir).load()

    actions_path = os.path.join(sim_dir, platform, "actions.jsonl")
    start_offset = store.get_file_offset(platform)
    actions, new_offset = read_actions_for_round(actions_path, start_offset, target_round)

    characters = store.load_characters()
    alive_names = {c["name"] for c in characters if c.get("status", "alive") != "dead"}
    characters = [c for c in characters if c["name"] in alive_names]
    actions = [a for a in actions if a.get("agent_name") in alive_names]

    previous_beats = store.get_all_beats()
    prose = generate_prose(actions, characters, tone, previous_beats, world)

    involved = sorted({a.get("agent_name") for a in actions if a.get("agent_name")})

    # Apply emotional deltas only to living characters
    all_chars = store.load_characters()
    all_by_name = {c["name"]: c for c in all_chars}
    for action in actions:
        char = all_by_name.get(action.get("agent_name"))
        if char and char.get("status", "alive") != "dead":
            apply_action_emotional_delta(char, action.get("action_type", ""))
    store.save_characters(list(all_by_name.values()))

    beat = {
        "round": target_round,
        "prose": prose,
        "characters": involved,
        "action_count": len(actions),
        "platform": platform,
    }
    store.append_beat(beat)
    store.set_file_offset(platform, new_offset)
    return beat
```

- [ ] **Step 8: Run full test suite**

```bash
cd backend && uv run pytest tests/ -v
```
Expected: all tests pass, including the new prompt-inclusion test.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/narrative/narrative_translator.py backend/tests/test_narrative_translator.py
git commit -m "feat(narrative): extend translator with world context + dead filter"
```

---

## Task 7: E2E — event injection and kill

**Files:**
- Modify: `backend/tests/test_narrative_e2e.py`

- [ ] **Step 1: Add integration test for event injection**

Append to `backend/tests/test_narrative_e2e.py`:

```python
from app.services.narrative.god_mode import inject_event, kill_character


def test_injected_event_appears_in_next_round_prompt(tmp_path):
    sim_dir = str(tmp_path / "sim_evt")
    os.makedirs(os.path.join(sim_dir, "twitter"))
    actions_path = os.path.join(sim_dir, "twitter", "actions.jsonl")

    lines = [
        {"round": 1, "agent_id": 1, "agent_name": "Elena", "action_type": "CREATE_POST",
         "action_args": {"content": "x"}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
        {"round": 2, "agent_id": 1, "agent_name": "Elena", "action_type": "REPOST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 2, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for a in lines:
            f.write(json.dumps(a) + "\n")

    store = StoryStore(sim_dir)
    neutral = {k: 0.0 for k in ["anger","fear","joy","sadness","surprise"]}
    store.save_characters([{
        "id": "1", "name": "Elena", "status": "alive",
        "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []},
    }])

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = "beat"
        translate_round(sim_dir, "twitter", 1, "noir")
        # Inject between rounds
        inject_event(sim_dir, description="A mysterious letter arrives.")
        translate_round(sim_dir, "twitter", 2, "noir")

        # Round-2 prompt should contain the event
        round2_prompt = mock_llm.call_args_list[1][0][0]
        assert "mysterious letter" in round2_prompt


def test_killed_character_filtered_from_next_round(tmp_path):
    sim_dir = str(tmp_path / "sim_kill")
    os.makedirs(os.path.join(sim_dir, "twitter"))
    actions_path = os.path.join(sim_dir, "twitter", "actions.jsonl")

    lines = [
        {"round": 1, "agent_id": 1, "agent_name": "Elena", "action_type": "CREATE_POST",
         "action_args": {"content": "x"}, "success": True, "timestamp": "t"},
        {"round": 1, "agent_id": 2, "agent_name": "Marcus", "action_type": "DISLIKE_POST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
        {"round": 2, "agent_id": 2, "agent_name": "Marcus", "action_type": "REPOST",
         "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 2, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for a in lines:
            f.write(json.dumps(a) + "\n")

    store = StoryStore(sim_dir)
    neutral = {k: 0.0 for k in ["anger","fear","joy","sadness","surprise"]}
    store.save_characters([
        {"id": "1", "name": "Elena", "status": "alive",
         "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []}},
        {"id": "2", "name": "Marcus", "status": "alive",
         "emotional_state": {"current": {**neutral, "trust": 0.5}, "history": []}},
    ])

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = "beat"
        translate_round(sim_dir, "twitter", 1, "noir")
        # Kill Marcus
        kill_character(sim_dir, "2")
        beat2 = translate_round(sim_dir, "twitter", 2, "noir")

        # Marcus acted in round 2 but is dead — should not appear
        assert "Marcus" not in beat2["characters"]

        # Round-2 prompt should NOT include Marcus in the character summary
        round2_prompt = mock_llm.call_args_list[1][0][0]
        # Marcus may appear in the death event log though — assert he's not in the
        # characters-in-scene section (by looking for "feeling:" adjacent to his name)
        lines = round2_prompt.split("\n")
        char_lines = [l for l in lines if "feeling:" in l]
        assert not any("Marcus" in l for l in char_lines)
```

- [ ] **Step 2: Run full suite**

```bash
cd backend && uv run pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_narrative_e2e.py
git commit -m "test(narrative): add e2e tests for event injection and kill"
```

---

## Task 8: API endpoints

**Files:**
- Modify: `backend/app/api/narrative.py`

- [ ] **Step 1: Add 6 new endpoints**

Append to `backend/app/api/narrative.py`:

```python
from ..services.narrative.world_state import WorldStateStore
from ..services.narrative.god_mode import inject_event, modify_emotion, kill_character


@narrative_bp.route('/world/<sim_id>', methods=['GET'])
def get_world(sim_id):
    store = WorldStateStore(_sim_dir(sim_id))
    return jsonify(store.load())


@narrative_bp.route('/world/<sim_id>/rules', methods=['POST'])
def set_rules(sim_id):
    data = request.get_json() or {}
    rules = data.get('rules')
    if not isinstance(rules, list):
        return jsonify({"error": "rules must be a list of strings"}), 400
    store = WorldStateStore(_sim_dir(sim_id))
    store.set_rules([str(r) for r in rules])
    return jsonify(store.load())


@narrative_bp.route('/world/<sim_id>/locations', methods=['POST'])
def upsert_location(sim_id):
    data = request.get_json() or {}
    if not data.get('id') or not data.get('name'):
        return jsonify({"error": "id and name are required"}), 400
    store = WorldStateStore(_sim_dir(sim_id))
    loc = store.upsert_location({
        "id": str(data['id']),
        "name": str(data['name']),
        "description": str(data.get('description', '')),
    })
    return jsonify(loc)


@narrative_bp.route('/godmode/<sim_id>/inject-event', methods=['POST'])
def godmode_inject_event(sim_id):
    data = request.get_json() or {}
    description = data.get('description')
    if not description:
        return jsonify({"error": "description is required"}), 400

    round_num = data.get('round')
    if round_num is not None:
        try:
            round_num = int(round_num)
            if round_num < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return jsonify({"error": "round must be a non-negative integer"}), 400

    evt = inject_event(_sim_dir(sim_id), description=str(description), round_num=round_num)
    return jsonify(evt)


@narrative_bp.route('/godmode/<sim_id>/modify-emotion', methods=['POST'])
def godmode_modify_emotion(sim_id):
    data = request.get_json() or {}
    char_id = data.get('character_id')
    emotions = data.get('emotions')
    if not char_id or not isinstance(emotions, dict):
        return jsonify({"error": "character_id and emotions are required"}), 400
    try:
        char = modify_emotion(_sim_dir(sim_id), str(char_id), emotions)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(char)


@narrative_bp.route('/godmode/<sim_id>/kill', methods=['POST'])
def godmode_kill(sim_id):
    data = request.get_json() or {}
    char_id = data.get('character_id')
    if not char_id:
        return jsonify({"error": "character_id is required"}), 400
    try:
        char = kill_character(_sim_dir(sim_id), str(char_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(char)
```

- [ ] **Step 2: Smoke test endpoints**

```bash
cd backend && LLM_API_KEY=fake ZEP_API_KEY=fake FLASK_DEBUG=false uv run python -c "
from app import create_app
app = create_app()
c = app.test_client()
print('GET world:', c.get('/api/narrative/world/x').status_code, c.get('/api/narrative/world/x').get_json())
print('POST rules empty:', c.post('/api/narrative/world/x/rules', json={}).status_code)
print('POST rules valid:', c.post('/api/narrative/world/x/rules', json={'rules': ['r1']}).status_code)
print('POST inject no desc:', c.post('/api/narrative/godmode/x/inject-event', json={}).status_code)
print('POST inject valid:', c.post('/api/narrative/godmode/x/inject-event', json={'description': 'test'}).status_code)
print('POST inject bad round:', c.post('/api/narrative/godmode/x/inject-event', json={'description': 'x', 'round': -1}).status_code)
"
```
Expected: 200, 400, 200, 400, 200, 400.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/narrative.py
git commit -m "feat(narrative): add world + god mode API endpoints"
```

---

## Task 9: Frontend API client

**Files:**
- Modify: `frontend/src/api/narrative.js`

- [ ] **Step 1: Add 6 named exports**

Append to `frontend/src/api/narrative.js`:

```javascript
export const getWorld = (simId) =>
  service.get(`/api/narrative/world/${simId}`)

export const setWorldRules = (simId, rules) =>
  service.post(`/api/narrative/world/${simId}/rules`, { rules })

export const upsertLocation = (simId, location) =>
  service.post(`/api/narrative/world/${simId}/locations`, location)

export const injectEvent = (simId, description, round = null) =>
  requestWithRetry(
    () => service.post(`/api/narrative/godmode/${simId}/inject-event`, { description, round }),
    3, 2000
  )

export const modifyEmotion = (simId, characterId, emotions) =>
  service.post(`/api/narrative/godmode/${simId}/modify-emotion`, {
    character_id: characterId,
    emotions,
  })

export const killCharacter = (simId, characterId) =>
  service.post(`/api/narrative/godmode/${simId}/kill`, { character_id: characterId })
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/narrative.js
git commit -m "feat(narrative): add frontend API client for world + god mode"
```

---

## Task 10: SimNav + routes + views

**Files:**
- Create: `frontend/src/views/GodModeView.vue`
- Create: `frontend/src/views/WorldBuilderView.vue`
- Modify: `frontend/src/views/StoryTimelineView.vue`
- Modify: `frontend/src/router/index.js`

**🎯 Contains USER CONTRIBUTION POINT #2 (location schema fields) — paused in Step 3.**

- [ ] **Step 1: Add routes**

Modify `frontend/src/router/index.js`:

```javascript
import GodModeView from '../views/GodModeView.vue'
import WorldBuilderView from '../views/WorldBuilderView.vue'
```

And in the routes array, before the closing `]`:

```javascript
  {
    path: '/godmode/:simulationId',
    name: 'GodMode',
    component: GodModeView,
    props: true
  },
  {
    path: '/world/:simulationId',
    name: 'World',
    component: WorldBuilderView,
    props: true
  }
```

- [ ] **Step 2: Add shared nav strip to StoryTimelineView**

In `frontend/src/views/StoryTimelineView.vue`, inside the top-level `<div class="story-timeline">`, add as the first child before `<header class="page-header">`:

```vue
<nav class="sim-nav">
  <router-link :to="`/story/${simId}`" active-class="active">Story</router-link>
  <router-link :to="`/godmode/${simId}`" active-class="active">God Mode</router-link>
  <router-link :to="`/world/${simId}`" active-class="active">World</router-link>
</nav>
```

And add to the scoped styles:

```css
.sim-nav {
  display: flex;
  gap: 1.25rem;
  padding: 0.75rem 0;
  margin-bottom: 1rem;
  border-bottom: 1px solid #e5ddc4;
  font-size: 0.9rem;
}
.sim-nav a {
  color: #7d6b3f;
  text-decoration: none;
  font-weight: 500;
}
.sim-nav a.active {
  color: #c9a45b;
  border-bottom: 2px solid #c9a45b;
  padding-bottom: 0.15rem;
}
```

- [ ] **Step 3: 🎯 USER CONTRIBUTION — location schema fields**

Create `frontend/src/views/WorldBuilderView.vue`.

The form has a **user-contribution point**: how many fields to accept for a location. Default is `{name, description}` but the user may want more. The comment block in Step 4 describes the options.

- [ ] **Step 4: Create WorldBuilderView.vue**

```vue
<template>
  <div class="world-builder">
    <nav class="sim-nav">
      <router-link :to="`/story/${simId}`">Story</router-link>
      <router-link :to="`/godmode/${simId}`">God Mode</router-link>
      <router-link :to="`/world/${simId}`" class="active">World</router-link>
    </nav>

    <h1>World Builder</h1>

    <section class="card">
      <h2>World Rules</h2>
      <p class="hint">One rule per line. These ground the story's world in every scene.</p>
      <textarea v-model="rulesText" rows="6" placeholder="Magic is forbidden
Winter is near
The kingdom is divided"></textarea>
      <button @click="saveRules" :disabled="busy">Save Rules</button>
    </section>

    <section class="card">
      <h2>Locations</h2>
      <!--
        USER CONTRIBUTION POINT — Location schema fields
        Default: id, name, description.
        Optional additions (uncomment in the form and in the addLocation() body):
          - atmosphere: short mood phrase ("dust motes in shafts of light")
          - time_of_day: "dawn" | "noon" | "dusk" | "midnight"
          - occupied_by: free-text notes about who usually is there
      -->
      <div v-for="loc in locations" :key="loc.id" class="location-item">
        <strong>{{ loc.name }}</strong> <span class="muted">({{ loc.id }})</span>
        <p>{{ loc.description }}</p>
      </div>

      <form @submit.prevent="addLocation" class="location-form">
        <input v-model="newLoc.id" placeholder="id (e.g. iron_tower)" required />
        <input v-model="newLoc.name" placeholder="Name (The Iron Tower)" required />
        <input v-model="newLoc.description" placeholder="Description" />
        <!-- Uncomment below to enable additional fields (per user contribution choices) -->
        <!-- <input v-model="newLoc.atmosphere" placeholder="Atmosphere (mood phrase)" /> -->
        <!-- <select v-model="newLoc.time_of_day"><option value="">time of day</option>
               <option>dawn</option><option>noon</option><option>dusk</option><option>midnight</option>
             </select> -->
        <button type="submit" :disabled="busy">Add / Update</button>
      </form>
    </section>

    <section class="card">
      <h2>Event Log</h2>
      <p class="hint">World events (injected via God Mode or logged automatically).</p>
      <ol class="event-log">
        <li v-for="e in events" :key="e.id">
          <span class="event-round">Round {{ e.round }}</span>
          <span class="event-type">{{ e.type }}</span>
          <span class="event-desc">{{ e.description }}</span>
        </li>
      </ol>
      <p v-if="!events.length" class="muted">No events yet.</p>
    </section>

    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getWorld, setWorldRules, upsertLocation } from '../api/narrative'

const route = useRoute()
const simId = route.params.simulationId

const world = ref({ rules: [], locations: {}, event_log: [] })
const rulesText = ref('')
const newLoc = ref({ id: '', name: '', description: '' })
const busy = ref(false)
const error = ref('')

const locations = computed(() => Object.values(world.value.locations || {}))
const events = computed(() => (world.value.event_log || []).slice().reverse())

async function load() {
  try {
    const res = await getWorld(simId)
    world.value = res
    rulesText.value = (res.rules || []).join('\n')
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  }
}

async function saveRules() {
  busy.value = true
  error.value = ''
  try {
    const rules = rulesText.value.split('\n').map(r => r.trim()).filter(Boolean)
    await setWorldRules(simId, rules)
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function addLocation() {
  busy.value = true
  error.value = ''
  try {
    await upsertLocation(simId, { ...newLoc.value })
    newLoc.value = { id: '', name: '', description: '' }
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.world-builder {
  max-width: 840px;
  margin: 0 auto;
  padding: 2rem 1.5rem 6rem;
}
.sim-nav {
  display: flex;
  gap: 1.25rem;
  padding: 0.75rem 0;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid #e5ddc4;
  font-size: 0.9rem;
}
.sim-nav a {
  color: #7d6b3f;
  text-decoration: none;
  font-weight: 500;
}
.sim-nav a.active {
  color: #c9a45b;
  border-bottom: 2px solid #c9a45b;
  padding-bottom: 0.15rem;
}
h1 {
  font-family: Georgia, serif;
  color: #2a2416;
  margin: 0 0 1.5rem;
}
.card {
  background: #faf7f0;
  border: 1px solid #e5ddc4;
  border-radius: 6px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}
.card h2 {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
  color: #2a2416;
}
.hint, .muted {
  color: #7d6b3f;
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
}
textarea, input, select {
  width: 100%;
  padding: 0.5rem 0.65rem;
  border: 1px solid #d4c893;
  border-radius: 4px;
  font-size: 0.9rem;
  background: white;
  margin-bottom: 0.5rem;
  font-family: inherit;
}
textarea {
  resize: vertical;
  font-family: Georgia, serif;
}
button {
  padding: 0.5rem 1rem;
  background: #c9a45b;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
}
button:disabled { opacity: 0.5; cursor: wait; }
.location-item {
  padding: 0.6rem 0;
  border-bottom: 1px dashed #e5ddc4;
}
.location-item p { margin: 0.25rem 0 0; color: #5a4f2f; font-size: 0.9rem; }
.location-form { display: grid; grid-template-columns: 1fr 1fr 2fr auto; gap: 0.5rem; align-items: start; margin-top: 0.75rem; }
.event-log { list-style: none; padding: 0; margin: 0; }
.event-log li {
  display: grid;
  grid-template-columns: 80px 140px 1fr;
  gap: 0.75rem;
  padding: 0.5rem 0;
  border-bottom: 1px dashed #e5ddc4;
  font-size: 0.9rem;
}
.event-round { color: #c9a45b; font-weight: 600; }
.event-type { font-family: 'SF Mono', Menlo, monospace; font-size: 0.75rem; color: #7d6b3f; }
.error { background: #ffe5e5; color: #8b0000; padding: 0.85rem 1rem; border-radius: 4px; }
</style>
```

- [ ] **Step 5: Create GodModeView.vue**

```vue
<template>
  <div class="godmode">
    <nav class="sim-nav">
      <router-link :to="`/story/${simId}`">Story</router-link>
      <router-link :to="`/godmode/${simId}`" class="active">God Mode</router-link>
      <router-link :to="`/world/${simId}`">World</router-link>
    </nav>

    <h1>God Mode</h1>

    <section class="card inject">
      <h2>⚡ Inject World Event</h2>
      <p class="hint">A new world event the narrator will weave into the next scene.</p>
      <textarea v-model="eventDesc" rows="3" placeholder="A stranger arrives at the market, carrying a sealed letter."></textarea>
      <div class="row">
        <input v-model.number="eventRound" type="number" min="0" placeholder="Round (optional)" />
        <button @click="doInject" :disabled="busy || !eventDesc">Inject</button>
      </div>
    </section>

    <section class="card emotion">
      <h2>💭 Modify Character Emotions</h2>
      <select v-model="emoCharId">
        <option value="">Select character…</option>
        <option v-for="c in aliveChars" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <div v-if="emoCharId" class="sliders">
        <div v-for="emo in emotions" :key="emo" class="slider-row">
          <label>{{ emo }}</label>
          <input type="range" min="0" max="1" step="0.05" v-model.number="emoValues[emo]" />
          <span>{{ emoValues[emo].toFixed(2) }}</span>
        </div>
        <button @click="doModifyEmotion" :disabled="busy">Apply</button>
      </div>
    </section>

    <section class="card kill">
      <h2>☠ Kill Character</h2>
      <p class="warning">Irreversible in v1. Type the character's name to confirm.</p>
      <select v-model="killCharId">
        <option value="">Select character…</option>
        <option v-for="c in aliveChars" :key="c.id" :value="c.id">{{ c.name }}</option>
      </select>
      <input v-if="killCharId" v-model="killConfirm"
             :placeholder="`Type ${selectedKillName} to confirm`" />
      <button @click="doKill" :disabled="busy || !canKill" class="danger">Kill</button>
    </section>

    <div v-if="error" class="error">{{ error }}</div>
    <div v-if="success" class="success">{{ success }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getCharacters, injectEvent, modifyEmotion, killCharacter } from '../api/narrative'

const route = useRoute()
const simId = route.params.simulationId

const emotions = ['anger', 'fear', 'joy', 'sadness', 'trust', 'surprise']

const characters = ref([])
const busy = ref(false)
const error = ref('')
const success = ref('')

const eventDesc = ref('')
const eventRound = ref(null)

const emoCharId = ref('')
const emoValues = ref(Object.fromEntries(emotions.map(e => [e, 0])))

const killCharId = ref('')
const killConfirm = ref('')

const aliveChars = computed(() =>
  characters.value.filter(c => (c.status || 'alive') !== 'dead')
)

const selectedKillName = computed(() => {
  const c = characters.value.find(c => c.id === killCharId.value)
  return c?.name || ''
})

const canKill = computed(() =>
  killCharId.value &&
  selectedKillName.value &&
  killConfirm.value.trim().toLowerCase() === selectedKillName.value.toLowerCase()
)

async function loadCharacters() {
  try {
    const res = await getCharacters(simId)
    characters.value = res.characters || []
  } catch (e) { /* non-fatal */ }
}

function flash(msg) {
  success.value = msg
  setTimeout(() => { success.value = '' }, 2500)
}

async function doInject() {
  busy.value = true
  error.value = ''
  try {
    await injectEvent(simId, eventDesc.value, eventRound.value || null)
    flash('Event injected.')
    eventDesc.value = ''
    eventRound.value = null
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function doModifyEmotion() {
  busy.value = true
  error.value = ''
  try {
    await modifyEmotion(simId, emoCharId.value, emoValues.value)
    flash('Emotions updated.')
    await loadCharacters()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

async function doKill() {
  busy.value = true
  error.value = ''
  try {
    await killCharacter(simId, killCharId.value)
    flash(`${selectedKillName.value} has been killed.`)
    killCharId.value = ''
    killConfirm.value = ''
    await loadCharacters()
  } catch (e) {
    error.value = e?.response?.data?.error || e.message
  } finally {
    busy.value = false
  }
}

onMounted(loadCharacters)
</script>

<style scoped>
.godmode {
  max-width: 840px;
  margin: 0 auto;
  padding: 2rem 1.5rem 6rem;
}
.sim-nav {
  display: flex; gap: 1.25rem;
  padding: 0.75rem 0; margin-bottom: 1.5rem;
  border-bottom: 1px solid #e5ddc4; font-size: 0.9rem;
}
.sim-nav a { color: #7d6b3f; text-decoration: none; font-weight: 500; }
.sim-nav a.active { color: #c9a45b; border-bottom: 2px solid #c9a45b; padding-bottom: 0.15rem; }
h1 { font-family: Georgia, serif; color: #2a2416; margin: 0 0 1.5rem; }
.card {
  background: #faf7f0; border: 1px solid #e5ddc4; border-radius: 6px;
  padding: 1.25rem 1.5rem; margin-bottom: 1.5rem;
}
.card h2 { margin: 0 0 0.5rem; font-size: 1.1rem; color: #2a2416; }
.hint { color: #7d6b3f; font-size: 0.85rem; margin: 0 0 0.75rem; }
.warning { color: #8b0000; font-size: 0.85rem; margin: 0 0 0.75rem; }
textarea, input, select {
  width: 100%; padding: 0.5rem 0.65rem; border: 1px solid #d4c893;
  border-radius: 4px; font-size: 0.9rem; background: white; margin-bottom: 0.5rem;
  font-family: inherit;
}
.row { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; }
button {
  padding: 0.5rem 1rem; background: #c9a45b; color: white;
  border: none; border-radius: 4px; cursor: pointer; font-weight: 500;
}
button:disabled { opacity: 0.5; cursor: wait; }
button.danger { background: #8b0000; }
.sliders { margin-top: 0.75rem; }
.slider-row {
  display: grid; grid-template-columns: 80px 1fr 50px;
  gap: 0.5rem; align-items: center; font-size: 0.85rem;
  margin-bottom: 0.35rem;
}
.slider-row label { text-transform: uppercase; letter-spacing: 0.05em; color: #7d6b3f; }
.error { background: #ffe5e5; color: #8b0000; padding: 0.85rem 1rem; border-radius: 4px; margin-top: 1rem; }
.success { background: #e5f7e5; color: #2a6b2a; padding: 0.85rem 1rem; border-radius: 4px; margin-top: 1rem; }
</style>
```

- [ ] **Step 6: Build frontend**

```bash
cd frontend && npm run build
```
Expected: clean build, no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(narrative): add GodModeView, WorldBuilderView, and shared nav"
```

---

## Self-review checklist

**Spec coverage:**
- §4.1 inject_event → Task 3 ✓
- §4.2 modify_emotion + audit log → Task 4 ✓
- §4.3 kill_character + auto-death event → Task 5 ✓
- §5.0 WorldStateStore + load semantics → Task 1 ✓
- §5.0 id/name/location resolution → Task 6 (translator) ✓
- §5 prompt extension with 3 world fields → Task 6 ✓
- §5 brace escape → Task 6 ✓
- §5.1 dead character filter → Task 6 ✓
- §3.3 all 6 API endpoints → Task 8 ✓
- §6.4 shared nav → Tasks 10.2 (Story) + 10.4 + 10.5
- §6.5 typed-name kill confirmation → Task 10.5 (canKill computed) ✓
- §7 round validation → Task 8 inject_event handler ✓
- §8 prompt inclusion test → Task 6 Step 1 ✓
- §8 e2e tests → Task 7 ✓
- §9.1 user contribution EVENT_ENFORCEMENT_STRENGTH → Task 6 Step 5 ✓
- §9.2 user contribution location schema → Task 10 Step 3 ✓

**Non-placeholder scan:** Every step shows actual code or exact commands. No "TODO later" or "fill in details" outside the two explicit USER CONTRIBUTION POINTs.

**Type consistency:** `translate_round`, `generate_prose`, `inject_event`, `modify_emotion`, `kill_character`, `WorldStateStore`, `_current_round`, `_escape_braces` — all signatures stable across task boundaries.

**Deferred (per spec §10):** Mid-sim OASIS injection, resurrection, force action, time skip, factions, resources, location transitions, bulk ops, undo/history, delete endpoints, file locking, event log rotation, per-sim enforcement strength.
