"""Tests for the multi-run reaction simulator and the aggregator's stability metrics.
Uses a fake LLM; no network calls."""

import json
import re
import threading

import pytest

from app.services import gtm_reaction_simulator as sim_mod
from app.services.gtm_aggregator import aggregate
from app.services.gtm_reaction_simulator import GTMReactionSimulator, SYSTEM_PROMPT

PERSONAS = [
    {
        'id': f'p{i}', 'name': f'Persona {i}', 'title': 'VP Sales', 'company_type': 'SaaS',
        'company_stage': 'Series A', 'primary_goal': 'pipeline', 'skepticism_level': 3,
        'objections': ['price'],
    }
    for i in range(12)
]
MESSAGES = [
    {'id': 'm_pain', 'angle': 'pain_first', 'subject_line': 's', 'body': 'b'},
    {'id': 'm_roi', 'angle': 'roi_first', 'subject_line': 's', 'body': 'b'},
]


class FakeLLM:
    """Returns one reaction per persona in the prompt. `score_fn(message_id, persona_id, call_no)`
    decides interest; `fail_calls` makes the first N calls raise."""

    def __init__(self, score_fn, fail_calls=0, drop_scores=False):
        self.score_fn = score_fn
        self.fail_calls = fail_calls
        self.drop_scores = drop_scores
        self.calls = 0
        self.lock = threading.Lock()

    def chat_json(self, messages, temperature=0.3, max_tokens=4096):
        with self.lock:
            self.calls += 1
            call_no = self.calls
        if call_no <= self.fail_calls:
            raise RuntimeError('boom')
        user = messages[1]['content']
        message_id = re.search(r'Set message_id to "([^"]+)"', user).group(1)
        persona_ids = re.findall(r'^- (p\d+):', user, flags=re.M)
        out = []
        for pid in persona_ids:
            r = {
                'id': '', 'persona_id': pid, 'message_id': message_id,
                'interest_score': self.score_fn(message_id, pid, call_no),
                'clarity_score': 6, 'trust_score': 6, 'urgency_score': 6,
                'objection': 'o', 'buying_trigger': 't', 'preferred_cta': 'c',
                'risk_signal': 'r', 'simulated_reply': f'reply {pid}', 'verdict': 'x',
            }
            if self.drop_scores:
                del r['trust_score']
            out.append(r)
        return out


@pytest.fixture(autouse=True)
def _no_mock_mode(monkeypatch):
    monkeypatch.delenv('MOCK_MODE', raising=False)


def test_prompt_no_longer_hardcodes_who_scores_low():
    assert 'should score lower' not in SYSTEM_PROMPT
    assert 'finance buyers' not in SYSTEM_PROMPT


def test_runs_batches_and_merges():
    llm = FakeLLM(lambda m, p, c: 8.0 if m == 'm_roi' else 5.0)
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=3)

    assert result['source'] == 'llm'
    assert result['mock_reason'] is None
    assert result['runs_completed'] == 3
    assert result['coverage'] == 1.0
    # 12 personas / batch of 6 = 2 calls per message per run
    assert llm.calls == 3 * len(MESSAGES) * 2
    assert len(result['reactions']) == len(MESSAGES) * len(PERSONAS)
    one = result['reactions'][0]
    assert len(one['interest_score_runs']) == 3
    assert one['interest_score_spread'] == 0.0


def test_scores_are_averaged_across_runs():
    # Interest alternates 4 / 8 by call number, so the merged mean must be between them.
    llm = FakeLLM(lambda m, p, c: 4.0 if c % 2 else 8.0)
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=2)
    for r in result['reactions']:
        assert 4.0 <= r['interest_score'] <= 8.0
        assert r['verdict'] in {'positive', 'neutral', 'negative'}


def test_failed_batch_is_retried_not_mocked():
    llm = FakeLLM(lambda m, p, c: 7.0, fail_calls=1)
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=1)
    assert result['source'] == 'llm'
    assert result['coverage'] == 1.0


def test_missing_scores_are_dropped_not_defaulted():
    llm = FakeLLM(lambda m, p, c: 7.0, drop_scores=True)
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=1)
    assert result['source'] == 'mock'
    assert 'succeeded' in result['mock_reason']


def test_llm_unavailable_is_labelled_mock():
    class Broken(GTMReactionSimulator):
        def _get_llm(self):
            raise ValueError('LLM_API_KEY is not configured')

    result = Broken().simulate(MESSAGES, PERSONAS)
    assert result['source'] == 'mock'
    assert 'LLM_API_KEY' in result['mock_reason']
    assert result['reactions']  # mock file still loads, so the demo stays runnable


def test_mock_mode_env(monkeypatch):
    monkeypatch.setenv('MOCK_MODE', 'true')
    llm = FakeLLM(lambda m, p, c: 7.0)
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS)
    assert result['source'] == 'mock'
    assert llm.calls == 0


def test_run_budget_caps_llm_calls():
    many = [dict(PERSONAS[0], id=f'p{i}') for i in range(120)]
    llm = FakeLLM(lambda m, p, c: 7.0)
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, many, runs=5)
    assert llm.calls <= sim_mod.MAX_LLM_CALLS
    assert result['runs_completed'] == 1


def test_stable_winner():
    llm = FakeLLM(lambda m, p, c: 8.0 if m == 'm_roi' else 5.0)
    sim = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=3)
    agg = aggregate(MESSAGES, sim['reactions'], sim['run_reactions'])
    w = agg['winner']
    assert w['winner_message_id'] == 'm_roi'
    assert w['runs'] == 3
    assert w['win_rate'] == 1.0
    assert w['stability'] == 'stable'
    roi = next(s for s in agg['summaries'] if s['message_id'] == 'm_roi')
    assert roi['interest_score_range'] == [8.0, 8.0]


def test_unstable_winner_is_flagged_as_tie():
    # Run 0 favours pain, runs 1-2 favour roi on average but run 1 flips.
    reactions_by_run = []
    for run, (pain, roi) in enumerate([(8, 5), (5, 8), (8, 5)]):
        reactions_by_run.append([
            {'persona_id': p['id'], 'message_id': mid, 'interest_score': score,
             'clarity_score': 5, 'trust_score': 5, 'urgency_score': 5, 'objection': 'o'}
            for p in PERSONAS for mid, score in (('m_pain', pain), ('m_roi', roi))
        ])
    merged = sim_mod._merge_runs(reactions_by_run)
    w = aggregate(MESSAGES, merged, reactions_by_run)['winner']
    assert w['winner_message_id'] == 'm_pain'
    assert w['win_rate'] == pytest.approx(0.67, abs=0.01)
    assert w['stability'] == 'leaning'


def test_single_run_has_no_win_rate():
    llm = FakeLLM(lambda m, p, c: 7.0)
    sim = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=1)
    w = aggregate(MESSAGES, sim['reactions'], sim['run_reactions'])['winner']
    assert w['stability'] == 'single_run'
    assert w['win_rate'] is None


def test_legacy_aggregate_call_still_works():
    reactions = [
        {'persona_id': 'p1', 'message_id': 'm_pain', 'interest_score': 6, 'objection': 'x'}
    ]
    agg = aggregate(MESSAGES, reactions)
    assert agg['winner']['winner_message_id'] == 'm_pain'
    assert agg['winner']['stability'] == 'single_run'


def test_simulate_all_wrapper_returns_list():
    llm = FakeLLM(lambda m, p, c: 7.0)
    out = GTMReactionSimulator(llm=llm).simulate_all(MESSAGES, PERSONAS)
    assert isinstance(out, list) and out
    json.dumps(out)  # serializable for the JSON file store


def test_generated_copy_has_no_em_dashes():
    from app.utils.text_style import strip_em_dashes
    raw = {'reply': 'Sounds good — send the case study', 'list': ['a—b', 3], 'n': 7.5}
    out = strip_em_dashes(raw)
    assert out == {'reply': 'Sounds good, send the case study', 'list': ['a-b', 3], 'n': 7.5}
    assert '—' not in SYSTEM_PROMPT


def test_simulated_reactions_are_cleaned():
    llm = FakeLLM(lambda m, p, c: 7.0)
    original = llm.chat_json

    def with_dash(messages, **kw):
        out = original(messages, **kw)
        for r in out:
            r['simulated_reply'] = 'Interesting — tell me more'
        return out

    llm.chat_json = with_dash
    result = GTMReactionSimulator(llm=llm).simulate(MESSAGES, PERSONAS, runs=1)
    assert all('—' not in r['simulated_reply'] for r in result['reactions'])


# ── Audience settings ────────────────────────────────────────────────────────

def test_audience_is_sanitized():
    from app.services.gtm_audience import normalize_audience
    a = normalize_audience({
        'mix': {'decision_maker': 250, 'champion': '40', 'evaluator': -3, 'hacker': 9},
        'colors': {'decision_maker': '#ff0000', 'champion': 'red;', 'evaluator': '#00ff00'},
        'regions': ['dach', 'mars', 'dach', 'india'],
        'company_sizes': ['11-50', 'huge'],
        'traits': {'risk_appetite': 9, 'skepticism': 'x'},
        'seed': 'abc',
    })
    assert a['mix'] == {'decision_maker': 100, 'champion': 40, 'evaluator': 0}
    assert a['colors']['champion'] == '#d95926'          # invalid color falls back
    assert a['regions'] == ['dach', 'india']              # unknown dropped, deduped
    assert a['company_sizes'] == ['11-50']
    assert a['traits']['risk_appetite'] == 5 and a['traits']['skepticism'] == 3
    assert normalize_audience('nope') is None


def test_audience_prompt_spells_out_role_counts_and_regions():
    from app.services.gtm_audience import audience_prompt, normalize_audience
    a = normalize_audience({'mix': {'decision_maker': 1, 'champion': 1, 'evaluator': 2},
                            'regions': ['nordics'], 'traits': {'risk_appetite': 5}})
    text = audience_prompt(a, 12)
    assert 'about 3 decision makers' in text and 'about 6 evaluators' in text
    assert 'Nordics' in text and 'very high (5/5)' in text
    assert audience_prompt(None, 12) == ''


def test_personas_always_leave_with_a_valid_mix_and_region():
    from app.services.gtm_audience import enrich_personas, normalize_audience
    a = normalize_audience({'mix': {'champion': 1}, 'regions': ['india', 'anz']})
    people = enrich_personas([
        {'persona_type': 'cfo'},                                             # no mix: derived
        {'persona_type': 'vp_sales', 'archetype_mix': {'decision_maker': 1, 'champion': 1, 'evaluator': 1},
         'region': 'india'},
        {'persona_type': 'x', 'archetype_mix': 'bad', 'region': 'mars'},
    ], a)
    for p in people:
        assert sum(p['archetype_mix'].values()) == 100
        assert p['region'] in ('india', 'anz')
    assert people[0]['archetype_mix'] == {'decision_maker': 65, 'champion': 0, 'evaluator': 35}
    assert people[1]['region'] == 'india'


def test_brief_round_trips_audience(tmp_path, monkeypatch):
    from app.config import Config
    from app.models.gtm_brief import GTMBriefManager
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    data = {f: 'x' * 25 for f in ['product_name', 'product_description', 'icp', 'pricing_model',
                                  'target_market', 'sales_channel', 'pain_point', 'gtm_goal']}
    data['audience'] = {'mix': {'champion': 70, 'evaluator': 30}, 'regions': ['latam']}
    brief = GTMBriefManager.create_brief(data)
    again = GTMBriefManager.get_brief(brief.brief_id)
    assert again.audience['regions'] == ['latam']
    assert again.audience['mix']['champion'] == 70
