"""Idea Studio agent team: readiness, fingerprint skipping, stages, normalization, failures, API."""

import json
import threading

import pytest

from app.services import idea_agents as ag
from app.services import idea_state as st


def filled_state():
    s = st.new_state('t')
    s['problem']['statement'] = {**s['problem']['statement'], 'text': 'Carriers overbill small 3PLs', 'status': 'founder_stated'}
    s['problem']['who'] = {**s['problem']['who'], 'text': 'AP clerks at 3PLs with 20 to 100 people', 'status': 'founder_stated'}
    s['solution']['core'] = {**s['solution']['core'], 'text': 'Software that flags overcharges', 'status': 'founder_stated'}
    return st.refresh(s)


GOOD = {
    'skeptic': {'headline': 'Data access is the gate.', 'risks': [{'title': 'No data', 'why': 'x', 'severity': 'FATAL', 'answer_with': 'y'}]},
    'customers': {'headline': 'Two would try it.', 'panel': [
        {'persona': 'a', 'reaction': 'yes please', 'would_try': 'yes'},
        {'persona': 'b', 'reaction': 'hmm', 'would_try': 'perhaps'},
        {'persona': 'c', 'reaction': 'no thanks', 'would_try': 'no'}]},
    'market': {'headline': 'Small but real.', 'unit': '3PL', 'count': '4,000', 'price_per_year': '$3000', 'confidence': 'high'},
    'pitch': {'headline': 'Lead with money.', 'one_liners': ['a', 'b', 'c', 'd'], 'elevator': 'e', 'avoid': 'AI'},
    'gtm': {'headline': 'LinkedIn.', 'channel': 'LinkedIn DMs', 'first_10': ['a'], 'week_one': ['b']},
    'experiments': {'headline': 'Test data access.', 'tests': [{'assumption': 'a', 'method': 'm', 'cost': '$0', 'days': 500, 'pass_if': 'p'}]},
    'chief': {'headline': 'Narrow it.', 'verdict': 'Keep going', 'why': 'w', 'next_actions': ['1', '2', '3', '4']},
}


class FakeLLM:
    def __init__(self, agent_id, log, fail=()):
        self.agent_id, self.log, self.fail = agent_id, log, fail

    def chat_json(self, messages, **kw):
        with ag_lock:
            self.log.append((self.agent_id, messages))
        if self.agent_id in self.fail:
            raise RuntimeError('boom')
        return GOOD[self.agent_id]


ag_lock = threading.Lock()


def factory(log, fail=()):
    return lambda agent_id: FakeLLM(agent_id, log, fail)


@pytest.fixture(autouse=True)
def no_mock(monkeypatch):
    monkeypatch.delenv('MOCK_MODE', raising=False)


def run(state, prior=None, **kw):
    return list(ag.run_team(state, prior, **kw))


def test_empty_idea_everyone_waits_and_nothing_runs():
    log = []
    ev = run(st.new_state('t'), llm_factory=factory(log))
    plan = ev[0]
    assert plan['type'] == 'plan' and all(p['status'] == 'waiting' for p in plan['agents'])
    assert 'the problem' in plan['agents'][0]['missing']
    assert log == [] and ev[-1] == {'type': 'done', 'ran': 0}


def test_full_run_stage_order_and_normalization():
    log = []
    ev = run(filled_state(), llm_factory=factory(log))
    done = {e['id']: e for e in ev if e['type'] == 'agent' and e['status'] == 'done'}
    assert set(done) == set(ag.AGENT_IDS)
    # stage 2 runs after every stage-1 agent finished
    order = [e['id'] for e in ev if e['type'] == 'agent' and e['status'] == 'done']
    assert order.index('chief') > max(order.index(i) for i in ('skeptic', 'customers', 'market', 'pitch', 'gtm'))
    assert done['skeptic']['output']['risks'][0]['severity'] == 'fatal'
    assert done['customers']['output']['tally'] == {'yes': 1, 'maybe': 1, 'no': 1}
    assert done['customers']['output']['synthetic'] is True
    m = done['market']['output']
    assert (m['count'], m['price_per_year'], m['estimate'], m['confidence']) == (4000, 3000, 12_000_000, 'low')
    assert len(done['pitch']['output']['one_liners']) == 3
    assert done['experiments']['output']['tests'][0]['days'] == 90
    assert done['chief']['output']['verdict'] == 'keep_going' and len(done['chief']['output']['next_actions']) == 3
    # the chief saw its teammates' findings
    chief_msgs = [m for a, m in log if a == 'chief'][0]
    assert 'TEAM FINDINGS' in chief_msgs[1]['content'] and 'Skeptic' in chief_msgs[1]['content']


def test_unchanged_inputs_are_skipped_and_changes_rerun_only_readers():
    log = []
    s = filled_state()
    ev = run(s, llm_factory=factory(log))
    prior = {e['id']: {'output': e['output'], 'fingerprint': e['fingerprint']}
             for e in ev if e['type'] == 'agent' and e['status'] == 'done'}
    log.clear()
    ev2 = run(s, prior, llm_factory=factory(log))
    assert log == [] and ev2[-1]['ran'] == 0
    # changing the price touches market, gtm, customers, skeptic (and chief downstream), not pitch
    s['business_model']['price_anchor'] = {**s['business_model']['price_anchor'], 'text': '$300 a month', 'status': 'founder_stated'}
    log.clear()
    run(s, prior, llm_factory=factory(log))
    reran = {a for a, _ in log}
    assert {'market', 'gtm', 'customers', 'skeptic', 'chief'} <= reran and 'pitch' not in reran
    # forcing one agent reruns just that one
    log.clear()
    run(s, prior, only=['pitch'], force=True, llm_factory=factory(log))
    assert {a for a, _ in log} == {'pitch'}


def test_failure_is_reported_and_chief_still_runs_with_enough_inputs():
    log = []
    ev = run(filled_state(), llm_factory=factory(log, fail=('market',)))
    failed = [e for e in ev if e.get('status') == 'failed']
    assert [e['id'] for e in failed] == ['market'] and 'last result is kept' in failed[0]['error']
    assert any(e.get('id') == 'chief' and e.get('status') == 'done' for e in ev)


def test_chief_waits_without_enough_teammates():
    ev = run(filled_state(), only=['chief'], llm_factory=factory([]))
    chief = [e for e in ev if e.get('id') == 'chief' and e['type'] == 'agent']
    assert chief[-1]['status'] == 'waiting'


def test_mock_mode_serves_labelled_samples(monkeypatch):
    monkeypatch.setenv('MOCK_MODE', 'true')
    ev = run(filled_state(), llm_factory=lambda _: pytest.fail('no LLM in mock mode'))
    done = [e for e in ev if e.get('status') == 'done']
    assert done and all(e['source'] == 'sample' for e in done)


def test_normalize_strips_em_dashes_and_bad_shapes():
    out = ag.normalize('pitch', {'headline': 'Fast — cheap', 'one_liners': 'not a list'})
    assert '—' not in out['headline'] and out['one_liners'] == []
    assert ag.normalize('skeptic', 'garbage') == {'headline': '', 'risks': []}


def test_api_roster_and_stream(monkeypatch):
    from app import create_app
    monkeypatch.setenv('MOCK_MODE', 'true')
    client = create_app().test_client()
    r = client.get('/api/idea/team')
    assert [a['id'] for a in r.get_json()['data']['agents']] == ag.AGENT_IDS
    r = client.post('/api/idea/team', json={'state': filled_state(), 'team': {}})
    events = [json.loads(l[6:]) for l in r.get_data(as_text=True).splitlines() if l.startswith('data: ')]
    assert events[0]['type'] == 'plan' and events[-1]['type'] == 'done' and events[-1]['ran'] == 7
