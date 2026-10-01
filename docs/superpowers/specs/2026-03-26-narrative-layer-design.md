# MiroFish Narrative Layer — Design Specification

**Date:** 2026-03-26
**Approach:** A — Narrative Layer on top of existing OASIS simulation
**Target:** Creative simulation engine (novel continuation, world-building, interactive fiction)
**Scale:** Small community (10–50 users), basic auth, moderate concurrency

---

## 1. Problem Statement

MiroFish is a multi-agent swarm intelligence engine built for prediction — it simulates social media interactions (Twitter/Reddit) to forecast outcomes. The simulation infrastructure (OASIS engine, Zep graph memory, LLM-driven agents) is powerful but locked into a social-media metaphor.

**Goal:** Extend MiroFish into a creative storytelling platform where users can upload fiction, define worlds, and watch AI agents generate emergent narratives — without replacing the proven OASIS simulation backbone.

**Key insight:** Social media actions map naturally to narrative actions. A "post" is speech. A "like" is agreement. A "repost" is rumor-spreading. By adding a translation layer, we reinterpret simulation output as story prose.

---

## 2. Architecture

### 2.1 System Diagram

```
┌──────────────────────────────────────────────────────┐
│                    Frontend (Vue 3)                   │
│  ┌────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ Story       │ │ Character    │ │ God Mode       │  │
│  │ Timeline    │ │ Workshop     │ │ Control Panel  │  │
│  └────────────┘ └──────────────┘ └────────────────┘  │
│  ┌────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │ World       │ │ Branching    │ │ Export         │  │
│  │ Map View   │ │ Timeline     │ │ Studio         │  │
│  └────────────┘ └──────────────┘ └────────────────┘  │
├──────────────────────────────────────────────────────┤
│                 Narrative Engine (NEW)                │
│  ┌──────────────────────────────────────────────┐    │
│  │ Narrative Translator                          │    │
│  │  - Action → Story Event mapping               │    │
│  │  - Emotional state tracking                   │    │
│  │  - Plot arc detection                         │    │
│  └──────────────────────────────────────────────┘    │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────┐   │
│  │ Character   │ │ World State  │ │ Timeline     │   │
│  │ Engine      │ │ Manager      │ │ Brancher     │   │
│  └─────────────┘ └──────────────┘ └─────────────┘   │
├──────────────────────────────────────────────────────┤
│              Existing MiroFish Backend               │
│  Graph Builder → OASIS Simulation → Report Agent     │
│  Zep Memory    → Profile Generator → LLM Client     │
└──────────────────────────────────────────────────────┘
```

### 2.2 New Backend Services

All new services live in `backend/app/services/narrative/` to keep the existing codebase untouched.

| Service | File | Purpose |
|---|---|---|
| Narrative Translator | `narrative_translator.py` | Converts OASIS actions into story prose via LLM |
| Character Engine | `character_engine.py` | Manages extended character profiles (backstory, emotions, arcs) |
| World State Manager | `world_state.py` | Tracks locations, factions, resources, world rules |
| Timeline Brancher | `timeline_brancher.py` | Snapshots and forks simulation state |
| Seed Enhancer | `seed_enhancer.py` | Processes EPUB/DOCX/templates into MiroFish seeds |
| Export Studio | `export_studio.py` | Generates EPUB, screenplay, chapter formats |

### 2.3 New API Routes

New route blueprint: `narrative_bp = Blueprint('narrative', __name__)` in `backend/app/api/narrative.py`. Register in `backend/app/__init__.py` via `app.register_blueprint(narrative_bp, url_prefix='/api/narrative')`. Import added to `backend/app/api/__init__.py`.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/narrative/translate` | Translate a simulation round into story prose |
| GET | `/api/narrative/story/{sim_id}` | Get full story for a simulation |
| GET | `/api/narrative/story/{sim_id}/round/{round}` | Get story for a specific round |
| POST | `/api/narrative/characters` | Create/update extended character profiles |
| GET | `/api/narrative/characters/{sim_id}` | Get all characters with emotional states |
| GET | `/api/narrative/characters/{sim_id}/{char_id}` | Get single character detail |
| POST | `/api/narrative/world` | Create/update world state |
| GET | `/api/narrative/world/{sim_id}` | Get current world state |
| POST | `/api/narrative/godmode/inject` | Inject an event into a running simulation |
| POST | `/api/narrative/godmode/modify-character` | Modify character state mid-simulation |
| POST | `/api/narrative/godmode/change-rules` | Change world rules mid-simulation |
| POST | `/api/narrative/branch/{sim_id}/{round}` | Fork timeline at a specific round |
| GET | `/api/narrative/branches/{sim_id}` | List all branches for a simulation |
| POST | `/api/narrative/export/{sim_id}` | Export story in specified format |
| GET | `/api/narrative/export/{sim_id}/status` | Check export generation status |

### 2.4 New Frontend Views

| View | File | Purpose |
|---|---|---|
| Story Timeline | `views/StoryTimelineView.vue` | Read the generated narrative chapter by chapter |
| Character Workshop | `views/CharacterWorkshopView.vue` | Create, edit, and browse characters |
| World Builder | `views/WorldBuilderView.vue` | Define locations, factions, rules |
| God Mode | `views/GodModeView.vue` | Control panel for mid-simulation intervention |
| Branch Explorer | `views/BranchExplorerView.vue` | Visual timeline tree, compare branches |
| Export Studio | `views/ExportStudioView.vue` | Choose format, preview, download |

### 2.6 Frontend Routes

| Route | View | Description |
|---|---|---|
| `/story/:simId` | StoryTimelineView | Read generated narrative |
| `/characters/:simId` | CharacterWorkshopView | Create and browse characters |
| `/world/:simId` | WorldBuilderView | Define world settings |
| `/godmode/:simId` | GodModeView | Mid-simulation controls |
| `/branches/:simId` | BranchExplorerView | Timeline tree and comparison |
| `/export/:simId` | ExportStudioView | Format and download stories |

Routes are added to `frontend/src/router/index.js` following the existing pattern of `/:simulationId` parameterized routes.

### 2.5 New Frontend Components

| Component | Purpose |
|---|---|
| `StoryBeat.vue` | Single story event/paragraph with character attribution |
| `CharacterCard.vue` | Character portrait with stats, emotions, relationships |
| `RelationshipGraph.vue` | Visual graph of character relationships (D3.js) |
| `EmotionTracker.vue` | Per-character emotional state over time (sparkline) |
| `WorldMap.vue` | Visual map of locations and character positions |
| `TimelineTree.vue` | Branching timeline visualization |
| `GodModeToolbar.vue` | Floating toolbar for injecting events |
| `ExportPreview.vue` | Preview formatted output before download |

---

## 3. Narrative Translator — Core Logic

### 3.0 Integration Point — How the Narrative Layer Connects to OASIS

The existing OASIS simulation runs as a subprocess that writes actions to `actions.jsonl` (one JSON line per agent action per round). The existing `_monitor_simulation` method in `SimulationRunner` already polls this file every 2 seconds, tracking file position to read only new lines.

**Narrative translation is asynchronous and on-demand.** The Narrative Translator does NOT hook into the simulation loop. Instead:

1. **During simulation:** The existing `_monitor_simulation` continues reading `actions.jsonl` as-is. No changes to the simulation runner.
2. **After each round completes:** The frontend polls a new endpoint `GET /api/narrative/story/{sim_id}/latest` which triggers translation of any untranslated rounds.
3. **Translation reads `actions.jsonl`** directly, maintaining its own file offset in `narrative/translator_state.json`. It reads actions for the next untranslated round, generates prose, and stores the result.
4. **Batch translation** is also available via `POST /api/narrative/translate` for retroactively translating a completed simulation.

**Why on-demand (not in-loop):** LLM prose generation takes 2-5 seconds per scene. Injecting this into the simulation monitor would slow round processing by 10-20x. By decoupling translation, the simulation runs at full speed and narrative is generated as users view it.

**IPC for God Mode:** The existing `SimulationIPCClient` supports file-based IPC with `INTERVIEW`, `BATCH_INTERVIEW`, and `CLOSE_ENV` commands. God Mode leverages `INTERVIEW` to inject custom prompts into running agents (see Section 6). New IPC command types (`INJECT_EVENT`, `MODIFY_AGENT_PROMPT`) will be added to `SimulationIPCServer` and the OASIS runner scripts.

### 3.1 Action Mapping

| OASIS Action | Narrative Interpretation |
|---|---|
| `CREATE_POST` | Character speaks, declares, announces |
| `LIKE_POST` | Character agrees, supports, nods |
| `REPOST` | Character spreads rumor, amplifies, gossips |
| `QUOTE_POST` | Character responds, debates, challenges |
| `FOLLOW` | Character allies with, shows loyalty to |
| `DO_NOTHING` | Character reflects, observes, waits *(inferred — see note below)* |
| `CREATE_COMMENT` | Character engages in dialogue |
| `DISLIKE_POST` | Character opposes, confronts, disapproves |
| `LIKE_COMMENT` | Character validates someone's response |
| `DISLIKE_COMMENT` | Character dismisses, mocks |
| `SEARCH_POSTS` | Character investigates, seeks information |
| `SEARCH_USER` | Character seeks out a specific person |
| `MUTE` | Character avoids, ignores, shuns |

**Note on `DO_NOTHING`:** This action may not appear in `actions.jsonl` since the logger only records actions agents take. The translator infers inaction: any agent present in the simulation but absent from a round's action log is treated as "observing/waiting." This is narratively valuable.

### 3.2 Translation Pipeline

For each simulation round:

1. **Collect actions** — read `actions.jsonl` from the translator's saved file offset, gather all actions until the next `round_end` event
2. **Infer inaction** — compare active agents against the full character roster; absent agents are marked as "observing"
3. **Enrich with context** — pull character emotional states, relationships, world state from `narrative/` files
4. **Group into scenes** — cluster related actions (same thread / interacting agents)
5. **Generate prose** — LLM call per scene with action data + context → narrative paragraph
6. **Detect plot events** — classify the round as rising action / climax / falling action / resolution
7. **Update states** — update character emotions and relationships based on what happened
8. **Store** — persist story beat to `narrative/story_beats.json`, update translator file offset in `narrative/translator_state.json`

### 3.3 Resilience

- **LLM retry:** 3 retries with exponential backoff (1s, 2s, 4s) using the existing `retry` utility in `backend/app/utils/retry.py`
- **Partial failure:** If a scene fails after retries, store a placeholder beat with raw action data. User can retry individual beats via API.
- **Graceful degradation:** If the LLM is completely unavailable, fall back to template-based summary: `"{agent_name} {action_verb} {target}"`
- **Cost estimate:** ~3-5 LLM calls per round (one per scene). A 20-round simulation ≈ 60-100 calls ≈ 30k-50k tokens ≈ $0.15-$0.25 with GPT-4o-mini.

### 3.4 LLM Prompt Structure

The translator uses a structured prompt:

```
You are a narrative writer. Convert these simulation events into a story passage.

World: {world_description}
Setting: {current_location_context}
Characters involved: {character_summaries_with_emotions}

Events this round:
{structured_action_list}

Previous story context (last 2 beats):
{previous_prose}

Write a story passage (2-4 paragraphs) that:
- Uses third-person past tense
- Shows character emotions through action and dialogue
- Maintains consistency with the world rules
- Advances the narrative naturally from the previous context

Tone: {user_defined_tone — e.g., "dark fantasy", "lighthearted comedy", "political thriller"}
```

---

## 4. Character Engine

### 4.1 Extended Character Schema

```json
{
  "id": "char_abc123",
  "name": "Elena Voss",
  "oasis_agent_id": "agent_xyz",

  "backstory": "Former diplomat turned rogue negotiator...",
  "motivations": ["power", "redemption"],
  "personality_traits": ["cunning", "loyal_to_few", "distrustful"],
  "speech_style": "Formal, precise, with occasional dark humor",

  "emotional_state": {
    "current": {"anger": 0.3, "fear": 0.1, "joy": 0.0, "sadness": 0.4, "trust": 0.2},
    "history": [{"round": 1, "state": {...}}, ...]
  },

  "relationships": {
    "char_def456": {"type": "rival", "intensity": 0.8, "history": ["betrayal in round 3"]},
    "char_ghi789": {"type": "ally", "intensity": 0.6, "history": ["formed alliance in round 1"]}
  },

  "arc": {
    "archetype": "fall_from_grace",
    "stage": "descent",
    "key_moments": [{"round": 3, "event": "Betrayed longtime ally"}]
  },

  "location": "The Iron Tower",
  "faction": "The Council"
}
```

### 4.2 Emotional State Model

Six basic emotions tracked as 0.0–1.0 floats: `anger`, `fear`, `joy`, `sadness`, `trust`, `surprise`.

Updated each round based on:
- Actions taken by the character
- Actions taken *toward* the character
- World events
- Relationship changes

**v1: Display-only.** Emotional states are derived from actions and displayed in the UI but do NOT feed back into OASIS agent prompts. OASIS profiles are generated once at simulation setup time by `OasisProfileGenerator` and are not modified mid-simulation.

**v2 (future):** Use the new `INJECT_CONTEXT` IPC command (see Section 6.2) to prepend emotional context to agent prompts each round. E.g., `"You are currently feeling angry and distrustful after the betrayal."` This creates a feedback loop where emotions influence behavior, but adds an IPC call per agent per round.

### 4.3 Character Arc Detection

After each round, the Character Engine evaluates arc progression using pattern matching:

| Arc Type | Pattern |
|---|---|
| Hero's Journey | Comfort → Crisis → Growth → Triumph |
| Fall from Grace | Status → Temptation → Descent → Consequences |
| Redemption | Flaw → Suffering → Realization → Atonement |
| Coming of Age | Innocence → Challenge → Learning → Maturity |
| Tragedy | Hope → Hubris → Downfall → Loss |

**Detection mechanism:** Rule-based classification using emotional state deltas:
- Trust drops > 0.3 in one round → "crisis" stage
- Joy sustained > 0.6 for 3+ rounds → "comfort" or "triumph" stage
- Anger + fear both > 0.5 → "descent" stage
- Transition from high-negative to high-positive emotions → "redemption"

If rule-based detection is ambiguous, a single LLM classification call is made with the character's action history summary (~200 tokens). Detected arcs are stored in `characters.json` and surfaced in the UI and export.

---

## 5. World State Manager

### 5.1 World State Schema

```json
{
  "sim_id": "sim_abc123",
  "name": "The Shattered Kingdoms",
  "genre": "dark_fantasy",
  "tone": "grim, political",
  "era": "medieval",

  "rules": [
    "Magic exists but is feared and regulated",
    "The monarchy has fallen; power is contested by three factions",
    "Winter is approaching and resources are scarce"
  ],

  "locations": {
    "iron_tower": {"name": "The Iron Tower", "type": "fortress", "faction": "council", "characters": ["char_abc"]},
    "market_district": {"name": "Market District", "type": "city", "faction": "neutral", "characters": []}
  },

  "factions": {
    "council": {"name": "The Council", "power": 0.6, "members": ["char_abc"], "goals": ["restore order"]},
    "rebels": {"name": "The Free Folk", "power": 0.3, "members": ["char_def"], "goals": ["overthrow council"]}
  },

  "resources": {
    "food": {"abundance": 0.3, "controlled_by": "council"},
    "weapons": {"abundance": 0.5, "controlled_by": "rebels"}
  },

  "timeline_position": {"round": 5, "branch": "main"}
}
```

### 5.2 World State Updates

Each simulation round, the World State Manager:
1. Processes narrative events for world-level changes (faction power shifts, resource changes)
2. Updates character locations based on their actions
3. Checks world rules for constraint violations
4. Triggers world events (e.g., "winter arrives" at round 10)

---

## 6. God Mode

### 6.1 Intervention Types

| Intervention | Effect |
|---|---|
| **Inject Event** | Add a world event ("earthquake strikes", "a stranger arrives") that agents must react to |
| **Modify Character** | Change a character's emotional state, motivation, or relationships |
| **Change Rules** | Add or remove world rules ("magic is now forbidden") |
| **Force Action** | Make a specific character take a specific action next round |
| **Kill Character** | Remove an agent from the simulation permanently |
| **Resurrect Character** | Re-introduce a removed character |
| **Time Skip** | Jump forward N rounds with summarized events |
| **Rewind** | Go back to a previous round (creates a branch) |

### 6.2 Implementation — IPC Dispatch Mechanism

God Mode leverages the existing **file-based IPC** system (`SimulationIPCClient` / `SimulationIPCServer`). The IPC currently supports `INTERVIEW`, `BATCH_INTERVIEW`, and `CLOSE_ENV` commands.

**Mapping God Mode interventions to IPC:**

| Intervention | IPC Mechanism |
|---|---|
| **Inject Event** | `BATCH_INTERVIEW` — send all agents a prompt describing the event, forcing them to react in their next action. E.g., `"An earthquake just struck. How do you respond?"` |
| **Modify Character** | `INTERVIEW` — send the target agent a prompt that reframes their emotional/motivational state. E.g., `"You have just learned that your ally betrayed you. Your trust is shattered."` The Character Engine also updates its local emotional state JSON. |
| **Change Rules** | `BATCH_INTERVIEW` — inform all agents of the rule change. E.g., `"Magic has been outlawed. Anyone caught using it faces death."` Also update `world_state.json`. |
| **Force Action** | `INTERVIEW` — send the target agent a directive prompt. E.g., `"You decide to confront Marcus in front of the council. Describe your accusation."` The response is logged as the agent's action. |
| **Kill Character** | Stop sending actions for this agent in subsequent rounds. Mark as "dead" in `characters.json`. OASIS agent continues to exist but receives no prompts. |
| **Resurrect Character** | Reverse of kill — resume prompting the agent with a resurrection context prompt. |
| **Time Skip** | Set simulation to run N rounds without narrative translation, then batch-translate with a "summary" prompt instead of detailed prose. |
| **Rewind** | Creates a new simulation from scratch using the same config but with a modified starting prompt that includes "the story so far up to round N." See Section 7 for details. |

**New IPC command type needed:** `INJECT_CONTEXT` — a variant of `BATCH_INTERVIEW` that prepends context to all agents' next-round system prompts rather than triggering an immediate interview response. This requires a small addition to the OASIS runner scripts (`run_twitter_simulation.py`, `run_reddit_simulation.py`).

Each intervention is logged to `narrative/god_mode_log.json` for story coherence and auditability.

---

## 7. Timeline Branching

### 7.1 Branch Model

```json
{
  "sim_id": "sim_abc123",
  "branches": {
    "main": {"parent": null, "fork_round": 0, "status": "running", "rounds_completed": 10},
    "what_if_elena_dies": {"parent": "main", "fork_round": 5, "status": "running", "rounds_completed": 3},
    "peaceful_ending": {"parent": "main", "fork_round": 7, "status": "paused", "rounds_completed": 1}
  }
}
```

### 7.2 Branching Mechanics — Replay-Based Approach

**OASIS does not support checkpointing.** The simulation database is deleted on startup and there is no state serialization for mid-simulation resumption. Therefore, branching uses a **replay + diverge** strategy:

1. User selects a round N to branch from
2. System creates a new simulation directory under `uploads/simulations/{sim_id}/branches/{branch_name}/`
3. System copies the original `simulation_config.json` and `profiles.json`
4. System generates a **"story so far" summary** — an LLM-generated condensation of all narrative beats from rounds 1 to N
5. This summary is injected into every agent's starting prompt as context: `"The following events have already occurred: {summary}. You are now at this point in the story."`
6. A new OASIS subprocess launches with modified agent prompts that include this prior context
7. User can optionally inject a God Mode event to differentiate the branch (e.g., "In this timeline, Elena survives the betrayal")
8. Both branches run as independent OASIS processes — user can switch between them in the UI

**Trade-offs of replay approach:**
- **Pro:** No OASIS modifications needed. Uses existing subprocess launch mechanism.
- **Con:** Agents don't have exact memory of previous rounds — they have an LLM-summarized version. This means branches may drift from the original timeline's "feel." For creative fiction, this is acceptable (stories branch naturally).
- **Con:** Starting a branch requires an LLM call for summary generation (~5-10 seconds). Not a major bottleneck.
- **Performance:** Branch launch takes the same time as a fresh simulation start (~10-30 seconds), regardless of which round you branch from.

Storage: Each branch gets its own subdirectory under `uploads/simulations/{sim_id}/branches/{branch_name}/` with its own `simulation_config.json`, `actions.jsonl`, and `narrative/` folder.

---

## 8. Enhanced Input Pipeline

### 8.1 New Seed Formats

| Format | Processing |
|---|---|
| **EPUB** | Extract text → identify characters (NER) → extract settings → generate world state |
| **DOCX** | Same as EPUB but with python-docx parsing |
| **YAML template** | Structured world definition — characters, locations, rules — no LLM needed |
| **Image** | Send to multimodal LLM → extract character description / setting description |
| **URL** | Scrape page content → process as text seed |

### 8.2 YAML World Template Format

```yaml
world:
  name: "The Shattered Kingdoms"
  genre: "dark_fantasy"
  tone: "grim, political"
  rules:
    - "Magic exists but is feared"
    - "Winter is approaching"

characters:
  - name: "Elena Voss"
    role: "protagonist"
    backstory: "Former diplomat..."
    motivations: ["power", "redemption"]
    personality: ["cunning", "loyal"]

  - name: "Marcus Iron"
    role: "antagonist"
    backstory: "Military commander..."
    motivations: ["control", "legacy"]

locations:
  - name: "The Iron Tower"
    type: "fortress"
    description: "A dark spire..."

factions:
  - name: "The Council"
    goals: ["restore order"]
    members: ["Elena Voss"]

simulation:
  max_rounds: 20
  tone: "dark_fantasy"
  platform: "twitter"  # underlying OASIS platform
```

---

## 9. Export Studio

### 9.1 Output Formats

| Format | Structure |
|---|---|
| **Chapters** | Story beats grouped into chapters (every 3-5 rounds), with chapter titles |
| **Screenplay** | Character names in caps, dialogue, (parenthetical action), scene headings |
| **EPUB** | Full e-book with cover, table of contents, chapters, character appendix |
| **Character Dossiers** | Per-character PDF with backstory, arc summary, key moments, relationships |
| **Raw Timeline** | JSON export of all events for programmatic use |

### 9.2 Export Pipeline

1. User selects simulation + branch + format
2. Backend collects all story beats for the selected scope
3. LLM pass for cohesion — smooth transitions between beats, add chapter breaks
4. Format-specific rendering (EPUB via `ebooklib`, screenplay via template)
5. Return download URL

**Async handling:** Export runs in a background thread (consistent with existing `SimulationRunner._monitor_simulation` pattern). The `POST /api/narrative/export/{sim_id}` endpoint returns immediately with an export job ID. Frontend polls `GET /api/narrative/export/{sim_id}/status` until complete. Note: server restarts will lose in-progress exports — acceptable for the target scale.

---

## 10. Data Model Changes

### 10.1 New Files per Simulation

```
uploads/simulations/{sim_id}/
├── state.json              # existing
├── profiles.json           # existing
├── entities.json            # existing
├── simulation_config.json   # existing
├── narrative/               # NEW
│   ├── world_state.json     # world definition
│   ├── characters.json      # extended character profiles
│   ├── story_beats.json     # generated narrative per round
├── branches/                    # Timeline branches (see Section 7)
│   ├── what_if_branch/
│   │   ├── simulation_config.json
│   │   ├── actions.jsonl
│   │   └── narrative/
│   │       ├── story_beats.json
│   │       └── characters.json
│   └── exports/
│       ├── story_chapters.epub
│       └── screenplay.txt
```

### 10.2 Database Additions

No new database — continues using file-based storage consistent with existing MiroFish patterns. For the 10-50 user scale, this is sufficient. If we need to scale later, we migrate to SQLite or PostgreSQL.

---

## 11. Authentication & Multi-User

**Deferred to a separate spec.** The existing MiroFish codebase has zero authentication — no middleware, no user model, no token checks. Adding JWT auth is a cross-cutting concern that touches every existing endpoint and deserves its own design. For v1 of the Narrative Layer, we operate without auth (same as existing MiroFish). Multi-user isolation is handled by simulation IDs — each simulation is self-contained in its own directory.

**When auth is added (separate spec):** Simple JWT tokens, user model in SQLite, middleware on all `/api/` routes, project isolation by user directory, optional "public" flag for sharing.

---

## 12. Non-Goals (Explicitly Out of Scope)

- Real-time collaborative editing (too complex for v1)
- Voice/audio output of stories
- Image generation for scenes (future enhancement)
- Mobile app
- Horizontal scaling / microservices
- Payment / billing
