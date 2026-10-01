"""Reads OASIS actions.jsonl and translates rounds into story prose.

The translator is stateless about which round comes next — callers maintain
the file offset via StoryStore. Each call to `read_actions_for_round` reads
from the saved offset until a matching `round_end` event is seen (or EOF).
"""
import os
import json
from typing import List, Tuple

from app.services.narrative.action_mapper import get_narrative_context


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
    lines = []
    for l in locs:
        name = _escape_braces(l.get("name", ""))
        desc = _escape_braces(l.get("description", ""))
        line = f"{name} — {desc}"
        # Cinematic schema: if atmosphere is present, surface it to the LLM as
        # a mood anchor for any scene set here.
        atmosphere = l.get("atmosphere")
        if atmosphere:
            line += f" [atmosphere: {_escape_braces(atmosphere)}]"
        lines.append(line)
    return "\n  ".join(lines)


def read_actions_for_round(
    jsonl_path: str, start_offset: int, target_round: int
) -> Tuple[List[dict], int]:
    """Read all agent actions for `target_round` starting at `start_offset`.

    Returns:
        (actions, new_offset): list of action dicts and the file position to
        resume from on the next read. If the target round hasn't completed yet
        (no matching `round_end` event), new_offset is advanced to EOF so the
        next call picks up where we left off.
    """
    if not os.path.exists(jsonl_path):
        return [], start_offset

    actions: List[dict] = []
    new_offset = start_offset

    with open(jsonl_path, "r", encoding="utf-8") as f:
        f.seek(start_offset)
        while True:
            line = f.readline()
            if not line:
                break
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                # Skip malformed lines but keep advancing
                new_offset = f.tell()
                continue

            # Round-end event for our target marks the boundary
            if entry.get("event_type") == "round_end" and entry.get("round") == target_round:
                new_offset = f.tell()
                break

            # Skip other event types (simulation_start, simulation_end, etc.)
            if "event_type" in entry:
                new_offset = f.tell()
                continue

            # Skip actions from other rounds
            if entry.get("round") != target_round:
                new_offset = f.tell()
                continue

            actions.append(entry)
            new_offset = f.tell()

    return actions, new_offset


# ---------------------------------------------------------------------------
# Prose generation
# ---------------------------------------------------------------------------

def call_llm(prompt: str) -> str:
    """Send a single-turn prompt to the configured LLM and return the response.

    Wrapped as a module-level function (not a class method) so tests can patch
    it trivially: `patch("app.services.narrative.narrative_translator.call_llm")`.
    """
    # Lazy import — avoids forcing LLM config to be set during unit tests that
    # never actually call the real LLM.
    from app.utils.llm_client import LLMClient

    client = LLMClient()
    return client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=1024,
    )


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


def _format_action_line(action: dict) -> str:
    name = action.get("agent_name", "Someone")
    act = action.get("action_type", "UNKNOWN")
    args = action.get("action_args", {}) or {}
    content = args.get("content", "")
    ctx = get_narrative_context(act)
    if content:
        return f'- {name}: {ctx}. Content: "{content}"'
    return f"- {name}: {ctx}"


# ============================================================================
# USER CONTRIBUTION POINT — Prose generation prompt
# ============================================================================
#
# This template is rendered with four substitutions and sent to the LLM to
# generate each story beat. It is the single biggest lever for story quality.
#
# Substitution fields available:
#   {tone}       — user-selected tone, e.g. "dark fantasy" or "romantic comedy"
#   {characters} — per-character one-liner with top emotions
#   {actions}    — bullet-point list of what each character did this round
#   {previous}   — prose from the last 1-2 beats (or "(first scene)")
#
# Design choices to consider:
#   - Tense/POV (third-person past is most versatile)
#   - Paragraph count (2-4 is a good range)
#   - Show vs tell (instruct the model to show emotions through action/dialogue)
#   - Continuity (tell it to continue naturally from {previous})
#   - How strictly to enforce tone
#
# A temporary minimal template is used below to make tests pass — REPLACE
# WITH YOUR OWN DESIGN to dial in story quality.
# ============================================================================
# ============================================================================
# USER CONTRIBUTION POINT — how strongly to force world events into prose
# ============================================================================
# Three supported values:
#   "soft"   — "consider referencing the most recent world event if it fits"
#   "medium" — "weave it in OR acknowledge its aftermath. Do not ignore it."
#   "hard"   — "the opening line MUST reference the most recent world event"
# Temporary default is "medium" — change after reviewing sample output.
# ============================================================================
EVENT_ENFORCEMENT_STRENGTH = "hard"

_ENFORCEMENT_PHRASES = {
    "soft":   "- Consider referencing the most recent world event if it fits naturally.",
    "medium": "- Weave the most recent world event in, OR acknowledge its aftermath. Do not ignore it.",
    "hard":   "- The OPENING LINE of this passage MUST reference the most recent world event.",
}


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
# ============================================================================


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

    enforcement = _ENFORCEMENT_PHRASES.get(
        EVENT_ENFORCEMENT_STRENGTH, _ENFORCEMENT_PHRASES["medium"]
    )

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


# ---------------------------------------------------------------------------
# Round orchestration — the entry point most callers use
# ---------------------------------------------------------------------------

def translate_round(sim_dir: str, platform: str, target_round: int, tone: str = "neutral") -> dict:
    """Translate a single simulation round into a story beat end-to-end.

    Steps:
      1. Read the round's actions from `{sim_dir}/{platform}/actions.jsonl`
         (starting from the saved file offset).
      2. Load world state (rules, locations, event log) — empty if not present.
      3. Filter dead characters and their actions out before prose generation.
      4. Generate prose via the LLM using current character + world state.
      5. Apply emotional-state deltas for every action to living characters.
      6. Persist the new beat, updated character state, and new file offset.

    Returns the newly created story beat dict.
    """
    # Lazy imports keep module import lightweight for unit tests of helpers
    from app.services.narrative.story_store import StoryStore
    from app.services.narrative.character_engine import apply_action_emotional_delta
    from app.services.narrative.world_state import WorldStateStore

    store = StoryStore(sim_dir)
    world = WorldStateStore(sim_dir).load()

    actions_path = os.path.join(sim_dir, platform, "actions.jsonl")
    start_offset = store.get_file_offset(platform)

    actions, new_offset = read_actions_for_round(actions_path, start_offset, target_round)

    # Filter dead characters and their actions
    all_characters = store.load_characters()
    alive_names = {c["name"] for c in all_characters if c.get("status", "alive") != "dead"}
    living_characters = [c for c in all_characters if c["name"] in alive_names]
    actions = [a for a in actions if a.get("agent_name") in alive_names]

    previous_beats = store.get_all_beats()
    prose = generate_prose(actions, living_characters, tone, previous_beats, world)

    # De-duplicated list of character names that acted this round (living only)
    involved = sorted({a.get("agent_name") for a in actions if a.get("agent_name")})

    # Apply emotional deltas only to living characters
    char_by_name = {c["name"]: c for c in all_characters}
    for action in actions:
        char = char_by_name.get(action.get("agent_name"))
        if char and char.get("status", "alive") != "dead":
            apply_action_emotional_delta(char, action.get("action_type", ""))
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
