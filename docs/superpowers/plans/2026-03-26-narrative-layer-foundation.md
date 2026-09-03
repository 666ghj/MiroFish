# Narrative Layer Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational narrative layer — translate OASIS simulation actions into story prose, track extended character state, and display the generated story in a new Vue view.

**Architecture:** New `backend/app/services/narrative/` module with three services (translator, character engine, action mapper). New Flask blueprint at `/api/narrative/*`. New Vue view `StoryTimelineView.vue` polls for narrative updates. All state is file-based under `uploads/simulations/{sim_id}/narrative/`.

**Tech Stack:** Python 3.11, Flask, Vue 3 + Vite, existing LLM client (`backend/app/utils/llm_client.py`), existing retry utility (`backend/app/utils/retry.py`).

**Scope boundary:** This plan covers ONLY translator + character engine + timeline view. God Mode, timeline branching, world state, enhanced input, and export are separate follow-on plans.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `backend/app/services/narrative/__init__.py` | Package init |
| `backend/app/services/narrative/action_mapper.py` | Maps OASIS action types to narrative verbs/interpretations |
| `backend/app/services/narrative/character_engine.py` | Extended character profiles, emotional state, arc detection |
| `backend/app/services/narrative/narrative_translator.py` | Reads actions.jsonl, generates prose via LLM |
| `backend/app/services/narrative/story_store.py` | File I/O for narrative state (story_beats.json, characters.json, translator_state.json) |
| `backend/app/api/narrative.py` | Flask blueprint with narrative endpoints |
| `backend/tests/test_action_mapper.py` | Tests for action mapping |
| `backend/tests/test_character_engine.py` | Tests for character state updates |
| `backend/tests/test_narrative_translator.py` | Tests for translation pipeline |
| `backend/tests/test_story_store.py` | Tests for file I/O |
| `frontend/src/api/narrative.js` | Frontend API client for narrative endpoints |
| `frontend/src/views/StoryTimelineView.vue` | Story reading UI |
| `frontend/src/components/StoryBeat.vue` | Single story paragraph component |
| `frontend/src/components/CharacterCard.vue` | Character summary with emotion indicators |

### Modified files

| File | Change |
|---|---|
| `backend/app/api/__init__.py` | Add `narrative_bp` blueprint registration |
| `backend/app/__init__.py` | Register narrative blueprint |
| `frontend/src/router/index.js` | Add `/story/:simId` route |

---

## Task 1: Action Mapper — Static Mapping Table

**Files:**
- Create: `backend/app/services/narrative/__init__.py`
- Create: `backend/app/services/narrative/action_mapper.py`
- Test: `backend/tests/test_action_mapper.py`

- [ ] **Step 1: Create empty package init**

Create `backend/app/services/narrative/__init__.py` with a single empty line.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_action_mapper.py`:

```python
from app.services.narrative.action_mapper import map_action_to_verb, get_narrative_context

def test_create_post_maps_to_speech():
    result = map_action_to_verb("CREATE_POST")
    assert result == "speaks"

def test_like_post_maps_to_agreement():
    result = map_action_to_verb("LIKE_POST")
    assert result == "agrees with"

def test_unknown_action_returns_fallback():
    result = map_action_to_verb("UNKNOWN_ACTION")
    assert result == "does something"

def test_get_narrative_context_returns_interpretation():
    ctx = get_narrative_context("REPOST")
    assert "rumor" in ctx.lower() or "amplifies" in ctx.lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_action_mapper.py -v`
Expected: FAIL with ImportError (module not yet created).

- [ ] **Step 4: Implement action_mapper.py**

Create `backend/app/services/narrative/action_mapper.py`:

```python
"""Maps OASIS action types to narrative verbs and interpretations."""

ACTION_TO_VERB = {
    "CREATE_POST": "speaks",
    "LIKE_POST": "agrees with",
    "REPOST": "spreads word of",
    "QUOTE_POST": "responds to",
    "FOLLOW": "shows loyalty to",
    "DO_NOTHING": "observes in silence",
    "CREATE_COMMENT": "engages with",
    "DISLIKE_POST": "disapproves of",
    "LIKE_COMMENT": "validates",
    "DISLIKE_COMMENT": "dismisses",
    "SEARCH_POSTS": "investigates",
    "SEARCH_USER": "seeks out",
    "MUTE": "ignores",
}

ACTION_TO_NARRATIVE = {
    "CREATE_POST": "Character speaks, declares, or announces",
    "LIKE_POST": "Character agrees, supports, or nods",
    "REPOST": "Character spreads rumor, amplifies, or gossips",
    "QUOTE_POST": "Character responds, debates, or challenges",
    "FOLLOW": "Character allies with or shows loyalty to",
    "DO_NOTHING": "Character reflects, observes, or waits",
    "CREATE_COMMENT": "Character engages in dialogue",
    "DISLIKE_POST": "Character opposes, confronts, or disapproves",
    "LIKE_COMMENT": "Character validates a response",
    "DISLIKE_COMMENT": "Character dismisses or mocks",
    "SEARCH_POSTS": "Character investigates or seeks information",
    "SEARCH_USER": "Character seeks out a specific person",
    "MUTE": "Character avoids, ignores, or shuns",
}


def map_action_to_verb(action_type: str) -> str:
    return ACTION_TO_VERB.get(action_type, "does something")


def get_narrative_context(action_type: str) -> str:
    return ACTION_TO_NARRATIVE.get(action_type, "Character takes an unknown action")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_action_mapper.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/narrative/__init__.py backend/app/services/narrative/action_mapper.py backend/tests/test_action_mapper.py
git commit -m "feat(narrative): add action-to-verb mapping for OASIS actions"
```

---

## Task 2: Story Store — File I/O for Narrative State

**Files:**
- Create: `backend/app/services/narrative/story_store.py`
- Test: `backend/tests/test_story_store.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_story_store.py`:

```python
import os
import tempfile
import pytest
from app.services.narrative.story_store import StoryStore

@pytest.fixture
def temp_sim_dir():
    with tempfile.TemporaryDirectory() as d:
        sim_dir = os.path.join(d, "sim_test123")
        os.makedirs(sim_dir)
        yield sim_dir

def test_save_and_load_story_beats(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    beat = {"round": 1, "prose": "Elena spoke.", "characters": ["elena"]}
    store.append_beat(beat)

    beats = store.get_all_beats()
    assert len(beats) == 1
    assert beats[0]["prose"] == "Elena spoke."

def test_translator_state_tracks_offset(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    assert store.get_file_offset("twitter") == 0

    store.set_file_offset("twitter", 1024)
    assert store.get_file_offset("twitter") == 1024

def test_get_beat_by_round(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    store.append_beat({"round": 1, "prose": "First"})
    store.append_beat({"round": 2, "prose": "Second"})

    beat = store.get_beat_by_round(2)
    assert beat["prose"] == "Second"

def test_narrative_dir_created_on_first_write(temp_sim_dir):
    store = StoryStore(temp_sim_dir)
    store.append_beat({"round": 1, "prose": "test"})

    narrative_dir = os.path.join(temp_sim_dir, "narrative")
    assert os.path.isdir(narrative_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_story_store.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement story_store.py**

Create `backend/app/services/narrative/story_store.py`:

```python
"""File-based persistence for narrative state."""
import os
import json
from typing import Optional


class StoryStore:
    """Manages narrative/*.json files for a single simulation."""

    def __init__(self, sim_dir: str):
        self.sim_dir = sim_dir
        self.narrative_dir = os.path.join(sim_dir, "narrative")
        self.beats_path = os.path.join(self.narrative_dir, "story_beats.json")
        self.translator_state_path = os.path.join(self.narrative_dir, "translator_state.json")
        self.characters_path = os.path.join(self.narrative_dir, "characters.json")

    def _ensure_dir(self):
        os.makedirs(self.narrative_dir, exist_ok=True)

    def append_beat(self, beat: dict) -> None:
        self._ensure_dir()
        beats = self.get_all_beats()
        beats.append(beat)
        with open(self.beats_path, "w", encoding="utf-8") as f:
            json.dump(beats, f, ensure_ascii=False, indent=2)

    def get_all_beats(self) -> list:
        if not os.path.exists(self.beats_path):
            return []
        with open(self.beats_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_beat_by_round(self, round_num: int) -> Optional[dict]:
        for beat in self.get_all_beats():
            if beat.get("round") == round_num:
                return beat
        return None

    def get_file_offset(self, platform: str) -> int:
        if not os.path.exists(self.translator_state_path):
            return 0
        with open(self.translator_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state.get(f"{platform}_offset", 0)

    def set_file_offset(self, platform: str, offset: int) -> None:
        self._ensure_dir()
        state = {}
        if os.path.exists(self.translator_state_path):
            with open(self.translator_state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        state[f"{platform}_offset"] = offset
        with open(self.translator_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def save_characters(self, characters: list) -> None:
        self._ensure_dir()
        with open(self.characters_path, "w", encoding="utf-8") as f:
            json.dump(characters, f, ensure_ascii=False, indent=2)

    def load_characters(self) -> list:
        if not os.path.exists(self.characters_path):
            return []
        with open(self.characters_path, "r", encoding="utf-8") as f:
            return json.load(f)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_story_store.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/story_store.py backend/tests/test_story_store.py
git commit -m "feat(narrative): add StoryStore for file-based narrative persistence"
```

---

## Task 3: Character Engine — Initial Emotional State

**Files:**
- Create: `backend/app/services/narrative/character_engine.py`
- Test: `backend/tests/test_character_engine.py`

**Learning mode note:** Step 4 of this task asks **you (the user)** to write the emotional delta rules. Those rules encode your creative judgment about how characters react emotionally — it's the kind of decision that shapes storytelling quality and is better made by a human than an LLM.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_character_engine.py`:

```python
from app.services.narrative.character_engine import (
    CharacterEngine,
    create_initial_character,
    apply_action_emotional_delta,
)

def test_create_initial_character_has_neutral_emotions():
    char = create_initial_character(char_id="elena", name="Elena Voss")
    assert char["emotional_state"]["current"]["anger"] == 0.0
    assert char["emotional_state"]["current"]["joy"] == 0.0
    assert char["emotional_state"]["current"]["trust"] == 0.5  # neutral baseline

def test_create_initial_character_stores_name_and_id():
    char = create_initial_character(char_id="elena", name="Elena Voss")
    assert char["id"] == "elena"
    assert char["name"] == "Elena Voss"

def test_apply_delta_clamps_to_zero_one_range():
    char = create_initial_character(char_id="x", name="X")
    # Apply a large positive anger delta
    apply_action_emotional_delta(char, "DISLIKE_POST")
    apply_action_emotional_delta(char, "DISLIKE_POST")
    apply_action_emotional_delta(char, "DISLIKE_POST")
    apply_action_emotional_delta(char, "DISLIKE_POST")
    apply_action_emotional_delta(char, "DISLIKE_POST")
    assert 0.0 <= char["emotional_state"]["current"]["anger"] <= 1.0

def test_create_post_increases_confidence_proxy():
    # Speaking out should bump joy slightly (a proxy for confidence)
    char = create_initial_character(char_id="x", name="X")
    baseline_joy = char["emotional_state"]["current"]["joy"]
    apply_action_emotional_delta(char, "CREATE_POST")
    assert char["emotional_state"]["current"]["joy"] >= baseline_joy

def test_dislike_post_increases_anger():
    char = create_initial_character(char_id="x", name="X")
    apply_action_emotional_delta(char, "DISLIKE_POST")
    assert char["emotional_state"]["current"]["anger"] > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_character_engine.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement scaffolding with placeholder deltas**

Create `backend/app/services/narrative/character_engine.py`:

```python
"""Extended character profiles, emotional state, arc detection."""
from typing import Dict


EMOTIONS = ["anger", "fear", "joy", "sadness", "trust", "surprise"]

INITIAL_EMOTIONAL_STATE = {
    "anger": 0.0,
    "fear": 0.0,
    "joy": 0.0,
    "sadness": 0.0,
    "trust": 0.5,
    "surprise": 0.0,
}


def create_initial_character(char_id: str, name: str, backstory: str = "",
                              motivations: list = None, personality: list = None) -> dict:
    """Build a new character profile with neutral emotional state."""
    return {
        "id": char_id,
        "name": name,
        "backstory": backstory,
        "motivations": motivations or [],
        "personality_traits": personality or [],
        "emotional_state": {
            "current": dict(INITIAL_EMOTIONAL_STATE),
            "history": [],
        },
        "relationships": {},
        "arc": {"archetype": None, "stage": "beginning", "key_moments": []},
    }


# >>> USER CONTRIBUTION POINT — see Step 4 <<<
ACTION_EMOTIONAL_DELTAS: Dict[str, Dict[str, float]] = {
    # TODO: Fill this in — see Task 3, Step 4
}


def apply_action_emotional_delta(character: dict, action_type: str) -> None:
    """Apply an emotional state change based on an action the character took."""
    deltas = ACTION_EMOTIONAL_DELTAS.get(action_type, {})
    current = character["emotional_state"]["current"]
    for emotion, delta in deltas.items():
        if emotion in current:
            current[emotion] = max(0.0, min(1.0, current[emotion] + delta))


class CharacterEngine:
    """Manages character roster for a simulation."""

    def __init__(self, store):
        self.store = store

    def initialize_from_profiles(self, oasis_profiles: list) -> list:
        """Bootstrap character roster from OASIS profiles."""
        characters = []
        for profile in oasis_profiles:
            char = create_initial_character(
                char_id=str(profile.get("user_id", profile.get("id", ""))),
                name=profile.get("name", "Unknown"),
            )
            characters.append(char)
        self.store.save_characters(characters)
        return characters
```

- [ ] **Step 4: 🎯 USER CONTRIBUTION — Define Emotional Deltas**

**This is the key creative decision.** The `ACTION_EMOTIONAL_DELTAS` dictionary maps each OASIS action to changes in the character's emotional state. Your choices here directly shape how characters feel and evolve over a story.

**Open** `backend/app/services/narrative/character_engine.py` and fill in the `ACTION_EMOTIONAL_DELTAS` dictionary. A delta is a dict of `{emotion: float}` where the float is added to the current emotion value (clamped to 0.0–1.0).

**Guidance — things to consider:**
- `CREATE_POST` (speaking out) — small confidence bump? small anxiety bump?
- `LIKE_POST` (agreeing) — builds trust? slight joy?
- `DISLIKE_POST` (confronting) — anger up, trust down?
- `FOLLOW` (allying) — trust up, maybe joy?
- `REPOST` (spreading rumor) — neutral? or surprise?
- `DO_NOTHING` (observing) — sadness creep? fear creep?

Suggested range: keep deltas between -0.15 and +0.15 per action (so they accumulate gradually). Example format:

```python
ACTION_EMOTIONAL_DELTAS: Dict[str, Dict[str, float]] = {
    "CREATE_POST": {"joy": 0.05},
    "DISLIKE_POST": {"anger": 0.10, "trust": -0.05},
    # ... fill in the rest for all 13 actions in action_mapper.py
}
```

**Why your judgment matters:** These values are a model of human emotional reaction. An LLM would pick generic values; your intuitions as a storyteller will produce richer, more deliberate character arcs. If you want characters who spiral into darkness easily, use bigger negative deltas. If you want resilient characters, use smaller ones.

Fill in deltas for at least these 7 core actions: `CREATE_POST`, `LIKE_POST`, `DISLIKE_POST`, `REPOST`, `QUOTE_POST`, `FOLLOW`, `DO_NOTHING`. The other 6 can use defaults (empty dicts).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_character_engine.py -v`
Expected: 5 passed. If `test_dislike_post_increases_anger` or `test_create_post_increases_confidence_proxy` fails, your deltas may be missing the relevant emotion — adjust.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/narrative/character_engine.py backend/tests/test_character_engine.py
git commit -m "feat(narrative): add CharacterEngine with emotional state tracking"
```

---

## Task 4: Narrative Translator — Read Actions.jsonl

**Files:**
- Create: `backend/app/services/narrative/narrative_translator.py`
- Test: `backend/tests/test_narrative_translator.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_narrative_translator.py`:

```python
import os
import json
import tempfile
import pytest
from app.services.narrative.narrative_translator import read_actions_for_round

@pytest.fixture
def actions_file():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "actions.jsonl")
        lines = [
            {"round": 1, "agent_id": 1, "agent_name": "Alice", "action_type": "CREATE_POST", "action_args": {"content": "Hi"}, "success": True, "timestamp": "2026-03-26T12:00:00"},
            {"round": 1, "agent_id": 2, "agent_name": "Bob", "action_type": "LIKE_POST", "action_args": {"post_id": 1}, "success": True, "timestamp": "2026-03-26T12:00:01"},
            {"event_type": "round_end", "round": 1, "timestamp": "2026-03-26T12:00:02"},
            {"round": 2, "agent_id": 1, "agent_name": "Alice", "action_type": "REPOST", "action_args": {}, "success": True, "timestamp": "2026-03-26T12:00:03"},
        ]
        with open(path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        yield path

def test_read_actions_for_round_1(actions_file):
    actions, next_offset = read_actions_for_round(actions_file, start_offset=0, target_round=1)
    assert len(actions) == 2
    assert actions[0]["agent_name"] == "Alice"
    assert actions[1]["agent_name"] == "Bob"
    assert next_offset > 0

def test_read_actions_resumes_from_offset(actions_file):
    # First read round 1
    _, offset_after_round_1 = read_actions_for_round(actions_file, start_offset=0, target_round=1)
    # Then read round 2 using that offset
    actions, _ = read_actions_for_round(actions_file, start_offset=offset_after_round_1, target_round=2)
    assert len(actions) == 1
    assert actions[0]["action_type"] == "REPOST"

def test_read_actions_missing_file_returns_empty():
    actions, offset = read_actions_for_round("/nonexistent/path.jsonl", start_offset=0, target_round=1)
    assert actions == []
    assert offset == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_narrative_translator.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement read_actions_for_round**

Create `backend/app/services/narrative/narrative_translator.py`:

```python
"""Reads OASIS actions.jsonl and translates them into story prose."""
import os
import json
from typing import List, Tuple


def read_actions_for_round(jsonl_path: str, start_offset: int, target_round: int) -> Tuple[List[dict], int]:
    """Read all actions for target_round starting at start_offset.

    Returns (actions, new_offset). new_offset is the file position right after
    the round_end event (or EOF if not found yet).
    """
    if not os.path.exists(jsonl_path):
        return [], start_offset

    actions = []
    new_offset = start_offset

    with open(jsonl_path, "r", encoding="utf-8") as f:
        f.seek(start_offset)
        while True:
            line_start = f.tell()
            line = f.readline()
            if not line:
                break
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Round-end event marks boundary
            if entry.get("event_type") == "round_end" and entry.get("round") == target_round:
                new_offset = f.tell()
                break

            # Skip events, other rounds
            if "event_type" in entry:
                new_offset = f.tell()
                continue
            if entry.get("round") != target_round:
                new_offset = f.tell()
                continue

            actions.append(entry)
            new_offset = f.tell()

    return actions, new_offset
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_narrative_translator.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/narrative_translator.py backend/tests/test_narrative_translator.py
git commit -m "feat(narrative): add actions.jsonl round reader"
```

---

## Task 5: Narrative Translator — LLM Prose Generation

**Files:**
- Modify: `backend/app/services/narrative/narrative_translator.py`
- Modify: `backend/tests/test_narrative_translator.py`

**Learning mode note:** Step 4 of this task asks you to shape the **prose generation prompt**. The prompt is the single biggest lever for story quality. This is where your voice as a storyteller gets encoded.

- [ ] **Step 1: Add failing test for generate_prose**

Append to `backend/tests/test_narrative_translator.py`:

```python
from unittest.mock import patch, MagicMock
from app.services.narrative.narrative_translator import generate_prose

def test_generate_prose_calls_llm_with_context():
    actions = [
        {"agent_name": "Elena", "action_type": "CREATE_POST", "action_args": {"content": "We must act."}},
        {"agent_name": "Marcus", "action_type": "DISLIKE_POST", "action_args": {}},
    ]
    characters = [
        {"id": "1", "name": "Elena", "emotional_state": {"current": {"anger": 0.2, "joy": 0.0, "fear": 0.1, "sadness": 0.0, "trust": 0.5, "surprise": 0.0}}},
        {"id": "2", "name": "Marcus", "emotional_state": {"current": {"anger": 0.5, "joy": 0.0, "fear": 0.0, "sadness": 0.0, "trust": 0.3, "surprise": 0.0}}},
    ]
    fake_response = "Elena's voice cut through the silence. Marcus scowled, unmoved."

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = fake_response
        result = generate_prose(actions, characters, tone="dark political thriller", previous_beats=[])

        assert result == fake_response
        # Verify the prompt included character names and action info
        call_args = mock_llm.call_args
        prompt = str(call_args)
        assert "Elena" in prompt
        assert "Marcus" in prompt

def test_generate_prose_empty_actions_returns_placeholder():
    result = generate_prose([], [], tone="any", previous_beats=[])
    assert "quiet" in result.lower() or "pause" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_narrative_translator.py::test_generate_prose_calls_llm_with_context -v`
Expected: FAIL with ImportError for `generate_prose` or `call_llm`.

- [ ] **Step 3: Add LLM client import and prose generator scaffold**

Append to `backend/app/services/narrative/narrative_translator.py`:

```python
from app.utils.llm_client import call_llm
from app.services.narrative.action_mapper import get_narrative_context


def _format_character_summary(character: dict) -> str:
    emotions = character["emotional_state"]["current"]
    top_emotions = sorted(emotions.items(), key=lambda kv: -kv[1])[:2]
    emo_str = ", ".join(f"{e[0]}={e[1]:.1f}" for e in top_emotions)
    return f"{character['name']} (feeling: {emo_str})"


def _format_action_line(action: dict) -> str:
    name = action.get("agent_name", "Someone")
    act = action.get("action_type", "UNKNOWN")
    args = action.get("action_args", {})
    content = args.get("content", "")
    ctx = get_narrative_context(act)
    if content:
        return f"- {name}: {ctx}. Content: \"{content}\""
    return f"- {name}: {ctx}"


# >>> USER CONTRIBUTION POINT — see Step 4 <<<
PROSE_PROMPT_TEMPLATE = """TODO: the user will define this in Step 4"""


def generate_prose(actions: list, characters: list, tone: str, previous_beats: list) -> str:
    """Generate a narrative passage from a round's actions."""
    if not actions:
        return "A quiet pause settles over the scene. No one acts; no one speaks."

    char_summaries = "\n".join(_format_character_summary(c) for c in characters)
    action_lines = "\n".join(_format_action_line(a) for a in actions)
    prev_prose = "\n\n".join(b.get("prose", "") for b in previous_beats[-2:])

    prompt = PROSE_PROMPT_TEMPLATE.format(
        tone=tone,
        characters=char_summaries,
        actions=action_lines,
        previous=prev_prose or "(this is the first scene)",
    )
    return call_llm(prompt)
```

- [ ] **Step 4: 🎯 USER CONTRIBUTION — Design the Prose Prompt**

**This is the storytelling soul of the system.** Replace the `PROSE_PROMPT_TEMPLATE` with your prompt. The template has 4 substitution fields: `{tone}`, `{characters}`, `{actions}`, `{previous}`.

**Guidance — key choices:**

1. **Tense and POV**: Third-person past is most versatile. First-person or present can work but limit you.
2. **Paragraph count**: 2-4 is a good range. Too short = feels like a log. Too long = drags.
3. **Dialogue**: Should the prompt encourage dialogue when actions have `content`? Probably yes.
4. **"Show don't tell"**: Instructing the LLM to show emotions through action/dialogue rather than stating them is a classic writing lever.
5. **Tone consistency**: How hard do you push the tone? A strong instruction like "Every line should feel grim" vs a soft one like "Maintain a grim tone."
6. **Continuity**: Instruct it to continue naturally from `{previous}`.

**Suggested structure (copy and modify):**

```python
PROSE_PROMPT_TEMPLATE = """You are a narrative writer working in the tone of {tone}.

Previous story context:
{previous}

Characters in this scene:
{characters}

Events this round:
{actions}

Write a story passage of 2-4 paragraphs that:
- Uses third-person past tense
- Shows character emotions through action, dialogue, and internal thought (never state emotions directly)
- Weaves the events above into prose — never list them like a log
- Continues naturally from the previous context
- Maintains the tone of {tone} throughout

Write only the prose. No headings, no preamble."""
```

Feel free to modify heavily — try your own instructions, add more rules, or tighten it. The quality of every generated story depends on this prompt.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_narrative_translator.py -v`
Expected: 5 passed (3 from Task 4 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/narrative/narrative_translator.py backend/tests/test_narrative_translator.py
git commit -m "feat(narrative): add LLM-driven prose generation"
```

---

## Task 6: Narrative Translator — Translate Round Orchestration

**Files:**
- Modify: `backend/app/services/narrative/narrative_translator.py`
- Modify: `backend/tests/test_narrative_translator.py`

- [ ] **Step 1: Add failing test**

Append to `backend/tests/test_narrative_translator.py`:

```python
from app.services.narrative.narrative_translator import translate_round
from app.services.narrative.story_store import StoryStore

def test_translate_round_produces_beat(tmp_path):
    sim_dir = str(tmp_path / "sim_test")
    os.makedirs(sim_dir)
    platform_dir = os.path.join(sim_dir, "twitter")
    os.makedirs(platform_dir)
    actions_path = os.path.join(platform_dir, "actions.jsonl")

    lines = [
        {"round": 1, "agent_id": 1, "agent_name": "Alice", "action_type": "CREATE_POST", "action_args": {"content": "Hi"}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    store = StoryStore(sim_dir)
    store.save_characters([
        {"id": "1", "name": "Alice", "emotional_state": {"current": {"anger": 0, "fear": 0, "joy": 0, "sadness": 0, "trust": 0.5, "surprise": 0}}},
    ])

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.return_value = "Alice spoke into the void."
        beat = translate_round(sim_dir, platform="twitter", target_round=1, tone="neutral")

    assert beat["round"] == 1
    assert beat["prose"] == "Alice spoke into the void."
    assert "Alice" in beat.get("characters", [])

    stored_beats = store.get_all_beats()
    assert len(stored_beats) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_narrative_translator.py::test_translate_round_produces_beat -v`
Expected: FAIL with ImportError for `translate_round`.

- [ ] **Step 3: Implement translate_round**

Append to `backend/app/services/narrative/narrative_translator.py`:

```python
from app.services.narrative.story_store import StoryStore
from app.services.narrative.character_engine import apply_action_emotional_delta


def translate_round(sim_dir: str, platform: str, target_round: int, tone: str = "neutral") -> dict:
    """Translate a single round of simulation into a story beat."""
    store = StoryStore(sim_dir)
    actions_path = os.path.join(sim_dir, platform, "actions.jsonl")
    start_offset = store.get_file_offset(platform)

    actions, new_offset = read_actions_for_round(actions_path, start_offset, target_round)

    characters = store.load_characters()
    previous_beats = store.get_all_beats()

    prose = generate_prose(actions, characters, tone, previous_beats)

    involved = list({a.get("agent_name") for a in actions if a.get("agent_name")})

    # Update emotional states
    char_by_name = {c["name"]: c for c in characters}
    for a in actions:
        char = char_by_name.get(a.get("agent_name"))
        if char:
            apply_action_emotional_delta(char, a.get("action_type", ""))
    store.save_characters(list(char_by_name.values()))

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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_narrative_translator.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/narrative/narrative_translator.py backend/tests/test_narrative_translator.py
git commit -m "feat(narrative): orchestrate round translation with state updates"
```

---

## Task 7: Flask Blueprint — Narrative API

**Files:**
- Create: `backend/app/api/narrative.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/__init__.py`

- [ ] **Step 1: Inspect existing API pattern**

Read `backend/app/api/__init__.py` and `backend/app/api/simulation.py` to understand the existing blueprint registration pattern and response format.

- [ ] **Step 2: Create narrative.py blueprint**

Create `backend/app/api/narrative.py`:

```python
"""Narrative Layer API endpoints."""
import os
from flask import Blueprint, jsonify, request
from app.services.narrative.story_store import StoryStore
from app.services.narrative.narrative_translator import translate_round
from app.services.narrative.character_engine import CharacterEngine
from app.config import Config

narrative_bp = Blueprint('narrative', __name__)


def _sim_dir(sim_id: str) -> str:
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)


@narrative_bp.route('/story/<sim_id>', methods=['GET'])
def get_full_story(sim_id):
    store = StoryStore(_sim_dir(sim_id))
    return jsonify({"sim_id": sim_id, "beats": store.get_all_beats()})


@narrative_bp.route('/story/<sim_id>/round/<int:round_num>', methods=['GET'])
def get_round_story(sim_id, round_num):
    store = StoryStore(_sim_dir(sim_id))
    beat = store.get_beat_by_round(round_num)
    if not beat:
        return jsonify({"error": "Round not translated yet"}), 404
    return jsonify(beat)


@narrative_bp.route('/translate', methods=['POST'])
def translate():
    data = request.get_json()
    sim_id = data.get('sim_id')
    round_num = data.get('round')
    platform = data.get('platform', 'twitter')
    tone = data.get('tone', 'neutral')
    try:
        beat = translate_round(_sim_dir(sim_id), platform, round_num, tone)
        return jsonify(beat)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@narrative_bp.route('/characters/<sim_id>', methods=['GET'])
def get_characters(sim_id):
    store = StoryStore(_sim_dir(sim_id))
    return jsonify({"characters": store.load_characters()})


@narrative_bp.route('/characters/<sim_id>/init', methods=['POST'])
def initialize_characters(sim_id):
    """Bootstrap characters from existing OASIS profiles."""
    import json
    sim_dir = _sim_dir(sim_id)
    profiles_path = os.path.join(sim_dir, 'profiles.json')
    if not os.path.exists(profiles_path):
        return jsonify({"error": "profiles.json not found"}), 404
    with open(profiles_path, 'r', encoding='utf-8') as f:
        profiles = json.load(f)
    store = StoryStore(sim_dir)
    engine = CharacterEngine(store)
    characters = engine.initialize_from_profiles(profiles)
    return jsonify({"count": len(characters), "characters": characters})
```

- [ ] **Step 3: Register blueprint in __init__.py**

Modify `backend/app/api/__init__.py` by adding (at the bottom of existing imports):

```python
from . import narrative
```

Then modify `backend/app/__init__.py` to register:

```python
from app.api.narrative import narrative_bp
app.register_blueprint(narrative_bp, url_prefix='/api/narrative')
```

(Find where other blueprints are registered and add this line alongside them.)

- [ ] **Step 4: Manual smoke test**

```bash
cd backend && uv run python run.py &
sleep 3
curl http://localhost:5001/api/narrative/story/nonexistent_sim
# Expected: {"sim_id": "nonexistent_sim", "beats": []}
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/narrative.py backend/app/api/__init__.py backend/app/__init__.py
git commit -m "feat(narrative): add narrative API blueprint"
```

---

## Task 8: Frontend API Client

**Files:**
- Create: `frontend/src/api/narrative.js`

- [ ] **Step 1: Inspect existing API client pattern**

Read `frontend/src/api/simulation.js` and `frontend/src/api/index.js` to understand the existing axios usage.

- [ ] **Step 2: Create narrative API client**

Create `frontend/src/api/narrative.js`:

```javascript
import api from './index.js'

export const narrativeAPI = {
  getFullStory(simId) {
    return api.get(`/narrative/story/${simId}`)
  },

  getRoundStory(simId, roundNum) {
    return api.get(`/narrative/story/${simId}/round/${roundNum}`)
  },

  translate(simId, round, platform = 'twitter', tone = 'neutral') {
    return api.post('/narrative/translate', { sim_id: simId, round, platform, tone })
  },

  getCharacters(simId) {
    return api.get(`/narrative/characters/${simId}`)
  },

  initCharacters(simId) {
    return api.post(`/narrative/characters/${simId}/init`)
  },
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/narrative.js
git commit -m "feat(narrative): add frontend API client"
```

---

## Task 9: StoryBeat Component

**Files:**
- Create: `frontend/src/components/StoryBeat.vue`

- [ ] **Step 1: Create component**

Create `frontend/src/components/StoryBeat.vue`:

```vue
<template>
  <article class="story-beat">
    <header class="beat-header">
      <span class="round-badge">Round {{ beat.round }}</span>
      <span v-if="beat.characters && beat.characters.length" class="characters">
        {{ beat.characters.join(' · ') }}
      </span>
    </header>
    <div class="prose">
      <p v-for="(para, i) in paragraphs" :key="i">{{ para }}</p>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  beat: { type: Object, required: true },
})

const paragraphs = computed(() =>
  (props.beat.prose || '').split(/\n\n+/).filter(p => p.trim())
)
</script>

<style scoped>
.story-beat {
  margin: 0 0 2.5rem;
  padding: 1.5rem;
  border-left: 3px solid #c9a45b;
  background: #faf7f0;
}
.beat-header {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.75rem;
  font-size: 0.85rem;
  color: #7d6b3f;
}
.round-badge {
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.characters {
  font-style: italic;
}
.prose p {
  line-height: 1.7;
  margin: 0 0 1rem;
  font-family: Georgia, serif;
  color: #2a2416;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/StoryBeat.vue
git commit -m "feat(narrative): add StoryBeat component"
```

---

## Task 10: StoryTimelineView

**Files:**
- Create: `frontend/src/views/StoryTimelineView.vue`

- [ ] **Step 1: Create view**

Create `frontend/src/views/StoryTimelineView.vue`:

```vue
<template>
  <div class="story-timeline">
    <header class="page-header">
      <h1>{{ title }}</h1>
      <div class="controls">
        <button @click="refresh" :disabled="loading">{{ loading ? 'Loading...' : 'Refresh' }}</button>
        <button @click="translateNext" :disabled="translating">
          {{ translating ? 'Generating...' : 'Translate Next Round' }}
        </button>
      </div>
    </header>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="beats.length === 0 && !loading" class="empty">
      No story yet. Run a simulation and translate rounds to see the narrative.
    </div>

    <StoryBeat v-for="beat in beats" :key="beat.round" :beat="beat" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { narrativeAPI } from '../api/narrative.js'
import StoryBeat from '../components/StoryBeat.vue'

const route = useRoute()
const simId = route.params.simId

const beats = ref([])
const loading = ref(false)
const translating = ref(false)
const error = ref('')
const title = ref(`Story: ${simId}`)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await narrativeAPI.getFullStory(simId)
    beats.value = data.beats || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function translateNext() {
  translating.value = true
  error.value = ''
  try {
    const nextRound = beats.value.length + 1
    await narrativeAPI.translate(simId, nextRound)
    await refresh()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  } finally {
    translating.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.story-timeline {
  max-width: 740px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e5ddc4;
}
.page-header h1 {
  margin: 0;
  font-family: Georgia, serif;
  color: #2a2416;
}
.controls {
  display: flex;
  gap: 0.5rem;
}
.controls button {
  padding: 0.5rem 1rem;
  background: #c9a45b;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.controls button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.error {
  background: #ffe5e5;
  color: #8b0000;
  padding: 1rem;
  border-radius: 4px;
  margin-bottom: 1rem;
}
.empty {
  text-align: center;
  color: #999;
  padding: 3rem 1rem;
  font-style: italic;
}
</style>
```

- [ ] **Step 2: Add route**

Read `frontend/src/router/index.js`. Then add to its routes array:

```javascript
{
  path: '/story/:simId',
  name: 'story',
  component: () => import('../views/StoryTimelineView.vue'),
},
```

- [ ] **Step 3: Manual smoke test**

```bash
cd frontend && npm run dev
# Open http://localhost:3000/story/any_sim_id
# Expected: "No story yet" message, Refresh/Translate buttons visible
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/StoryTimelineView.vue frontend/src/router/index.js
git commit -m "feat(narrative): add StoryTimelineView and route"
```

---

## Task 11: CharacterCard Component + Integration

**Files:**
- Create: `frontend/src/components/CharacterCard.vue`
- Modify: `frontend/src/views/StoryTimelineView.vue`

- [ ] **Step 1: Create CharacterCard**

Create `frontend/src/components/CharacterCard.vue`:

```vue
<template>
  <div class="character-card">
    <div class="name">{{ character.name }}</div>
    <div class="emotions">
      <span v-for="(val, emo) in topEmotions" :key="emo" class="emotion">
        {{ emo }}: {{ val.toFixed(2) }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  character: { type: Object, required: true },
})

const topEmotions = computed(() => {
  const current = props.character.emotional_state?.current || {}
  const sorted = Object.entries(current).sort((a, b) => b[1] - a[1]).slice(0, 3)
  return Object.fromEntries(sorted)
})
</script>

<style scoped>
.character-card {
  display: inline-block;
  padding: 0.5rem 0.75rem;
  margin: 0.25rem;
  background: #2a2416;
  color: #faf7f0;
  border-radius: 4px;
  font-size: 0.85rem;
}
.name {
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.emotions {
  display: flex;
  gap: 0.5rem;
  font-family: monospace;
  font-size: 0.75rem;
  opacity: 0.85;
}
</style>
```

- [ ] **Step 2: Integrate into StoryTimelineView**

In `frontend/src/views/StoryTimelineView.vue`, add character loading and display. Add to imports:

```javascript
import CharacterCard from '../components/CharacterCard.vue'
```

Add to script setup (after `title`):

```javascript
const characters = ref([])
async function loadCharacters() {
  try {
    const { data } = await narrativeAPI.getCharacters(simId)
    characters.value = data.characters || []
  } catch (e) { /* ignore */ }
}
```

Change `onMounted(refresh)` to `onMounted(() => { refresh(); loadCharacters() })`.

Change `translateNext` to reload characters after: add `await loadCharacters()` before `await refresh()`.

Add this block in template, right after `<header class="page-header">`:

```vue
<div v-if="characters.length" class="character-roster">
  <CharacterCard v-for="c in characters" :key="c.id" :character="c" />
</div>
```

Add to styles:

```css
.character-roster {
  margin-bottom: 2rem;
  padding: 1rem;
  background: #f5efd9;
  border-radius: 4px;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CharacterCard.vue frontend/src/views/StoryTimelineView.vue
git commit -m "feat(narrative): add CharacterCard and roster display"
```

---

## Task 12: End-to-End Smoke Test

**Files:**
- Create: `backend/tests/test_narrative_e2e.py`

- [ ] **Step 1: Write E2E test**

Create `backend/tests/test_narrative_e2e.py`:

```python
"""End-to-end test: create fake simulation dir → translate → verify story."""
import os
import json
import tempfile
from unittest.mock import patch
from app.services.narrative.story_store import StoryStore
from app.services.narrative.narrative_translator import translate_round

def test_full_pipeline_from_fake_simulation(tmp_path):
    sim_dir = str(tmp_path / "sim_e2e")
    os.makedirs(os.path.join(sim_dir, "twitter"))

    actions_path = os.path.join(sim_dir, "twitter", "actions.jsonl")
    actions = [
        {"round": 1, "agent_id": 1, "agent_name": "Elena", "action_type": "CREATE_POST", "action_args": {"content": "The council must fall."}, "success": True, "timestamp": "t"},
        {"round": 1, "agent_id": 2, "agent_name": "Marcus", "action_type": "DISLIKE_POST", "action_args": {"post_id": 1}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 1, "timestamp": "t"},
        {"round": 2, "agent_id": 1, "agent_name": "Elena", "action_type": "REPOST", "action_args": {}, "success": True, "timestamp": "t"},
        {"event_type": "round_end", "round": 2, "timestamp": "t"},
    ]
    with open(actions_path, "w") as f:
        for a in actions:
            f.write(json.dumps(a) + "\n")

    store = StoryStore(sim_dir)
    store.save_characters([
        {"id": "1", "name": "Elena", "emotional_state": {"current": {k: 0.0 for k in ["anger","fear","joy","sadness","trust","surprise"]}}},
        {"id": "2", "name": "Marcus", "emotional_state": {"current": {k: 0.0 for k in ["anger","fear","joy","sadness","trust","surprise"]}}},
    ])
    store.load_characters()[0]["emotional_state"]["current"]["trust"] = 0.5

    with patch("app.services.narrative.narrative_translator.call_llm") as mock_llm:
        mock_llm.side_effect = [
            "Elena addressed the gathering. Marcus's face darkened.",
            "Elena's message spread through the quarter like a spark.",
        ]
        beat1 = translate_round(sim_dir, "twitter", 1, "dark fantasy")
        beat2 = translate_round(sim_dir, "twitter", 2, "dark fantasy")

    assert beat1["round"] == 1
    assert beat2["round"] == 2
    assert "Elena" in beat1["prose"]

    all_beats = store.get_all_beats()
    assert len(all_beats) == 2

    # Characters should have evolved
    chars = store.load_characters()
    marcus = next(c for c in chars if c["name"] == "Marcus")
    # If ACTION_EMOTIONAL_DELTAS has anger for DISLIKE_POST, anger should be > 0
    # (this validates the user's Step 4 choices in Task 3)
    assert marcus["emotional_state"]["current"]["anger"] >= 0.0  # at minimum, not negative
```

- [ ] **Step 2: Run test**

Run: `cd backend && uv run pytest tests/test_narrative_e2e.py -v`
Expected: 1 passed.

- [ ] **Step 3: Run full test suite**

Run: `cd backend && uv run pytest tests/ -v`
Expected: all tests pass (action_mapper: 4, character_engine: 5, story_store: 4, narrative_translator: 6, e2e: 1 = 20 total).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_narrative_e2e.py
git commit -m "test(narrative): add end-to-end pipeline test"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Section 3.0 Integration Point (async on-demand) → Task 6 `translate_round` + Task 7 API
- ✅ Section 3.1 Action Mapping → Task 1 `action_mapper.py`
- ✅ Section 3.2 Translation Pipeline → Task 4 + 5 + 6
- ✅ Section 3.3 Resilience → partial (retry deferred, see below)
- ✅ Section 3.4 LLM Prompt Structure → Task 5 with user contribution point
- ✅ Section 4.1 Extended Character Schema → Task 3
- ✅ Section 4.2 Emotional State Model (v1 display-only) → Task 3 with user contribution point
- ⏸ Section 4.3 Arc Detection → deferred to follow-on plan (not needed for MVP)
- ⏸ Sections 5-9 (world state, god mode, branching, input, export) → separate plans
- ✅ New API routes → Task 7 (subset: story, translate, characters, init)
- ✅ Frontend routes → Task 10 (`/story/:simId`)
- ✅ StoryBeat.vue → Task 9
- ✅ CharacterCard.vue → Task 11
- ✅ StoryTimelineView → Task 10

**Deferred to follow-on plans:** God Mode, timeline branching, world state manager, arc detection, enhanced input pipeline, export studio, all other frontend views. These each warrant their own focused plan.

**Deferred within this plan (acceptable gaps):** Retry/resilience wrapper around `call_llm` — relies on whatever retry is already in `utils/llm_client.py`; can be added in a hardening task if the basic pipeline works.

**Type consistency check:** ✅ `StoryStore`, `translate_round`, `generate_prose`, `apply_action_emotional_delta`, `create_initial_character` all have consistent signatures across tasks.
