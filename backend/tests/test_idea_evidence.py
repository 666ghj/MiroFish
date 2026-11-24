"""Idea Studio evidence service: providers, filtering, caching, triggers (no network)."""

import pytest

from app.config import Config
from app.services import idea_evidence as ev
from app.services import idea_state as st
from app.services import idea_studio as studio


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    ev._mem_cache.clear()
    monkeypatch.setenv('TAVILY_API_KEY', 'tvly-test')
    monkeypatch.setenv('EXA_API_KEY', 'exa-test')
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)


def fake_request(calls):
    def _req(url, body=None, headers=None):
        calls.append((url, body, headers))
        if 'tavily' in url:
            return {'results': [{'title': 'FreightPOP freight audit software', 'url': 'https://freightpop.com/audit',
                                 'content': '## Audit every invoice\nAutomatically catch carrier overcharges.'}]}
        if 'exa.ai' in url:
            return {'results': [{'title': 'Intelligent Audit', 'url': 'https://intelligentaudit.com',
                                 'highlights': ['Intelligent Audit is a transportation audit company.']}]}
        if 'algolia' in url:
            return {'hits': [{'title': 'Show HN: Freight invoice audit for small shippers', 'objectID': '1',
                              'points': 40, 'num_comments': 12, 'created_at': '2025-03-01T00:00:00Z'},
                             {'title': 'Show HN: Observability for Flink', 'objectID': '2'}]}
        if 'github' in url:
            return {'items': [{'full_name': 'x/freight-invoice-audit', 'description': 'Audit freight invoices',
                               'html_url': 'https://github.com/x/freight-invoice-audit', 'stargazers_count': 3,
                               'pushed_at': '2026-10-01', 'created_at': '2026-01-01'},
                              {'full_name': 'y/flink-jobs', 'description': 'stream processing',
                               'html_url': 'https://github.com/y/flink-jobs'}]}
        raise AssertionError(url)
    return _req


QUERIES = {'competitors': 'freight invoice audit software for small 3PLs', 'graveyard': 'freight invoice audit startup shut down',
           'semantic': 'a company that audits freight invoices', 'hn': 'freight invoice audit', 'oss': 'freight invoice audit'}


def test_sweep_runs_all_providers_filters_and_ids(monkeypatch):
    calls = []
    monkeypatch.setattr(ev, '_request', fake_request(calls))
    out = ev.sweep(QUERIES)
    assert set(out['providers']) == {'tavily', 'exa', 'hn', 'github'} and out['unavailable'] == []
    titles = [r['title'] for r in out['results']]
    assert 'Show HN: Observability for Flink' not in titles             # irrelevant HN dropped
    assert not any('flink-jobs' in t for t in titles)                   # irrelevant repo dropped
    assert all(r['id'].startswith('S') and len(r['id']) == 7 for r in out['results'])
    tav = next(r for r in out['results'] if r['provider'] == 'tavily')
    assert '#' not in tav['snippet'] and tav['purpose'] in ('competitors', 'graveyard')
    # auth headers and only neutral phrases sent
    tav_call = next(c for c in calls if 'tavily' in c[0])
    assert tav_call[2]['Authorization'] == 'Bearer tvly-test' and tav_call[1]['query'] in QUERIES.values()
    exa_call = next(c for c in calls if 'exa.ai' in c[0])
    assert exa_call[2]['x-api-key'] == 'exa-test' and exa_call[1]['category'] == 'company'


def test_missing_keys_are_reported_not_silent(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY')
    monkeypatch.delenv('EXA_API_KEY')
    monkeypatch.setattr(ev, '_request', fake_request([]))
    out = ev.sweep(QUERIES)
    assert 'tavily (not configured)' in out['unavailable'] and 'exa (not configured)' in out['unavailable']
    assert set(out['providers']) == {'hn', 'github'}


def test_provider_errors_are_reported(monkeypatch):
    import urllib.error

    def boom(url, body=None, headers=None):
        if 'exa.ai' in url:
            raise urllib.error.URLError('timeout')
        return fake_request([])(url, body, headers)
    monkeypatch.setattr(ev, '_request', boom)
    assert 'exa (error)' in ev.sweep(QUERIES)['unavailable']


def test_results_are_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(ev, '_request', fake_request(calls))
    ev.sweep(QUERIES)
    first = len(calls)
    ev._mem_cache.clear()          # disk cache still serves
    ev.sweep(QUERIES)
    assert first == 5 and len(calls) == first


def test_planner_uses_llm_phrases_and_falls_back():
    class LLM:
        def chat_json(self, m, **kw):
            return {'category': 'freight invoice audit', 'buyer': 'small 3PLs', 'job': 'audits carrier invoices'}
    s = st.refresh(st.new_state('x'))
    s['one_liner']['text'] = 'Software that audits freight invoices for small logistics companies'
    q = ev.plan_queries(s, LLM())
    assert q['competitors'] == 'freight invoice audit software for small 3PLs'
    assert q['semantic'] == 'a company that audits carrier invoices for small 3PLs'

    class Broken:
        def chat_json(self, m, **kw):
            raise RuntimeError('down')
    q2 = ev.plan_queries(s, Broken())
    assert 'freight' in q2['competitors'].lower()


def idea_state(turn=2, sweeps=0, with_idea=True):
    s = st.refresh(st.new_state('x'))
    s['meta']['turn'] = turn
    s['why_not_built']['search']['sweeps'] = sweeps
    if with_idea:
        s['one_liner']['text'] = 'Freight invoice audits for small 3PLs'
    return s


def test_trigger_policy():
    assert ev.should_search(idea_state(turn=1), False) is None        # too early
    assert ev.should_search(idea_state(turn=2), False) == 'auto'
    assert ev.should_search(idea_state(turn=5, sweeps=1), False) is None   # auto only once
    assert ev.should_search(idea_state(turn=5, sweeps=1), True) == 'requested'
    assert ev.should_search(idea_state(turn=5, sweeps=ev.MAX_SWEEPS), True) is None
    assert ev.should_search(idea_state(with_idea=False), False) is None


def test_hook_confidential_and_limit():
    hook = ev.make_hook(requested=True, confidential=True, sweep_fn=lambda q: pytest.fail('searched'))
    assert [e['type'] for e in hook(idea_state(), 'x')] == ['evidence_skipped']
    hook = ev.make_hook(requested=True, sweep_fn=lambda q: pytest.fail('searched'))
    out = list(hook(idea_state(sweeps=ev.MAX_SWEEPS), 'x'))
    assert out[0]['type'] == 'evidence_skipped' and 'limit' in out[0]['reason']


def test_hook_in_a_turn_registers_sources_and_asks_differentiation():
    class Planner:
        def chat_json(self, m, **kw):
            return {'category': 'freight invoice audit', 'buyer': 'small 3PLs', 'job': 'audits invoices'}

    def fake_sweep(queries):
        return {'results': [{'id': 'Sabc123', 'url': 'https://freightpop.com', 'title': 'FreightPOP freight audit',
                             'snippet': 'Audit software', 'provider': 'tavily', 'purpose': 'competitors'}],
                'providers': ['tavily'], 'unavailable': ['exa (not configured)']}

    class Chat:
        messages = None
        def chat_stream(self, messages, **kw):
            Chat.messages = messages
            yield 'Here is what exists.\n\n**Why would they pick you over FreightPOP?**'

    class Extract:
        def chat_json(self, m, **kw):
            return {'founder_facts': {}}

    class Synth:
        def chat_json(self, m, **kw):
            return {
                'competitors': [{'name': 'FreightPOP', 'source_id': 'Sabc123', 'status': 'active'}],
                'classification': 'exists_unknown'}

    hook = ev.make_hook(planner_llm=Planner(), sweep_fn=fake_sweep, synth_llm=Synth())
    events = list(studio.run_turn(idea_state(turn=1), [], 'It audits invoices', Chat(), Extract(), evidence_hook=hook))
    kinds = [e['type'] for e in events]
    assert kinds[:3] == ['start', 'searching', 'sources']
    assert 'compares to what already exists' in Chat.messages[1]['content']
    s = next(e for e in events if e['type'] == 'state')['state']
    assert s['why_not_built']['competitors'][0]['name'] == 'FreightPOP'
    assert s['why_not_built']['classification'] == 'exists_unknown'
    assert s['why_not_built']['search']['sweeps'] == 1
    assert s['why_not_built']['search']['unavailable'] == ['exa (not configured)']
    assert s['sources']['Sabc123']['purpose'] == 'competitors'


class Synth:
    def __init__(self, out):
        self.out, self.messages = out, None

    def chat_json(self, messages, **kw):
        self.messages = messages
        return self.out


RESULTS = [
    {'id': 'S1', 'url': 'https://gartner.com/freight-audit', 'title': 'Best Freight Audit Providers 2026 | Gartner',
     'snippet': 'Compare freight audit vendors', 'provider': 'tavily', 'purpose': 'competitors'},
    {'id': 'S2', 'url': 'https://trimble.com/audit', 'title': 'Trimble Freight Audit Software',
     'snippet': 'Trimble automates freight invoice audits', 'provider': 'tavily', 'purpose': 'competitors'},
    {'id': 'S3', 'url': 'https://news.com/shipsmart', 'title': 'ShipSmart shuts down its audit product',
     'snippet': 'ShipSmart closed after failing to win small shippers', 'provider': 'tavily', 'purpose': 'graveyard'},
]


def test_synthesis_sees_results_as_untrusted_data():
    synth = Synth({'competitors': [], 'classification': 'crowded_funded', 'summary': 'Established vendors exist.'})
    out = ev.synthesize(idea_state(), RESULTS, synth)
    assert out['classification'] == 'crowded_funded'
    assert 'untrusted' in synth.messages[0]['content'] and 'S2 [tavily/competitors] Trimble' in synth.messages[1]['content']
    assert ev.synthesize(idea_state(), [], synth) == {}


def test_research_event_applies_validated_findings_before_the_reply():
    synth = Synth({
        'competitors': [{'name': 'Trimble', 'source_id': 'S2', 'status': 'active', 'note': 'Freight audit suite'},
                        {'name': 'Gartner', 'source_id': 'S1'},                 # review site: rejected in code
                        {'name': 'MadeUp Audit Co', 'source_id': 'S2'}],        # not in its source: rejected
        'predecessors': [{'name': 'ShipSmart', 'source_id': 'S3', 'failure_reason': 'could not win small shippers'}],
        'classification': 'crowded_funded', 'summary': 'Established vendors already sell audits.'})

    class Chat:
        messages = None
        def chat_stream(self, messages, **kw):
            Chat.messages = messages
            yield 'Trimble already sells this.\n\n**What is different for small 3PLs?**'

    class Extract:
        def chat_json(self, m, **kw):
            return {'founder_facts': {}}

    hook = ev.make_hook(planner_llm=Synth({'category': 'freight audit'}),
                        sweep_fn=lambda q: {'results': RESULTS, 'providers': ['tavily'], 'unavailable': []},
                        synth_llm=synth)
    events = list(studio.run_turn(idea_state(turn=1), [], 'nobody serves small 3PLs', Chat(), Extract(), evidence_hook=hook))
    research = next(e for e in events if e['type'] == 'research')
    assert research['competitors'] == ['Trimble'] and research['predecessors'] == ['ShipSmart']
    assert research['classification'] == 'crowded_funded' and research['rejected'] == 2   # review site + invented
    assert 'competitor: Trimble' in Chat.messages[1]['content']     # the co-founder sees the findings
    s = next(e for e in events if e['type'] == 'state')['state']
    assert s['why_not_built']['predecessors'][0]['status'] == 'dead'
    assert s['why_not_built']['summary']['text'] == 'Established vendors already sell audits.'


def test_planner_does_not_double_the_word_software():
    q = ev.plan_queries(idea_state(), Synth({'category': 'freight audit software', 'buyer': 'small 3PLs', 'job': 'audits'}))
    assert q['competitors'] == 'freight audit software for small 3PLs'
