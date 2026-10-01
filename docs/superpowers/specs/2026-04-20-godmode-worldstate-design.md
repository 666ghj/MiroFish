# God Mode + World State — Minimal v1 Design Specification

**Date:** 2026-04-20
**Builds on:** `2026-03-26-narrative-layer-design.md` (sections 5–6)
**Target:** Author-controlled story intervention + world grounding
**Scope:** 3 God Mode actions + 3 World State features, file-based only

---

## 1. Problem

The Narrative Layer generates prose from OASIS simulation output, but the author has no way to intervene mid-story or ground scenes in a coherent world. This is a creative platform, not a passive spectator tool — authors need levers.

**v1 goal:** Ship the three highest-leverage intervention levers and the three highest-leverage world grounding primitives, without modifying the OASIS simulation engine.

---

## 2. Scope

### In scope
**God Mode interventions (3):**
1. **Inject world event** — append a user-described event to the world event log; subsequent prose generations reference it
2. **Modify character emotional state** — directly set emotion values in `characters.json`
3. **Kill character** — mark a character as `status: "dead"`; filtered from future translations

**World State (3):**
1. **Locations** — named places with descriptions; characters can have a current `location`
2. **World rules** — list of background rules / constraints (genre, laws, era)
3. **Event log** — chronological record of world-level events, populated automatically by God Mode event injections

### Explicitly out of scope (deferred to v2+)
- Agent-side event propagation (the OASIS simulation doesn't "see" injected events — only the prose layer does)
- World rule changes mid-simulation via OASIS prompt injection
- Factions, resources, timeline branching
- Force action, resurrect character, time skip

### Why file-based only
The existing OASIS subprocess has no `INJECT_CONTEXT` IPC command. Adding one requires touching the OASIS runner scripts, which introduces simulation coupling we don't need for creative storytelling. v1 God Mode is a **story-layer intervention system** — it shapes what the author reads, not what agents do. The author injects an earthquake; the next prose paragraph starts "A tremor ran through the city…" The agents keep posting about whatever they were already posting about. This is a feature, not a bug: it means authors can introduce "unreliable narrator" events that exist only in the prose.

---

## 3. Architecture

### 3.1 New files

**Backend services:**
| File | Responsibility |
|---|---|
| `backend/app/services/narrative/world_state.py` | CRUD for world_state.json (locations, rules, event log) |
| `backend/app/services/narrative/god_mode.py` | 3 intervention handlers; writes to world_state and characters |
| `backend/tests/test_world_state.py` | Unit tests for world CRUD |
| `backend/tests/test_god_mode.py` | Unit tests for interventions |

**Backend API (modifies existing):**
| File | Change |
|---|---|
| `backend/app/api/narrative.py` | +6 endpoints (3 world, 3 god mode) |

**Backend translator (modifies existing):**
| File | Change |
|---|---|
| `backend/app/services/narrative/narrative_translator.py` | Extend prompt to surface world rules, recent events, character locations; filter dead characters |

**Frontend:**
| File | Responsibility |
|---|---|
| `frontend/src/api/narrative.js` | +6 named exports for new endpoints |
| `frontend/src/views/WorldBuilderView.vue` | Locations + rules + event log UI |
| `frontend/src/views/GodModeView.vue` | 3 action forms |
| `frontend/src/router/index.js` | +2 routes |

### 3.2 Data model

New file per simulation: `uploads/simulations/{sim_id}/narrative/world_state.json`

```json
{
  "sim_id": "sim_abc123",
  "rules": [
    "The kingdom is in civil war",
    "Magic is feared but not forbidden",
    "Winter will arrive in 10 rounds"
  ],
  "locations": {
    "iron_tower": {
      "id": "iron_tower",
      "name": "The Iron Tower",
      "description": "A brutal spire of black stone at the city's heart."
    },
    "market": {
      "id": "market",
      "name": "The Old Market",
      "description": "Narrow stalls under fraying canvas. Always crowded."
    }
  },
  "event_log": [
    {
      "id": "evt_001",
      "round": 3,
      "type": "god_mode_injection",
      "description": "A stranger arrived at the market, carrying a sealed letter.",
      "injected_at": "2026-04-20T14:22:00Z"
    }
  ]
}
```

**Character schema extension** (`characters.json`) — adds two optional fields:

```json
{
  "id": "1",
  "name": "Elena",
  "emotional_state": {...},
  "status": "alive",          // NEW — "alive" | "dead"
  "location": "iron_tower"    // NEW — optional, references world_state.locations
}
```

Existing characters without these fields default to `status: "alive"` and no location — backward compatible.

### 3.3 API endpoints

All under `/api/narrative/*` prefix (reusing existing `narrative_bp`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/world/<sim_id>` | Return full world_state.json |
| `POST` | `/world/<sim_id>/rules` | Set world rules (body: `{rules: [string]}`) |
| `POST` | `/world/<sim_id>/locations` | Upsert a location (body: `{id, name, description}`) |
| `POST` | `/godmode/<sim_id>/inject-event` | Inject a world event (body: `{description, round?}`) |
| `POST` | `/godmode/<sim_id>/modify-emotion` | Set emotion values (body: `{character_id, emotions: {anger: 0.8, ...}}`) |
| `POST` | `/godmode/<sim_id>/kill` | Mark character dead (body: `{character_id}`) |

---

## 4. God Mode handlers

### 4.1 Inject event
```python
def inject_event(sim_dir: str, description: str, round_num: int | None = None) -> dict:
    """Append a new event to world_state.event_log.

    If round_num is None, uses current round (last translated beat's round + 1,
    or 1 if no beats yet).
    """
```
- Generates unique `id = evt_{n}` where n is `len(event_log) + 1`
- Returns the event dict

### 4.2 Modify emotion
```python
def modify_emotion(sim_dir: str, character_id: str, emotions: dict[str, float]) -> dict:
    """Overwrite specified emotion values for a character.

    Clamps to [0.0, 1.0]. Only modifies emotions named in the input dict;
    unspecified emotions keep their current values. Unknown emotion keys
    are silently ignored.
    """
```
- Reads `characters.json`, finds character by `id`, applies overwrites
- Raises `ValueError("character not found")` if `character_id` doesn't match
- **Audit logging:** appends a `{"type": "god_mode_emotion_change", ...}` entry to `world_state.event_log` so the intervention is visible in the world event log UI

### 4.3 Kill character
```python
def kill_character(sim_dir: str, character_id: str) -> dict:
    """Mark character as dead. Future translations ignore their actions."""
```
- Sets `status = "dead"` on the target character
- Translation pipeline filters dead characters from the characters list passed to LLM prompt, and ignores any actions with matching agent names
- **Auto-appends a death event** to `world_state.event_log`: `{"type": "god_mode_death", "description": "{name} has died.", "round": current_round}` where `current_round` is defined as "last translated beat's round + 1, or 1 if no beats yet" (same rule `inject_event` uses). This guarantees the LLM knows the character is gone rather than silently omitting them — preventing "character vanishes mid-story" narrative bugs.
- Raises `ValueError("character not found")` if `character_id` doesn't match

### 4.4 Concurrency note

God Mode writes to `characters.json` while background translation may also be reading/writing it. This is a classic read-modify-write race: if `translate_round` is mid-LLM-call when the user POSTs `/kill`, the subsequent save may overwrite the kill. **For v1 (single-user, 10–50 user scale), this is an accepted limitation, not a bug.** Authors are expected to intervene between rounds, not during. This constraint is documented in §10 non-goals. File-locking can be added in a follow-up if needed.

---

## 5. Translator prompt extension

### 5.0 Integration — how the translator loads world state

`translate_round` is extended to load `world_state.json` internally via a new `WorldStateStore.load(sim_dir)` (parallel to how it uses `StoryStore.load_characters()` today). If the file doesn't exist, load returns an empty world (`{"rules": [], "locations": {}, "event_log": []}`) — existing simulations without a world state continue to work unchanged.

**Event round semantics:** every event in `event_log` has a `round` field, but this is **metadata only** (used for UI display and prompt formatting as `"(Round N)"`). `event_log` is append-only — the last element in the list is always the newest. The translator always surfaces the *last 3 events by insertion order*, regardless of their round. `event.round` is never used as a filter.

**Lookup key discipline:** characters are keyed by both `id` (stable string like `"1"`) and `name` (display string like `"Elena"`). The canonical conventions are:
- God Mode API endpoints always take `character_id` (the `id` field) in request bodies.
- Internal handlers resolve `character_id → name` once and use `name` downstream for alive/dead filtering and action-log matching (since `actions.jsonl` stores `agent_name`, not id).
- Location `id` (`"iron_tower"`) is stored on characters as `character.location`. The translator resolves `id → location.name` once when building the prompt — characters in the prose prompt read as "Elena (at The Iron Tower, feeling: anger=0.3, trust=0.1)".

Current prompt has substitution fields: `{tone}`, `{characters}`, `{actions}`, `{previous}`.

Add 3 new fields: `{world_rules}`, `{world_events}`, `{world_locations}`.

**Prompt injection safety:** user-supplied strings (rules, event descriptions, location names/descriptions) are free-text and may contain `{` or `}`. Before rendering with `str.format()`, these strings are escaped: `{` → `{{`, `}` → `}}`. This prevents `KeyError` from stray braces in author content.

**New prompt sections inserted before "Events this round":**

```
World grounding:
  Rules: {world_rules}
  Recent events: {world_events}
  Known locations: {world_locations}
```

- `{world_rules}` is a bulleted list joined with `; `
- `{world_events}` is the last 3 events from `event_log`, each as `"(Round N) description"`
- `{world_locations}` is a `name — description` list, capped at 5

The prompt also gets one new instruction in the CINEMATIC DETAIL section:

```
- If a character has a known location, root the scene there.
- If a recent world event is listed, weave it in OR acknowledge its aftermath — do not ignore it.
```

### 5.1 Filtering dead characters

In `translate_round`, before building `characters` and `actions` lists:

```python
alive = {c["name"] for c in characters if c.get("status", "alive") != "dead"}
characters = [c for c in characters if c["name"] in alive]
actions = [a for a in actions if a.get("agent_name") in alive]
```

Dead characters are invisible to the LLM — no prose is generated about them unless the event log contains their death (which is auto-populated by `kill_character` — see §4.3). The alive-filter applies only to the roster and action list passed into the prompt; there is no separate "observing" inference in the committed code today, so no other code paths need adjustment.

**Backward compatibility:** `create_initial_character()` is updated to set `status: "alive"` on every new character. Existing saved characters without a `status` field are treated as alive via the `c.get("status", "alive")` default.

---

## 6. Frontend

### 6.1 GodModeView.vue

Three card-style forms, visually distinct:

```
┌──────────────────────────────────┐
│  ⚡ Inject World Event           │
│  [textarea: event description]   │
│  [input: round (optional)]       │
│  [Inject button]                 │
│  Last 3 events shown below       │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  💭 Modify Character Emotions    │
│  [select: character dropdown]    │
│  [6 sliders: anger/fear/joy/...] │
│  [Apply button]                  │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  ☠ Kill Character                │
│  [select: character dropdown]    │
│  [Confirm checkbox] [Kill button]│
│  Warning: removes from future    │
│  story. Cannot be undone in v1.  │
└──────────────────────────────────┘
```

Uses existing `CharacterCard.vue` for selection preview.

### 6.2 WorldBuilderView.vue

Three sections:

1. **Rules** — editable textarea, one rule per line, Save button
2. **Locations** — list of existing locations + "Add location" form
3. **Event log** — read-only scrollable list (for now; events are added only via God Mode)

### 6.3 Routes

Added to `frontend/src/router/index.js`:

```javascript
{ path: '/godmode/:simulationId', name: 'GodMode', component: GodModeView, props: true },
{ path: '/world/:simulationId', name: 'World', component: WorldBuilderView, props: true }
```

### 6.4 Navigation

A small cross-view nav is added to **all three views** (`StoryTimelineView`, `GodModeView`, `WorldBuilderView`) as a shared header strip — the links show the current route as active:

```
Story | God Mode | World
```

Implementation: extracted into a small `<SimNav :simId="simId" />` component (not a separate file unless it grows — inline in each view is fine for v1) to avoid app-level layout changes.

### 6.5 Kill confirmation UX

The spec upgrades the Kill Character form beyond a checkbox: the user must **type the character's name** to enable the Kill button. This matches the GitHub-style pattern for irreversible destructive actions and eliminates misclicks. The input is case-insensitive and whitespace-trimmed.

---

## 7. Error handling

- **Missing character**: handler raises `ValueError("character not found")`; API returns 404 with `{"error": "character not found"}`
- **Missing simulation**: API returns 404 (reuses existing pattern from Task 7)
- **Invalid emotion name**: silently ignored (extra emotion keys don't break anything; they just don't affect state)
- **Inject event before translation starts**: event is stored with `round: 0` and included in the first beat's prompt
- **Invalid round number on inject_event**: API validates `round` is a non-negative integer (or null); otherwise returns 400

---

## 8. Testing

**Unit tests** (`tests/test_world_state.py`):
- `test_world_state_empty_on_fresh_sim`
- `test_add_location_persists`
- `test_set_rules_replaces_previous`
- `test_append_event_auto_ids`

**Unit tests** (`tests/test_god_mode.py`):
- `test_inject_event_appends_to_log`
- `test_modify_emotion_clamps_and_preserves_others`
- `test_kill_character_sets_status`
- `test_kill_character_not_found_raises`

**Integration** (extend `test_narrative_e2e.py`):
- Inject an event between round 1 and round 2, verify the event appears in the round-2 prompt context (assert via `mock_llm.call_args[0][0]`)
- Kill a character between rounds, verify their actions are skipped in the next translation
- Set world rules + locations, verify they appear in the prompt

**Prompt-inclusion unit test** (in `test_narrative_translator.py`):
- Patch `call_llm`, call `translate_round` with a populated world_state, assert the captured prompt contains each rule, each event description, and each location name. This prevents silent regressions in §5 formatting.

---

## 9. User contribution points

Same learning-mode pattern as before — two places the author's creative judgment matters more than an LLM's guess.

### 9.1 Event injection prompt enforcement

When God Mode injects an event, the prose prompt will include it in "Recent events." The prompt currently says "weave it in OR acknowledge its aftermath — do not ignore it." User decides **how strong** this instruction should be:

- **Soft**: "consider referencing the event if it fits"
- **Medium**: current default — "weave it in OR acknowledge its aftermath"
- **Hard**: "the opening line of this passage MUST reference the most recent world event"

Marked as `EVENT_ENFORCEMENT_STRENGTH` module-level constant in `narrative_translator.py`. Note: this is a **deployment-global** setting in v1, not per-simulation. Per-sim overrides are a v2 concern (would move this to `world_state.json`).

### 9.2 Location schema

Whether locations need fields beyond `name + description`. Options:
- **Minimal** (default): just `name + description`
- **Cinematic**: add `atmosphere` (a mood phrase like "oppressive silence, dust motes in shafts of light")
- **Temporal**: add `time_of_day` ("dusk", "midnight")
- **Full**: all of the above

Marked clearly in `world_state.py` as scaffolded default, with a TODO comment pointing to user contribution.

---

## 10. Non-goals

- Mid-simulation OASIS prompt injection (deferred to v2)
- Resurrection, time skip, forced action
- Faction system, resource system
- Location transitions (characters moving between locations during a round) — v1 locations are static per-character
- Bulk intervention (applying to multiple characters at once)
- Undo / history — God Mode actions are one-way in v1
- **No delete endpoints** for locations, rules (they're replaced in bulk via the POST endpoint), or events. An author who mis-types must manually edit `world_state.json`.
- **Concurrent write safety** — authors should intervene between rounds, not during (see §4.4). No file locking in v1.
- **Event log rotation** — `event_log` grows unbounded. Fine at expected v1 scale (tens of events per sim); pruning can be added in v2.
- **Per-simulation event enforcement strength** — `EVENT_ENFORCEMENT_STRENGTH` is deployment-global in v1 (§9.1).
