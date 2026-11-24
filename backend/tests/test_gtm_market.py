"""Market intelligence: static profiles, computed timing, and live sources (stubbed, no network)."""

import json
from datetime import datetime, timezone

import pytest

from app.services import gtm_market as gm


@pytest.fixture(autouse=True)
def _clear_cache():
    gm._cache.clear()
    yield
    gm._cache.clear()


def test_every_region_profile_is_complete():
    for rid, prof in gm.REGION_MARKETS.items():
        assert prof['countries'] and prof['fiscal_years'] and prof['channels'], rid
        for c in prof['countries']:
            assert c['rule'] in gm.RULE_LABELS and c['confidence'] in ('settled', 'contested')
            assert '—' not in c['note']


def test_static_intel_without_network():
    now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
    r = gm.region_intel('dach', live=False, now_utc=now)
    assert r['outreach']['rule'] == 'opt_in'
    de = next(c for c in r['countries'] if c['code'] == 'DE')
    assert de['local']['time'] == '11:00' and de['local']['open'] is True
    assert r['fiscal_years'][0]['days_left'] == 37
    assert any('fiscal year ends in 37 days' in t for t in r['timing'])


def test_mixed_region_reports_strictest_rule():
    r = gm.region_intel('north_america', live=False)
    assert r['outreach']['rule'] == 'opt_in'          # Canada (CASL) is stricter than the US
    assert r['outreach']['label'].startswith('Mixed')


def test_saudi_weekend_is_friday_saturday():
    friday_noon = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)   # 12:00 in Riyadh
    r = gm.region_intel('middle_east', live=False, now_utc=friday_noon)
    status = {c['code']: c['local']['open'] for c in r['countries']}
    assert status == {'AE': True, 'SA': False}


def test_ramadan_window_appears_ahead_of_time():
    jan = datetime(2027, 1, 5, 9, 0, tzinfo=timezone.utc)
    r = gm.region_intel('middle_east', live=False, now_utc=jan)
    assert any('Ramadan' in t for t in r['timing'])


def test_live_sources_are_parsed_and_merged(monkeypatch):
    wb = {'FP.CPI.TOTL.ZG': [{'country': {'id': 'DE'}, 'date': '2025', 'value': 2.234}]}
    holidays = [{'date': '2026-12-25', 'name': 'Christmas Day', 'global': True}]
    rss = ('<rss><channel><item><title>German economy steadies - Reuters</title><source>Reuters</source>'
           '<link>https://x</link><pubDate>Mon, 23 Nov 2026</pubDate></item>'
           '<item><title>Germany - Britannica</title><source>Britannica</source></item></channel></rss>')

    def fake_get(url, timeout=None):
        if 'worldbank' in url:
            code = next((k for k in wb if k in url), None)
            return json.dumps([{}, wb.get(code, [])]).encode()
        if 'nager' in url:
            return json.dumps(holidays).encode()
        if 'news.google' in url:
            return rss.encode()
        return None

    monkeypatch.setattr(gm, '_get', fake_get)
    now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
    r = gm.region_intel('dach', live=True, now_utc=now)
    de = next(c for c in r['countries'] if c['code'] == 'DE')
    assert de['indicators']['inflation'] == {'value': 2.2, 'year': '2025'}
    assert r['holidays'][0] == {'date': '2026-12-25', 'name': 'Christmas Day', 'country': 'DE, AT, CH'}
    assert [h['title'] for h in r['headlines']] == ['German economy steadies']   # source suffix + Britannica dropped
    text = gm.market_prompt({'regions': [r], 'generated_at': now.isoformat()})
    assert 'prior consent required' in text and 'inflation 2.2% (2025)' in text


def test_sources_failing_never_break_intel(monkeypatch):
    monkeypatch.setattr(gm, '_get', lambda url, timeout=None: None)
    data = gm.market_intel(['india', 'nope'])
    assert [r['id'] for r in data['regions']] == ['india']
    assert data['regions'][0]['headlines'] == [] and data['disclaimer']


def test_market_endpoint(monkeypatch):
    monkeypatch.setattr(gm, '_get', lambda url, timeout=None: None)
    from app import create_app
    client = create_app().test_client()
    assert client.get('/api/gtm/market').status_code == 400
    res = client.get('/api/gtm/market?regions=anz,east_asia&live=0').get_json()
    assert res['success'] and [r['id'] for r in res['data']['regions']] == ['anz', 'east_asia']


def test_new_audience_parameters():
    from app.services.gtm_audience import normalize_audience, audience_prompt
    a = normalize_audience({'industries': ['fintech', 'spaceships'], 'current_solutions': ['competitor'],
                            'traits': {'tech_maturity': 5}, 'live_market': False})
    assert a['industries'] == ['fintech'] and a['current_solutions'] == ['competitor']
    assert a['live_market'] is False
    text = audience_prompt(a, 12)
    assert 'Fintech' in text and 'established competitor' in text and 'Tech maturity: very high' in text
