"""Narrative Layer API endpoints.

Routes are attached to the narrative_bp blueprint defined in api/__init__.py.
All endpoints are prefixed with /api/narrative (see app/__init__.py).
"""
import os
import json
from flask import jsonify, request

from . import narrative_bp
from ..config import Config
from ..services.narrative.story_store import StoryStore
from ..services.narrative.narrative_translator import translate_round
from ..services.narrative.character_engine import CharacterEngine
from ..services.narrative.world_state import WorldStateStore
from ..services.narrative.god_mode import (
    inject_event as gm_inject_event,
    modify_emotion as gm_modify_emotion,
    kill_character as gm_kill_character,
)


def _sim_dir(sim_id: str) -> str:
    """Resolve a simulation ID to its on-disk directory."""
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)


@narrative_bp.route('/story/<sim_id>', methods=['GET'])
def get_full_story(sim_id):
    """Return every story beat generated so far for this simulation."""
    store = StoryStore(_sim_dir(sim_id))
    return jsonify({"sim_id": sim_id, "beats": store.get_all_beats()})


@narrative_bp.route('/story/<sim_id>/round/<int:round_num>', methods=['GET'])
def get_round_story(sim_id, round_num):
    """Return a single round's story beat, or 404 if not yet translated."""
    store = StoryStore(_sim_dir(sim_id))
    beat = store.get_beat_by_round(round_num)
    if not beat:
        return jsonify({"error": "Round not translated yet"}), 404
    return jsonify(beat)


@narrative_bp.route('/translate', methods=['POST'])
def translate():
    """Translate a specific round on demand.

    Body: {"sim_id": str, "round": int, "platform": str = "twitter", "tone": str = "neutral"}
    """
    data = request.get_json() or {}
    sim_id = data.get('sim_id')
    round_num = data.get('round')
    platform = data.get('platform', 'twitter')
    tone = data.get('tone', 'neutral')

    if not sim_id or round_num is None:
        return jsonify({"error": "sim_id and round are required"}), 400

    try:
        beat = translate_round(_sim_dir(sim_id), platform, int(round_num), tone)
        return jsonify(beat)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@narrative_bp.route('/characters/<sim_id>', methods=['GET'])
def get_characters(sim_id):
    """Return the extended character roster (with emotional state)."""
    store = StoryStore(_sim_dir(sim_id))
    return jsonify({"characters": store.load_characters()})


@narrative_bp.route('/characters/<sim_id>/init', methods=['POST'])
def initialize_characters(sim_id):
    """Bootstrap narrative character profiles from the simulation's OASIS profiles."""
    sim_dir = _sim_dir(sim_id)
    profiles_path = os.path.join(sim_dir, 'profiles.json')
    if not os.path.exists(profiles_path):
        return jsonify({"error": "profiles.json not found for this simulation"}), 404

    with open(profiles_path, 'r', encoding='utf-8') as f:
        profiles = json.load(f)

    store = StoryStore(sim_dir)
    engine = CharacterEngine(store)
    characters = engine.initialize_from_profiles(profiles)
    return jsonify({"count": len(characters), "characters": characters})


# ---------------------------------------------------------------------------
# World State endpoints
# ---------------------------------------------------------------------------

@narrative_bp.route('/world/<sim_id>', methods=['GET'])
def get_world(sim_id):
    """Return the full world_state.json for this simulation."""
    store = WorldStateStore(_sim_dir(sim_id))
    return jsonify(store.load())


@narrative_bp.route('/world/<sim_id>/rules', methods=['POST'])
def set_rules(sim_id):
    """Replace the full rules list. Body: {"rules": [str, ...]}."""
    data = request.get_json() or {}
    rules = data.get('rules')
    if not isinstance(rules, list):
        return jsonify({"error": "rules must be a list of strings"}), 400
    store = WorldStateStore(_sim_dir(sim_id))
    store.set_rules([str(r) for r in rules])
    return jsonify(store.load())


@narrative_bp.route('/world/<sim_id>/locations', methods=['POST'])
def upsert_location(sim_id):
    """Insert or update a location. Body: {"id", "name", "description"}."""
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


# ---------------------------------------------------------------------------
# God Mode endpoints
# ---------------------------------------------------------------------------

@narrative_bp.route('/godmode/<sim_id>/inject-event', methods=['POST'])
def godmode_inject_event(sim_id):
    """Inject a world event. Body: {"description", "round"? (optional, >=0)}."""
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

    evt = gm_inject_event(_sim_dir(sim_id), description=str(description), round_num=round_num)
    return jsonify(evt)


@narrative_bp.route('/godmode/<sim_id>/modify-emotion', methods=['POST'])
def godmode_modify_emotion(sim_id):
    """Overwrite emotion values. Body: {"character_id", "emotions": {name: float}}."""
    data = request.get_json() or {}
    char_id = data.get('character_id')
    emotions = data.get('emotions')
    if not char_id or not isinstance(emotions, dict):
        return jsonify({"error": "character_id and emotions are required"}), 400
    try:
        char = gm_modify_emotion(_sim_dir(sim_id), str(char_id), emotions)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(char)


@narrative_bp.route('/godmode/<sim_id>/kill', methods=['POST'])
def godmode_kill(sim_id):
    """Mark a character as dead. Body: {"character_id"}."""
    data = request.get_json() or {}
    char_id = data.get('character_id')
    if not char_id:
        return jsonify({"error": "character_id is required"}), 400
    try:
        char = gm_kill_character(_sim_dir(sim_id), str(char_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(char)
