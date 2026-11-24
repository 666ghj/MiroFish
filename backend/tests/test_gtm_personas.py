"""Batched persona generation: exact sizes, role mix per batch, retries, honest labelling."""

import re
import threading
from types import SimpleNamespace

import pytest

from app.services import gtm_persona_generator as pg
from app.services.gtm_audience import normalize_audience


def make_persona(i, batch_tag):
    return {
        'id': f'p_{batch_tag}_{i}', 'name': f'Person {batch_tag}-{i}', 'title': 'VP Sales',
        'company_type': 'SaaS', 'company_stage': 'Series A', 'persona_type': 'vp_sales',
        'primary_goal': 'g', 'pain_points': ['a'], 'buying_triggers': ['b'], 'objections': ['c'],
        'communication_style': 's', 'budget_sensitivity': 'medium', 'risk_tolerance': 'low',
        'preferred_channels': ['linkedin'], 'likely_message_angle': 'roi_led', 'summary': 's',
        'reaction': 'neutral', 'skepticism_level': 3, 'likely_response': 'r', 'objection_category': None,
        'archetype_mix': {'decision_maker': 20, 'champion': 70, 'evaluator': 10},
    }


class FakeLLM:
    """Returns the requested number of personas. `fail_batches` always fail."""

    def __init__(self, fail_batches=(), flaky_batches=()):
        self.fail_batches = set(fail_batches)
        self.flaky = set(flaky_batches)       # fail on first attempt only
        self.prompts = []
        self.lock = threading.Lock()

    def chat_json(self, messages, **kw):
        user = messages[1]['content']
        n = int(re.search(r'Generate exactly (\d+) distinct', user).group(1))
        m = re.search(r'This is batch (\d+) of', user)
        b = int(m.group(1)) if m else 1
        with self.lock:
            self.prompts.append(user)
            if b in self.flaky:
                self.flaky.discard(b)
                raise RuntimeError('transient')
        if b in self.fail_batches:
            raise RuntimeError('boom')
        return [make_persona(i, b) for i in range(n)]


def brief(audience=None):
    return SimpleNamespace(
        product_name='Acme', product_description='d', icp='i', pricing_model='p', target_market='t',
        sales_channel='s', pain_point='pp', gtm_goal='g', competitors=[], company_stage=None,
        team_size=None, existing_problems=None, audience=audience,
    )


def generator(llm):
    g = pg.GTMPersonaGenerator()
    g._llm = llm
    return g


@pytest.fixture(autouse=True)
def _no_mock_mode(monkeypatch):
    monkeypatch.delenv('MOCK_MODE', raising=False)


def test_plan_batches_matches_mix_and_regions_exactly():
    aud = normalize_audience({'mix': {'decision_maker': 20, 'champion': 50, 'evaluator': 30},
                              'regions': ['dach', 'india', 'anz']})
    plan = pg.plan_batches(aud, 47)
    assert [b['size'] for b in plan] == [10, 10, 9, 9, 9]
    totals = [sum(b['role_counts'][i] for b in plan) for i in range(3)]
    assert totals == [9, 24, 14]                      # 20/50/30 of 47, largest remainder
    assert all(sum(b['role_counts']) == b['size'] for b in plan)
    assert {r for b in plan for r in b['regions']} == {'dach', 'india', 'anz'}
    assert len({b['persona_types'][0] for b in plan}) > 1   # batches lead with different types


def test_large_audience_is_generated_in_batches_without_padding():
    llm = FakeLLM()
    out = generator(llm).generate_detailed(brief(), 50)
    assert out['meta'] == {'source': 'llm', 'mock_reason': None, 'requested': 50,
                           'generated': 50, 'batches': 5, 'batches_failed': 0}
    assert len(llm.prompts) == 5
    assert len({p['id'] for p in out['personas']}) == 50
    assert all(sum(p['archetype_mix'].values()) == 100 for p in out['personas'])


def test_failed_batch_is_reported_not_padded():
    out = generator(FakeLLM(fail_batches={2})).generate_detailed(brief(), 50)
    meta = out['meta']
    assert meta['source'] == 'llm' and meta['generated'] == 40 and meta['batches_failed'] == 1
    assert all(p['id'].startswith('p_') for p in out['personas'])   # no sample personas mixed in


def test_flaky_batch_is_retried():
    out = generator(FakeLLM(flaky_batches={1})).generate_detailed(brief(), 20)
    assert out['meta']['generated'] == 20 and out['meta']['batches_failed'] == 0


def test_too_few_personas_falls_back_to_labelled_sample():
    out = generator(FakeLLM(fail_batches={1, 2, 3})).generate_detailed(brief(), 30)
    assert out['meta']['source'] == 'mock'
    assert 'Only 0 of 30' in out['meta']['mock_reason']


def test_mock_mode_is_labelled(monkeypatch):
    monkeypatch.setenv('MOCK_MODE', 'true')
    llm = FakeLLM()
    out = generator(llm).generate_detailed(brief(), 12)
    assert out['meta']['source'] == 'mock' and llm.prompts == []


def test_batch_prompt_carries_its_share_of_the_audience():
    aud = normalize_audience({'mix': {'decision_maker': 0, 'champion': 100, 'evaluator': 0},
                              'regions': ['nordics'], 'live_market': False})
    llm = FakeLLM()
    generator(llm).generate_detailed(brief(aud), 20)
    assert len(llm.prompts) == 2
    for p in llm.prompts:
        assert 'about 10 champions' in p and 'Nordics' in p and 'batch' in p


def test_api_returns_and_caches_meta(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.models.gtm_brief import GTMBriefManager
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(tmp_path))
    monkeypatch.setattr(pg.GTMPersonaGenerator, '_get_llm', lambda self: FakeLLM())
    data = {f: 'x' * 25 for f in ['product_name', 'product_description', 'icp', 'pricing_model',
                                  'target_market', 'sales_channel', 'pain_point', 'gtm_goal']}
    b = GTMBriefManager.create_brief({**data, 'num_personas': 25})
    client = create_app().test_client()
    first = client.post(f'/api/gtm/personas/{b.brief_id}', json={'count': 25}).get_json()
    assert len(first['data']) == 25 and first['meta']['batches'] == 3 and first['cached'] is False
    again = client.get(f'/api/gtm/personas/{b.brief_id}').get_json()
    assert again['cached'] is True and again['meta']['generated'] == 25
