"""
Idea Studio API: chat sessions with a streamed AI co-founder reply.

POST /api/idea/sessions                       create a session  -> {session_id, ...}
GET  /api/idea/sessions                       recent sessions
GET  /api/idea/sessions/<id>                  full session (messages + state)
POST /api/idea/sessions/<id>/messages         {"content": "..."} -> text/event-stream

Stream events (Server-Sent Events, one JSON object per `data:` line):
  {"type": "start"}                           reply is starting
  {"type": "delta", "text": "..."}            next chunk of the reply
  {"type": "done", "message": {...}}          final cleaned message, as saved
  {"type": "error", "error": "..."}           the model failed; nothing was saved for the reply
"""

import json

from flask import Response, jsonify, request, stream_with_context

from . import idea_bp
from ..models.idea_session import MAX_MESSAGE_CHARS, IdeaSessionManager, is_valid_session_id
from ..utils.logger import get_logger
from ..utils.text_style import strip_em_dashes

logger = get_logger('mirofish.api.idea')


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@idea_bp.route('/sessions', methods=['POST'])
def create_session():
    body = request.get_json(silent=True) or {}
    session = IdeaSessionManager.create(title=body.get('title'))
    return jsonify({'success': True, 'data': session})


@idea_bp.route('/sessions', methods=['GET'])
def list_sessions():
    limit = max(1, min(100, int(request.args.get('limit', 20))))
    return jsonify({'success': True, 'data': IdeaSessionManager.list(limit)})


@idea_bp.route('/sessions/<session_id>', methods=['GET'])
def get_session(session_id: str):
    session = IdeaSessionManager.get(session_id)
    if not session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    return jsonify({'success': True, 'data': session})


@idea_bp.route('/sessions/<session_id>/messages', methods=['POST'])
def post_message(session_id: str):
    if not is_valid_session_id(session_id) or not IdeaSessionManager.get(session_id):
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    body = request.get_json(silent=True) or {}
    content = (body.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'content is required'}), 400
    if len(content) > MAX_MESSAGE_CHARS:
        return jsonify({'success': False, 'error': f'message is longer than {MAX_MESSAGE_CHARS} characters'}), 400

    try:
        IdeaSessionManager.append_message(session_id, 'user', content)
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    history = IdeaSessionManager.get(session_id)['messages']

    from ..services import idea_chat   # imported here so tests can swap the LLM

    @stream_with_context
    def generate():
        yield _sse({'type': 'start'})
        parts = []
        try:
            for text in idea_chat.stream_reply(history):
                parts.append(text)
                yield _sse({'type': 'delta', 'text': text})
        except Exception as e:
            logger.warning(f"Idea chat stream failed for {session_id}: {e}")
            yield _sse({'type': 'error', 'error': f'The AI co-founder is unavailable right now ({e}).'})
            return
        reply = strip_em_dashes(''.join(parts)).strip()
        if not reply:
            yield _sse({'type': 'error', 'error': 'The AI co-founder returned an empty reply.'})
            return
        message = IdeaSessionManager.append_message(session_id, 'assistant', reply)
        yield _sse({'type': 'done', 'message': message})

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',   # stop proxies from buffering the stream
    })


# ── Stateless Idea Studio turn API (the browser owns the state) ─────────────

@idea_bp.route('/new', methods=['GET'])
def new_idea():
    """A fresh idea state and the opening message. Nothing is stored server-side."""
    import uuid
    from ..services import idea_state, idea_studio
    state = idea_state.refresh(idea_state.new_state(str(uuid.uuid4())))
    return jsonify({'success': True, 'data': {'state': state, 'opening': idea_studio.opening_message()}})


@idea_bp.route('/turn', methods=['POST'])
def idea_turn():
    """
    POST /api/idea/turn  {"state": {...}, "messages": [{role, content}], "content": "..."}
    Streams: start, sources/evidence (step 3), delta..., reply, state, done; or error.
    """
    body = request.get_json(silent=True) or {}
    content = (body.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'content is required'}), 400
    if len(content) > MAX_MESSAGE_CHARS:
        return jsonify({'success': False, 'error': f'message is longer than {MAX_MESSAGE_CHARS} characters'}), 400
    messages = [m for m in (body.get('messages') or []) if isinstance(m, dict)][-20:]
    raw_state = body.get('state')

    from ..services import idea_studio

    @stream_with_context
    def generate():
        try:
            for event in idea_studio.run_turn(raw_state, messages, content):
                yield _sse(event)
        except Exception as e:   # never leave the client hanging mid-stream
            logger.error(f"Idea turn failed: {e}")
            yield _sse({'type': 'error', 'error': 'Something went wrong on this turn. Your idea is unchanged.'})

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-transform',
        'X-Accel-Buffering': 'no',
    })


def _state_action(fn):
    from ..services import idea_state
    body = request.get_json(silent=True) or {}
    state = idea_state.validate_client_state(body.get('state'))
    try:
        return jsonify({'success': True, 'data': {'state': fn(idea_state, state, body)}})
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return jsonify({'success': False, 'error': f'Cannot change that field: {e}'}), 400


@idea_bp.route('/edit', methods=['POST'])
def idea_edit():
    """The founder rewrites a field: it becomes founder-stated and locked."""
    return _state_action(lambda m, s, b: m.founder_edit(s, str(b.get('path', '')), str(b.get('text', ''))[:400]))


@idea_bp.route('/lock', methods=['POST'])
def idea_lock():
    """Lock or unlock a field so the analyst cannot change it."""
    return _state_action(lambda m, s, b: m.refresh(m.set_locked(s, str(b.get('path', '')), bool(b.get('locked')))))
