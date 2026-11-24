"""Idea Studio turn pipeline: question routing, streamed reply, analyst patch, fallbacks, API."""

import json
from types import SimpleNamespace as N

import pytest

from app.services import idea_state as st
from app.services import idea_studio as studio


class FakeChat:
    def __init__(self, chunks=('Got it. ', '**What can they not do well today?**'), fail=False):
        self.chunks, self.fail, self.messages = chunks, fail, None

    def chat_stream(self, messages, **kw):
        self.messages = messages
        if self.fail:
            raise RuntimeError('LLM_API_KEY is not configured')
        yield from self.chunks


class FakeExtract:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.messages = None

    def chat_json(self, messages, **kw):
        self.calls += 1
        self.messages = messages
        r = self.results.pop(0) if self.results else {}
        if isinstance(r, Exception):
            raise r
        return r


def events(gen):
    return list(gen)


def new():
    return st.refresh(st.new_state('11111111-2222-3333-4444-555555555555'))


def test_first_question_targets_the_problem():
    q = studio.pick_next_questions(new())
    assert q[0]['field'] == 'problem.statement' and len(q) == 3


def test_questions_rotate_and_back_off_when_dodged():
    s = new()
    s['meta']['turn'] = 5
    asked = [{'field': 'problem.statement', 'turn': 1}, {'field': 'problem.statement', 'turn': 2}]
    q = studio.pick_next_questions(s, asked)
    assert q[0]['field'] != 'problem.statement'      # dodged twice, move on


def test_contradiction_is_asked_first():
    s, _, _ = st.apply_patch(new(), [{'op': 'replace', 'path': '/problem/frequency',
                                      'value': {'text': 'Monthly, not daily', 'status': 'contradiction'}}])
    assert studio.pick_next_questions(s)[0]['reason'] == 'contradiction'


def test_full_turn_streams_reply_and_applies_validated_patch():
    chat = FakeChat()
    extract = FakeExtract([{'founder_facts': {'problem': 'Front desks spend hours confirming appointments'},
                            'analysis': {'one_liner': 'Voice agent that confirms dental appointments',
                                         'competitors': [{'name': 'Weave', 'source_id': 'S9'}]},   # no such source
                            'change_summary': 'Captured the problem.'}])
    ev = events(studio.run_turn(new(), [], 'A voice agent that confirms dental appointments', chat, extract))
    types = [e['type'] for e in ev]
    assert types == ['start', 'delta', 'delta', 'reply', 'state', 'done']
    reply = next(e for e in ev if e['type'] == 'reply')
    assert reply['source'] == 'llm' and reply['acknowledgment'] == 'Got it.'
    assert reply['ask']['field'] != 'problem.statement'
    state_ev = next(e for e in ev if e['type'] == 'state')
    s = state_ev['state']
    assert s['problem']['statement']['status'] == 'founder_stated'
    assert s['one_liner']['status'] == 'ai_inference'
    assert state_ev['rejected'] == 1 and s['clarity']['score'] > 0
    assert s['meta']['turn'] == 1 and s['history'][-1]['asked']['turn'] == 1
    assert len(s['open_questions']) == 3


def test_extractor_reads_only_the_latest_founder_message():
    chat, extract = FakeChat(), FakeExtract([{'founder_facts': {}}])
    events(studio.run_turn(new(), [], 'my idea', chat, extract))
    system = extract.messages[0]['content']
    assert system.startswith('An analyst is reviewing')
    assert 'LATEST FOUNDER MESSAGE:\nmy idea' in extract.messages[1]['content']
    assert 'Advisor:' not in extract.messages[1]['content']
    assert 'NEXT QUESTION' in chat.messages[1]['content']


def test_chat_failure_falls_back_to_scripted_question():
    ev = events(studio.run_turn(new(), [], 'idea', FakeChat(fail=True), FakeExtract([{'founder_facts': {}}])))
    reply = next(e for e in ev if e['type'] == 'reply')
    assert reply['source'] == 'scripted' and reply['notice'] and reply['content'].startswith('**')


def test_extraction_retries_without_guessing_the_field():
    extract = FakeExtract([RuntimeError('bad json'), RuntimeError('bad json again')])
    ev = events(studio.run_turn(new(), [], 'Dentists waste time on reminder calls', FakeChat(), extract))
    state_ev = next(e for e in ev if e['type'] == 'state')
    assert extract.calls == 2 and 'remains in the conversation' in state_ev['notice']
    assert state_ev['state']['problem']['statement']['text'] == ''


def test_extraction_retry_succeeds_on_second_try():
    extract = FakeExtract([{'nope': 1}, {'founder_facts': {}, 'analysis': {'why_now': ['Voice AI costs fell']}}])
    ev = events(studio.run_turn(new(), [], 'idea', FakeChat(), extract))
    s = next(e for e in ev if e['type'] == 'state')['state']
    assert extract.calls == 2 and s['why_now'][0]['text'] == 'Voice AI costs fell'


def test_evidence_hook_sources_are_registered_and_citable():
    def hook(state, msg):
        yield {'type': 'searching', 'terms': ['dental appointment software']}
        yield {'type': 'sources', 'results': [{'id': 'S1', 'url': 'https://weave.com', 'title': 'Weave dental platform',
                                               'snippet': 'Weave helps dental offices', 'provider': 'tavily'}],
               'search': {'terms': ['dental appointment software'], 'providers': ['tavily'],
                          'searched_at': '2026-11-24', 'unavailable': []}}
        yield {'type': 'research', 'analysis': {'competitors': [{'name': 'Weave', 'source_id': 'S1'}]}}
    extract = FakeExtract([{'founder_facts': {}}])
    chat = FakeChat()
    ev = events(studio.run_turn(new(), [], 'idea', chat, extract, evidence_hook=hook))
    assert [e['type'] for e in ev][:3] == ['start', 'searching', 'sources']
    assert 'S1 [tavily] Weave dental platform' in chat.messages[1]['content']
    s = next(e for e in ev if e['type'] == 'state')['state']
    assert s['why_not_built']['competitors'][0]['name'] == 'Weave' and 'S1' in s['sources']


def test_history_is_trimmed_to_recent_messages():
    chat = FakeChat()
    history = [{'role': 'user' if i % 2 else 'assistant', 'content': f'm{i}'} for i in range(30)]
    events(studio.run_turn(new(), history, 'latest', chat, FakeExtract([{'founder_facts': {}}])))
    convo = [m for m in chat.messages if m['role'] != 'system']
    assert len(convo) == studio.CHAT_HISTORY + 1 and convo[-1]['content'] == 'latest'


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from app import create_app
    fakes = {'IDEA_CHAT_MODEL': FakeChat(),
             'IDEA_EXTRACT_MODEL': FakeExtract([{'founder_facts': {'problem': 'Dentists lose time'}}]),
             'IDEA_READ_MODEL': FakeExtract([{'kinds': ['answer']}] * 5)}
    monkeypatch.setattr(studio, '_llm', lambda env: fakes[env])
    return create_app().test_client()


def sse(resp):
    return [json.loads(l[6:]) for l in resp.get_data(as_text=True).splitlines() if l.startswith('data: ')]


def test_api_new_turn_edit_lock(client):
    start = client.get('/api/idea/new').get_json()['data']
    state = start['state']
    assert start['opening'] and state['clarity']['score'] == 0 and state['meta']['session_id']

    ev = sse(client.post('/api/idea/turn', json={'state': state, 'messages': [], 'content': 'Dental reminder idea'}))
    assert ev[-1]['type'] == 'done'
    state = next(e for e in ev if e['type'] == 'state')['state']
    assert state['problem']['statement']['text'] == 'Dentists lose time'
    assert state['meta']['session_id'] == start['state']['meta']['session_id']

    edited = client.post('/api/idea/edit', json={'state': state, 'path': '/problem/who',
                                                 'text': 'Office managers at 3 chair dental practices'}).get_json()
    s2 = edited['data']['state']
    assert s2['problem']['who']['locked'] and s2['problem']['who']['status'] == 'founder_stated'
    unlocked = client.post('/api/idea/lock', json={'state': s2, 'path': '/problem/who', 'locked': False}).get_json()
    assert unlocked['data']['state']['problem']['who']['locked'] is False
    bad = client.post('/api/idea/lock', json={'state': s2, 'path': '/clarity', 'locked': True})
    assert bad.status_code == 400


def test_api_turn_validation(client):
    assert client.post('/api/idea/turn', json={'content': ' '}).status_code == 400
    assert client.post('/api/idea/turn', json={'content': 'x' * 5000}).status_code == 400


def test_form_to_ops_code_decides_every_status():
    state = st.refresh(st.new_state('x'))
    state['open_objections'] = [{'text': 'No evidence of demand', 'raised_turn': 1}]
    form = {
        'founder_facts': {'who': 'AP clerk at a 40-person 3PL in Texas', 'severity': 'Found $18,000 overbilled in a quarter',
                          'frequency': '', 'bogus_slot': 'ignored'},
        'specific_fields': ['who', 'severity'],
        'contradictions': [],
        'analysis': {
            'wont_work': [{'text': 'Carriers may dispute audits', 'severity': 'high'}],
            'challenges': [{'kind': 'gtm', 'text': 'Reaching small 3PLs is fragmented'}, {'kind': 'nonsense', 'text': 'x'}],
            'risky_assumptions': [{'text': 'Small 3PLs will pay a share of recovered money', 'impact': 'fatal',
                                   'test': {'method': 'Offer 5 3PLs a free audit for 20% of recoveries', 'days': 7}}],
            'new_objections': ['Only one company observed'],
            'resolved_objections': [{'index': 0, 'new_fact': 'Found $18,000 overbilled'}, {'index': 7, 'new_fact': 'x'}],
            'competitors': [{'name': 'Invented Co', 'source_id': 'S1'}],
        },
    }
    ops = studio.form_to_ops(form, state)
    new, applied, rejected = st.apply_patch(state, ops)
    assert new['problem']['who']['status'] == 'founder_stated' and new['problem']['who']['specific']
    assert new['what_wont_work'][0]['status'] == 'ai_inference' and new['what_wont_work'][0]['severity'] == 'high'
    assert [c['text'] for c in new['challenges']['go_to_market']] == ['Reaching small 3PLs is fragmented']
    assert new['risky_assumptions'][0]['impact'] == 'fatal'
    assert [o['text'] for o in new['open_objections']] == ['Only one company observed']   # old one resolved
    assert new['why_not_built']['competitors'] == [] and len(rejected) == 1              # unsourced company


def test_contradiction_slot_marks_the_field():
    state = st.refresh(st.new_state('x'))
    ops = studio.form_to_ops({'founder_facts': {'frequency': 'Actually only monthly'},
                              'contradictions': ['frequency']}, state)
    assert ops[0]['value']['status'] == 'contradiction'


def test_tidy_reply_repairs_bold():
    assert studio.tidy_reply('Good point. What do they pay? **') == 'Good point. What do they pay?'
    assert studio.tidy_reply('Nice.\n**Who pays?**') == 'Nice.\n**Who pays?**'


@pytest.mark.parametrize('raw,expected', [
    ('Clear gap.\n\nWhat happened last time?\n\n**Is this the feedback you wanted?**', 'Clear gap.\n\n**What happened last time?**'),
    ('Nice.\n**Who pays?**\n**And how much?**', 'Nice.\n**Who pays?**'),
    ('Good. Who pays? How much?', 'Good. How much?'),
    ('Solid evidence.\n\n**Who signs off?**', 'Solid evidence.\n\n**Who signs off?**'),
])
def test_tidy_reply_keeps_exactly_one_question(raw, expected):
    out = studio.tidy_reply(raw)
    assert out == expected and out.count('?') == 1


def test_why_not_built_summary_needs_sources():
    state = st.refresh(st.new_state('x'))
    assert studio.form_to_ops({'founder_facts': {}, 'analysis': {'why_not_built_summary': 'Guess'}}, state) == []


def test_state_to_brief_maps_fields_and_readiness():
    s = st.refresh(st.new_state('x'))
    s = st.add_sources(s, [{'id': 'S1', 'url': 'https://freightpop.com', 'title': 'FreightPOP freight audit'}])
    spec = lambda t: {'text': t, 'status': 'founder_stated', 'specific': True}
    s, _, rejected = st.apply_patch(s, [
        {'op': 'replace', 'path': '/one_liner', 'value': spec('Freight invoice audits for small 3PLs')},
        {'op': 'replace', 'path': '/problem/statement', 'value': spec('Carriers overbill small 3PLs on freight invoices')},
        {'op': 'replace', 'path': '/problem/who', 'value': spec('AP clerks at 3PLs with 20 to 100 people')},
        {'op': 'replace', 'path': '/problem/severity', 'value': spec('About $18,000 overbilled in one quarter')},
        {'op': 'replace', 'path': '/problem/workaround', 'value': spec('An AP clerk checks 10 percent of invoices by hand')},
        {'op': 'replace', 'path': '/business_model/price_anchor', 'value': spec('20 percent of recovered overcharges')},
        {'op': 'add', 'path': '/what_could_work/-', 'value': 'Partner with freight brokers who already serve 3PLs'},
        {'op': 'add', 'path': '/what_wont_work/-', 'value': {'text': 'Carriers may dispute audit findings', 'severity': 'high'}},
        {'op': 'add', 'path': '/why_not_built/competitors/-', 'value': {'name': 'FreightPOP', 'source_ids': ['S1']}},
    ])
    assert not rejected
    out = studio.state_to_brief(s, 'FreightGuard')
    b = out['brief']
    assert b['productName'] == 'FreightGuard'
    assert b['painPoint'] == 'Carriers overbill small 3PLs on freight invoices'
    assert b['icp'] == 'AP clerks at 3PLs with 20 to 100 people'
    assert b['competitors'] == 'FreightPOP' and b['salesChannel'] == 'partnerships'
    assert b['pricingModel'] == '20 percent of recovered overcharges'
    assert 'Carriers may dispute' in b['existingProblems']
    assert out['ready'] is False and out['ready_at'] == 60 and out['missing']


def test_suggest_name_cleans_and_falls_back():
    s = st.refresh(st.new_state('x'))
    s['one_liner']['text'] = 'Freight audits for small 3PLs'

    class Namer:
        def chat_json(self, m, **kw):
            return {'name': '"FreightGuard!"'}

    class Broken:
        def chat_json(self, m, **kw):
            raise RuntimeError('down')
    assert studio.suggest_name(s, Namer()) == 'FreightGuard'
    assert studio.suggest_name(s, Broken()) == ''


def test_analyst_model_defaults(monkeypatch):
    monkeypatch.delenv('IDEA_EXTRACT_MODEL', raising=False)
    monkeypatch.delenv('IDEA_CHAT_MODEL', raising=False)
    monkeypatch.setenv('LLM_BASE_URL', 'https://openrouter.ai/api/v1')
    assert studio.model_for('IDEA_EXTRACT_MODEL') == 'openai/gpt-4.1-mini'
    assert studio.model_for('IDEA_CHAT_MODEL') is None
    monkeypatch.setenv('IDEA_EXTRACT_MODEL', 'openai/gpt-4o-mini')
    assert studio.model_for('IDEA_EXTRACT_MODEL') == 'openai/gpt-4o-mini'
    monkeypatch.delenv('IDEA_EXTRACT_MODEL')
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.openai.com/v1')
    assert studio.model_for('IDEA_EXTRACT_MODEL') is None


def test_brainstorm_api_advances_hints_without_changing_the_active_idea(client, monkeypatch):
    chat = FakeChat(chunks=('Schedule changes might not reach the next shift.\n'
                            'Handoffs may depend on one supervisor.\n'
                            'Time records may disagree across tools.',))
    monkeypatch.setattr(studio, '_llm', lambda env: chat if env == 'IDEA_CHAT_MODEL' else pytest.fail(env))
    state = client.get('/api/idea/new').get_json()['data']['state']
    state = st.founder_edit(state, '/problem/statement', 'A problem already in the brief')
    state['brainstorm'].update(mode='brainstorm', candidates=['A separate founder observation'])
    problem = state['problem']
    progress = state['meta']

    for content, assistance, expected_level in [
        ('Give me a hint.', 'hint', 1),
        ("I'm stuck.", '', 2),
        ('Show me rough ideas.', 'sparks', 4),
        ('Shift leads copy the schedule into three spreadsheets every day.', '', 0),
    ]:
        stream = sse(client.post('/api/idea/turn', json={
            'state': state, 'content': content, 'assistance': assistance,
        }))
        assert stream[-1]['type'] == 'done'
        reply = next(event for event in stream if event['type'] == 'reply')
        assert ('AI-suggested hypotheses' in reply['content']) == (expected_level == 4)
        assert reply['content'].count('?') == 1
        state = next(event for event in stream if event['type'] == 'state')['state']
        assert state['brainstorm']['hint_level'] == expected_level
        assert state['brainstorm']['candidates'] == ['A separate founder observation']
        assert state['problem'] == problem
        assert state['meta'] == progress


def test_stress_test_routes_to_risk_and_preserves_brief_when_analyst_is_down():
    state = st.refresh(st.new_state())
    state['brainstorm']['mode'] = 'stress-test'
    chat = FakeChat()
    stream = events(studio.run_turn(state, [], 'What could kill the idea?',
                                    chat_llm=chat, extract_llm=FakeExtract([])))
    assert stream[0]['next_question']['field'] == 'risky_assumptions'
    assert 'Mode: Stress-test' in chat.messages[-1]['content']
    updated = next(event for event in stream if event['type'] == 'state')['state']
    assert updated['problem']['statement']['text'] == ''


def test_off_domain_answer_is_quarantined_and_blocks_prefill(client):
    state = st.founder_edit(new(), '/problem/who', 'Alex, solo founder')
    extract = FakeExtract([{'founder_facts': {
        'who': 'RF engineer at Amdocs', 'problem': 'Cell towers use too much energy',
    }}])
    stream = events(studio.run_turn(state, [], 'RF engineer at Amdocs', FakeChat(), extract))
    state = next(event for event in stream if event['type'] == 'state')['state']
    assert state['problem']['who']['text'] == 'Alex, solo founder'
    assert state['problem']['statement']['text'] == ''
    assert state['conflicts'] == {'/problem/who': 'RF engineer at Amdocs'}
    assert client.post('/api/idea/brief', json={'state': state}).status_code == 409

    response = client.post('/api/idea/resolve-conflict', json={
        'state': state, 'path': '/problem/who', 'choice': 'replace',
    })
    updated = response.get_json()['data']['state']
    assert updated['conflicts'] == {}
    assert updated['problem']['who']['text'] == 'RF engineer at Amdocs'
    assert updated['history'][-1]['revisions'][0]['before']['text'] == 'Alex, solo founder'


@pytest.mark.parametrize('text', [
    'some examples',
    'help me increase the score to moe than 60',
    'Meet Alex, a solo founder who prioritizes original thinking.',
    'mark that as pending and top priority',
])
def test_non_answer_turns_bypass_extraction_and_preserve_interview_slot(text):
    examples = ['Can you describe the last time?', 'What did it cost?']
    chat = FakeExtract([{'acknowledgment': 'Try these prompts.', 'coaching_items': examples}])
    extractor = FakeExtract([{'founder_facts': {'who': 'Different customer'}}])
    stream = events(studio.run_turn(new(), [], text, chat, extractor))
    reply = next(event for event in stream if event['type'] == 'reply')
    state = next(event for event in stream if event['type'] == 'state')['state']
    assert reply['coaching_items'] == examples
    assert reply['ask']['question'] == ''
    assert extractor.calls == 0 and not state['history']
    assert state['problem']['who']['text'] == ''
    if 'pending' in text:
        assert state['parked'][0]['priority'] == 'top'


def test_simulation_coherence_check_rejects_existing_mixed_brief():
    state = st.founder_edit(new(), '/one_liner', 'MindForge is a cognitive gym for solo founders.')
    state = st.founder_edit(state, '/problem/who', 'RF engineers at Amdocs')
    state = st.founder_edit(state, '/problem/statement', 'Cell towers draw too much power')
    judge = FakeExtract([{'aligned': False, 'issue': 'The pain describes telecommunications.'}])
    assert 'telecommunications' in studio.check_brief_coherence(state, judge)
