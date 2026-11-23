"""
GTM Simulation Lab — API endpoints for GTM brief submission, preview, and persona generation.
"""

import os
import json
from flask import request, jsonify
from . import gtm_bp
from ..models.gtm_brief import GTMBriefManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.gtm')


def _persona_count(brief) -> int:
    """Persona count from brief object or dict, clamped 6–500."""
    n = brief.get('num_personas', 12) if isinstance(brief, dict) else getattr(brief, 'num_personas', 12)
    return max(6, min(500, int(n or 12)))


def _message_count(brief) -> int:
    """Message variant count from brief object or dict, clamped 2–5."""
    n = brief.get('num_messages', 3) if isinstance(brief, dict) else getattr(brief, 'num_messages', 3)
    return max(2, min(5, int(n or 3)))

_MOCK_PREVIEW_PATH = os.path.join(
    os.path.dirname(__file__), '../../mock_data/gtm_preview.json'
)


def _load_mock_preview():
    """Load the static mock preview data from backend/mock_data/gtm_preview.json."""
    try:
        with open(_MOCK_PREVIEW_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load mock preview data: {e}")
        return {"personas": [], "message_angle_teasers": []}


def _personas_path(brief_id: str) -> str:
    from ..config import Config
    return os.path.join(Config.UPLOAD_FOLDER, 'gtm_briefs', brief_id, 'personas.json')


def _save_personas(brief_id: str, personas: list):
    path = _personas_path(brief_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(personas, f, ensure_ascii=False, indent=2)


def _load_cached_personas(brief_id: str):
    path = _personas_path(brief_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@gtm_bp.route('/brief', methods=['POST'])
def submit_brief():
    """
    POST /api/gtm/brief

    Accepts a GTM brief payload, validates it, persists it, and returns
    the brief_id for downstream simulation steps.
    """
    data = request.get_json(silent=True) or {}

    errors = GTMBriefManager.validate(data)
    if errors:
        return jsonify({'success': False, 'errors': errors}), 400

    try:
        brief = GTMBriefManager.create_brief(data)
        logger.info(f"GTM brief created: {brief.brief_id}")
        return jsonify({
            'success': True,
            'data': {
                'brief_id': brief.brief_id,
                'brief': brief.to_dict(),
            }
        })
    except Exception as e:
        logger.error(f"Failed to create GTM brief: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gtm_bp.route('/brief/<brief_id>', methods=['GET'])
def get_brief(brief_id: str):
    """GET /api/gtm/brief/<brief_id> — retrieve a stored GTM brief."""
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404
    return jsonify({'success': True, 'data': brief.to_dict()})


@gtm_bp.route('/brief/<brief_id>/preview', methods=['GET'])
def get_preview(brief_id: str):
    """
    GET /api/gtm/brief/<brief_id>/preview

    Returns a quick 3-persona preview (mock) for the Home.vue teaser state.
    Intentionally fast — does not call LLM.
    Full 12-persona generation is done via POST /api/gtm/personas/<brief_id>.
    """
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    preview = _load_mock_preview()
    return jsonify({'success': True, 'data': preview})


@gtm_bp.route('/personas/<brief_id>', methods=['POST'])
def generate_personas(brief_id: str):
    """
    POST /api/gtm/personas/<brief_id>

    Generate 10-12 buyer personas using LLM + GTM brief context.
    Caches result to uploads/gtm_briefs/<brief_id>/personas.json.
    Returns cached personas if already generated (idempotent).
    """
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    # Return cached if available
    cached = _load_cached_personas(brief_id)
    if cached:
        logger.info(f"Returning cached personas for brief {brief_id}")
        return jsonify({'success': True, 'data': cached, 'cached': True})

    try:
        from ..services.gtm_persona_generator import GTMPersonaGenerator
        generator = GTMPersonaGenerator()
        body = request.get_json(silent=True, force=True) or {}
        n = int(body.get('count', _persona_count(brief)))
        personas = generator.generate(brief, count=n)
        _save_personas(brief_id, personas)
        logger.info(f"Generated and cached {len(personas)} personas for brief {brief_id}")
        return jsonify({'success': True, 'data': personas, 'cached': False})
    except Exception as e:
        logger.error(f"Persona generation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gtm_bp.route('/personas/<brief_id>', methods=['GET'])
def get_personas(brief_id: str):
    """
    GET /api/gtm/personas/<brief_id>

    Returns cached personas if available. If not cached, generates them on-demand
    and caches the result. Use POST for an explicit generation trigger.
    """
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_cached_personas(brief_id)
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    # Auto-generate on GET if not cached
    try:
        from ..services.gtm_persona_generator import GTMPersonaGenerator
        generator = GTMPersonaGenerator()
        personas = generator.generate(brief, count=_persona_count(brief))
        _save_personas(brief_id, personas)
        return jsonify({'success': True, 'data': personas, 'cached': False})
    except Exception as e:
        logger.error(f"On-demand persona generation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gtm_bp.route('/briefs', methods=['GET'])
def list_briefs():
    """GET /api/gtm/briefs — list recent GTM briefs."""
    limit = request.args.get('limit', 20, type=int)
    briefs = GTMBriefManager.list_briefs(limit=limit)
    return jsonify({
        'success': True,
        'data': [b.to_dict() for b in briefs],
        'count': len(briefs),
    })


# ── Message generation ────────────────────────────────────────────────────────

def _messages_path(brief_id: str) -> str:
    from ..config import Config
    return os.path.join(Config.UPLOAD_FOLDER, 'gtm_briefs', brief_id, 'messages.json')


def _reactions_path(brief_id: str) -> str:
    from ..config import Config
    return os.path.join(Config.UPLOAD_FOLDER, 'gtm_briefs', brief_id, 'reactions.json')


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@gtm_bp.route('/messages/<brief_id>', methods=['POST'])
def generate_messages(brief_id: str):
    """
    POST /api/gtm/messages/<brief_id>

    Generate 3 outreach messages using LLM + GTM brief context.
    Idempotent — returns cached messages if already generated.
    Requires personas to already be generated (or auto-generates them).
    """
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_json(_messages_path(brief_id))
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    try:
        personas = _load_json(_personas_path(brief_id))
        if not personas:
            from ..services.gtm_persona_generator import GTMPersonaGenerator
            personas = GTMPersonaGenerator().generate(brief, count=_persona_count(brief))
            _save_json(_personas_path(brief_id), personas)

        from ..services.gtm_message_generator import GTMMessageGenerator
        messages = GTMMessageGenerator().generate(brief, personas, count=_message_count(brief))
        _save_json(_messages_path(brief_id), messages)
        logger.info(f"Generated {len(messages)} messages for brief {brief_id}")
        return jsonify({'success': True, 'data': messages, 'cached': False})
    except Exception as e:
        logger.error(f"Message generation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gtm_bp.route('/messages/<brief_id>', methods=['GET'])
def get_messages(brief_id: str):
    """GET /api/gtm/messages/<brief_id> — return cached messages; auto-generate if missing."""
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_json(_messages_path(brief_id))
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    try:
        personas = _load_json(_personas_path(brief_id)) or []
        from ..services.gtm_message_generator import GTMMessageGenerator
        messages = GTMMessageGenerator().generate(brief, personas, count=_message_count(brief))
        _save_json(_messages_path(brief_id), messages)
        return jsonify({'success': True, 'data': messages, 'cached': False})
    except Exception as e:
        logger.error(f"On-demand message generation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── Reaction simulation ───────────────────────────────────────────────────────

def _simulate_reactions(messages: list, personas: list) -> dict:
    """Run the multi-run reaction simulation and aggregate it into the stored result shape."""
    from ..services.gtm_reaction_simulator import GTMReactionSimulator
    from ..services.gtm_aggregator import aggregate

    sim = GTMReactionSimulator().simulate(messages, personas)
    agg = aggregate(messages, sim['reactions'], sim['run_reactions'])
    return {
        'reactions': sim['reactions'],
        'summaries': agg['summaries'],
        'winner': agg['winner'],
        'source': sim['source'],            # 'llm' or 'mock' — the UI must label mock results
        'mock_reason': sim['mock_reason'],
        'runs_requested': sim['runs_requested'],
        'runs_completed': sim['runs_completed'],
        'coverage': sim['coverage'],
    }


@gtm_bp.route('/reactions/<brief_id>', methods=['POST'])
def generate_reactions(brief_id: str):
    """
    POST /api/gtm/reactions/<brief_id>

    Simulate all persona × message reactions (36 total) using LLM.
    Also runs aggregation and returns summaries + winner in the same response.
    Idempotent — returns cached if already simulated.
    """
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_json(_reactions_path(brief_id))
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    try:
        personas = _load_json(_personas_path(brief_id))
        if not personas:
            from ..services.gtm_persona_generator import GTMPersonaGenerator
            personas = GTMPersonaGenerator().generate(brief, count=_persona_count(brief))
            _save_json(_personas_path(brief_id), personas)

        messages = _load_json(_messages_path(brief_id))
        if not messages:
            from ..services.gtm_message_generator import GTMMessageGenerator
            messages = GTMMessageGenerator().generate(brief, personas, count=_message_count(brief))
            _save_json(_messages_path(brief_id), messages)

        result = _simulate_reactions(messages, personas)
        _save_json(_reactions_path(brief_id), result)
        logger.info(
            f"Simulated {len(result['reactions'])} reactions for brief {brief_id} "
            f"(source={result['source']}, runs={result['runs_completed']})"
        )
        return jsonify({'success': True, 'data': result, 'cached': False})
    except Exception as e:
        logger.error(f"Reaction simulation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gtm_bp.route('/reactions/<brief_id>', methods=['GET'])
def get_reactions(brief_id: str):
    """GET /api/gtm/reactions/<brief_id> — return cached reactions; auto-simulate if missing."""
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_json(_reactions_path(brief_id))
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    # Delegate to POST handler logic
    return generate_reactions(brief_id)


# ── GTM Report ────────────────────────────────────────────────────────────────

def _report_path(brief_id: str) -> str:
    from ..config import Config
    return os.path.join(Config.UPLOAD_FOLDER, 'gtm_briefs', brief_id, 'report.json')


@gtm_bp.route('/report/<brief_id>', methods=['POST'])
def generate_report(brief_id: str):
    """
    POST /api/gtm/report/<brief_id>

    Generate a structured GTM report from existing simulation data.
    Idempotent — returns cached report if already generated.
    Auto-generates any missing upstream data (personas, messages, reactions).
    """
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_json(_report_path(brief_id))
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    try:
        # Ensure all upstream data exists
        personas = _load_json(_personas_path(brief_id))
        if not personas:
            from ..services.gtm_persona_generator import GTMPersonaGenerator
            personas = GTMPersonaGenerator().generate(brief, count=_persona_count(brief))
            _save_json(_personas_path(brief_id), personas)

        messages = _load_json(_messages_path(brief_id))
        if not messages:
            from ..services.gtm_message_generator import GTMMessageGenerator
            messages = GTMMessageGenerator().generate(brief, personas, count=_message_count(brief))
            _save_json(_messages_path(brief_id), messages)

        reactions_data = _load_json(_reactions_path(brief_id))
        if not reactions_data:
            reactions_data = _simulate_reactions(messages, personas)
            _save_json(_reactions_path(brief_id), reactions_data)

        reactions = reactions_data.get('reactions', [])
        summaries = reactions_data.get('summaries', [])
        winner = reactions_data.get('winner', {})

        from ..services.gtm_report_generator import GTMReportGenerator
        report = GTMReportGenerator().generate(brief, personas, messages, reactions, summaries, winner)
        _save_json(_report_path(brief_id), report)
        logger.info(f"GTM report generated for brief {brief_id}")
        return jsonify({'success': True, 'data': report, 'cached': False})
    except Exception as e:
        logger.error(f"GTM report generation failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@gtm_bp.route('/report/<brief_id>', methods=['GET'])
def get_report(brief_id: str):
    """GET /api/gtm/report/<brief_id> — return cached report; auto-generate if missing."""
    brief = GTMBriefManager.get_brief(brief_id)
    if not brief:
        return jsonify({'success': False, 'error': f'Brief not found: {brief_id}'}), 404

    cached = _load_json(_report_path(brief_id))
    if cached:
        return jsonify({'success': True, 'data': cached, 'cached': True})

    return generate_report(brief_id)
