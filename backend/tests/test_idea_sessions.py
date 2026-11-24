"""Idea Studio plumbing: LLM streaming, session storage, and the streamed messages endpoint."""

import json
from types import SimpleNamespace as N

import pytest

from app.config import Config
from app.models.idea_session import IdeaSessionManager, is_valid_session_id
from app.utils.llm_client import LLMClient


@pytest.fixture(autouse=True)
def _uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))


def chunk(text):
    return N(choices=[N(delta=N(content=text))])


def stream_client(chunks):
    client = LLMClient.__new__(LLMClient)
    client.model = 'openai/gpt-4o-mini'
    client.client = N(chat=N(completions=N(create=lambda **kw: iter([chunk(c) for c in chunks]))))
    return client


def test_chat_stream_yields_deltas_and_drops_reasoning():
    llm = stream_client(['Hel', 'lo <think>hidden', ' still hidden</think> wor', 'ld', None])
    assert ''.join(llm.chat_stream([{'role': 'user', 'content': 'hi'}])) == 'Hello  world'


def test_chat_stream_requests_streaming():
    seen = {}

    def create(**kw):
        seen.update(kw)
        return iter([chunk('ok')])

    llm = stream_client([])
    llm.client = N(chat=N(completions=N(create=create)))
    list(llm.chat_stream([{'role': 'user', 'content': 'hi'}], max_tokens=50))
    assert seen['stream'] is True and seen['max_tokens'] == 50


def test_session_lifecycle():
    s = IdeaSessionManager.create()
    sid = s['session_id']
    assert is_valid_session_id(sid) and s['messages'] == [] and s['state'] == {}
    IdeaSessionManager.append_message(sid, 'user', 'Uber for dog walkers\nmore detail')
    IdeaSessionManager.append_message(sid, 'assistant', 'Who pays?')
    again = IdeaSessionManager.get(sid)
    assert [m['role'] for m in again['messages']] == ['user', 'assistant']
    assert again['title'] == 'Uber for dog walkers'
    assert IdeaSessionManager.list()[0]['message_count'] == 2


@pytest.mark.parametrize('bad', ['../../etc/passwd', 'abc', '', '..', 'ABCDEFGH-1234-1234-1234-123456789012'])
def test_session_ids_cannot_escape_the_sessions_folder(bad):
    assert IdeaSessionManager.get(bad) is None


def test_invalid_role_rejected():
    sid = IdeaSessionManager.create()['session_id']
    with pytest.raises(ValueError):
        IdeaSessionManager.append_message(sid, 'system', 'x')


def _events(resp):
    body = resp.get_data(as_text=True)
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: ')]


@pytest.fixture
def client():
    from app import create_app
    return create_app().test_client()


def test_stream_endpoint_saves_both_sides(client, monkeypatch):
    from app.services import idea_chat
    monkeypatch.setattr(idea_chat, 'stream_reply', lambda history: iter(['Who ', 'pays — owners?']))
    sid = client.post('/api/idea/sessions', json={}).get_json()['data']['session_id']
    resp = client.post(f'/api/idea/sessions/{sid}/messages', json={'content': 'Dog walking app'})
    assert resp.mimetype == 'text/event-stream'
    ev = _events(resp)
    assert [e['type'] for e in ev] == ['start', 'delta', 'delta', 'done']
    assert ev[-1]['message']['content'] == 'Who pays, owners?'           # em dash cleaned on save
    saved = client.get(f'/api/idea/sessions/{sid}').get_json()['data']['messages']
    assert [(m['role'], m['content']) for m in saved] == [('user', 'Dog walking app'),
                                                          ('assistant', 'Who pays, owners?')]


def test_stream_endpoint_reports_llm_failure_without_saving_reply(client, monkeypatch):
    from app.services import idea_chat

    def boom(history):
        raise RuntimeError('LLM_API_KEY is not configured')
        yield  # pragma: no cover

    monkeypatch.setattr(idea_chat, 'stream_reply', boom)
    sid = client.post('/api/idea/sessions', json={}).get_json()['data']['session_id']
    ev = _events(client.post(f'/api/idea/sessions/{sid}/messages', json={'content': 'hi'}))
    assert ev[-1]['type'] == 'error' and 'LLM_API_KEY' in ev[-1]['error']
    saved = client.get(f'/api/idea/sessions/{sid}').get_json()['data']['messages']
    assert [m['role'] for m in saved] == ['user']


def test_message_validation(client):
    sid = client.post('/api/idea/sessions', json={}).get_json()['data']['session_id']
    assert client.post(f'/api/idea/sessions/{sid}/messages', json={'content': '  '}).status_code == 400
    assert client.post(f'/api/idea/sessions/{sid}/messages', json={'content': 'x' * 5000}).status_code == 400
    assert client.post('/api/idea/sessions/not-a-uuid/messages', json={'content': 'hi'}).status_code == 404


def test_history_sent_to_model_is_bounded():
    from app.services.idea_chat import HISTORY_LIMIT, build_messages
    history = [{'role': 'user' if i % 2 else 'assistant', 'content': str(i)} for i in range(100)]
    msgs = build_messages(history)
    assert msgs[0]['role'] == 'system' and len(msgs) == HISTORY_LIMIT + 1 and msgs[-1]['content'] == '99'
