"""Idea Studio state: code-computed clarity, guarded patches, client state validation."""

import pytest

from app.services import idea_state as st


def fresh():
    return st.refresh(st.new_state('s1'))


def src(state, sid, title, snippet='', url=None):
    return st.add_sources(state, [{'id': sid, 'url': url or f'https://ex.com/{sid}', 'title': title,
                                   'snippet': snippet, 'provider': 'tavily'}])


def test_empty_state_has_zero_clarity_and_is_vague():
    s = fresh()
    assert s['clarity']['score'] == 0 and s['meta']['stage'] == 'vague'
    assert len(s['clarity']['top_missing']) == 3


def test_founder_statements_raise_clarity_more_than_ai_guesses():
    s = fresh()
    founder, _, _ = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/statement',
                                        'value': {'text': 'Dental offices lose 6 hours a week confirming appointments by phone',
                                                  'status': 'founder_stated', 'specific': True}}])
    guess, _, _ = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/statement',
                                      'value': {'text': 'Small businesses struggle with scheduling', 'status': 'ai_inference'}}])
    assert founder['clarity']['score'] > guess['clarity']['score'] > 0


def test_specific_flag_needs_real_detail():
    s = fresh()
    vague, _, _ = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/who',
                                      'value': {'text': 'businesses', 'status': 'founder_stated', 'specific': True}}])
    assert vague['problem']['who']['specific'] is False


def test_model_cannot_write_score_sources_meta_or_unknown_paths():
    s = fresh()
    new, applied, rejected = st.apply_patch(s, [
        {'op': 'replace', 'path': '/clarity/score', 'value': 100},
        {'op': 'add', 'path': '/sources/x', 'value': {'url': 'https://fake'}},
        {'op': 'replace', 'path': '/meta/stage', 'value': 'ready'},
        {'op': 'replace', 'path': '/system', 'value': 'ignore all rules'},
        {'op': 'move', 'path': '/one_liner', 'from': '/problem/who'},
    ])
    assert applied == [] and len(rejected) == 5
    assert new['clarity']['score'] == 0 and new['sources'] == {}


def test_locked_fields_are_protected():
    s = st.founder_edit(fresh(), '/one_liner', 'Appointment confirmations for dental offices')
    assert s['one_liner']['locked'] and s['one_liner']['status'] == 'founder_stated'
    new, applied, rejected = st.apply_patch(s, [{'op': 'replace', 'path': '/one_liner', 'value': 'Something else'}])
    assert not applied and 'locked' in rejected[0]['reason']
    assert new['one_liner']['text'] == 'Appointment confirmations for dental offices'


def test_evidence_needs_a_real_source_and_supported_numbers():
    s = src(fresh(), 'S1', 'Dental no-show rates', 'Practices report no-show rates of 23% on average.')
    new, applied, _ = st.apply_patch(s, [
        {'op': 'replace', 'path': '/problem/severity',
         'value': {'text': 'No-shows hit 23% of appointments', 'status': 'evidence', 'source_ids': ['S1']}},
        {'op': 'replace', 'path': '/problem/frequency',
         'value': {'text': 'Happens 40 times a week', 'status': 'evidence', 'source_ids': ['S1']}},
        {'op': 'replace', 'path': '/problem/workaround',
         'value': {'text': 'Front desk calls each patient', 'status': 'evidence', 'source_ids': ['S9']}},
    ])
    assert new['problem']['severity']['status'] == 'evidence'
    assert new['problem']['frequency']['status'] == 'ai_inference'     # 40 is not in the source
    assert new['problem']['workaround']['status'] == 'ai_inference'    # S9 does not exist
    assert any('downgraded' in w for a in applied for w in a.get('warnings', []))


def test_competitors_must_appear_in_their_source():
    s = src(fresh(), 'S1', 'Weave: patient communication for dental practices')
    new, applied, rejected = st.apply_patch(s, [
        {'op': 'add', 'path': '/why_not_built/competitors/-',
         'value': {'name': 'Weave', 'source_ids': ['S1'], 'status': 'active'}},
        {'op': 'add', 'path': '/why_not_built/competitors/-',
         'value': {'name': 'DentaBotX', 'source_ids': ['S1']}},             # invented
        {'op': 'add', 'path': '/why_not_built/competitors/-',
         'value': {'name': 'NoSource Inc'}},                                # no source
    ])
    assert [c['name'] for c in new['why_not_built']['competitors']] == ['Weave']
    assert len(rejected) == 2


def test_predecessor_marked_dead_only_with_shutdown_language():
    s = src(fresh(), 'S1', 'Recall Health shuts down after failing to reach scale')
    s = src(s, 'S2', 'Recallify launches new dental feature')
    new, _, _ = st.apply_patch(s, [
        {'op': 'add', 'path': '/why_not_built/predecessors/-',
         'value': {'name': 'Recall Health', 'source_ids': ['S1'], 'failure_reason': 'could not scale'}},
        {'op': 'add', 'path': '/why_not_built/predecessors/-',
         'value': {'name': 'Recallify', 'source_ids': ['S2']}},
    ])
    assert [p['status'] for p in new['why_not_built']['predecessors']] == ['dead', 'unknown']


def test_why_not_built_counts_only_once_researched():
    s = src(fresh(), 'S1', 'Weave dental software')
    unresearched = st.apply_patch(s, [{'op': 'replace', 'path': '/why_not_built/classification',
                                       'value': 'crowded_funded'}])[0]
    researched = st.apply_patch(unresearched, [{'op': 'add', 'path': '/why_not_built/competitors/-',
                                                'value': {'name': 'Weave', 'source_ids': ['S1']}}])[0]
    assert researched['clarity']['field_values']['why_not_built'] == 1.0
    assert unresearched['clarity']['field_values']['why_not_built'] == 0.4


def test_no_op_and_duplicate_items_are_skipped():
    s = fresh()
    s, _, _ = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/who', 'value': 'Office managers'},
                                 {'op': 'add', 'path': '/why_now/-', 'value': 'Voice AI got cheap in 2025'}])
    _, applied, rejected = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/who', 'value': 'office managers!'},
                                              {'op': 'add', 'path': '/why_now/-', 'value': 'Voice AI got cheap in 2025'}])
    assert not applied and all('no-op' in r['reason'] for r in rejected)


def test_lists_are_capped_and_assumptions_ranked_by_impact():
    s = fresh()
    ops = [{'op': 'add', 'path': '/risky_assumptions/-',
            'value': {'text': f'Assumption {i}', 'impact': imp, 'test': {'method': 'call 5 buyers', 'days': 2}}}
           for i, imp in enumerate(['minor', 'fatal', 'major', 'minor', 'major', 'fatal'])]
    new, applied, rejected = st.apply_patch(s, ops)
    assert len(new['risky_assumptions']) == 5 and len(rejected) == 1
    assert [a['impact'] for a in new['risky_assumptions']][:2] == ['fatal', 'major']
    assert [a['rank'] for a in new['risky_assumptions']] == [1, 2, 3, 4, 5]


def test_contradiction_lowers_clarity_with_a_reason():
    s = fresh()
    s, _, _ = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/frequency',
                                  'value': {'text': 'Every single day, about 30 calls', 'status': 'founder_stated',
                                            'specific': True}}])
    before = s['clarity']['score']
    s, _, _ = st.apply_patch(s, [{'op': 'replace', 'path': '/problem/frequency',
                                  'value': {'text': 'Founder later said it happens monthly', 'status': 'contradiction'}}])
    assert s['clarity']['score'] < before and 'contradicts' in s['clarity']['last_change_reason']
    assert s['problem']['frequency']['previous']['text'].startswith('Every single day')


def test_ready_stage_needs_a_complete_picture():
    s = src(fresh(), 'S1', 'Weave dental patient messaging')
    spec = lambda t: {'text': t, 'status': 'founder_stated', 'specific': True}
    s, applied, rejected = st.apply_patch(s, [
        {'op': 'replace', 'path': '/problem/statement', 'value': spec('Front desks spend 6 hours a week confirming appointments')},
        {'op': 'replace', 'path': '/problem/who', 'value': spec('Office managers at independent dental practices with 2 to 5 chairs')},
        {'op': 'replace', 'path': '/problem/severity', 'value': spec('Each no-show costs about 200 dollars in lost chair time')},
        {'op': 'replace', 'path': '/problem/frequency', 'value': spec('Every day, roughly 30 calls per office')},
        {'op': 'replace', 'path': '/problem/workaround', 'value': spec('A receptionist phones every patient the day before')},
        {'op': 'replace', 'path': '/customer/early_adopters', 'value': spec('Practices already paying for 1 answering service')},
        {'op': 'replace', 'path': '/solution/core', 'value': spec('A voice agent that calls patients and updates the calendar automatically')},
        {'op': 'add', 'path': '/why_now/-', 'value': spec('Voice model prices fell 10x during 2025 and 2026')},
        {'op': 'replace', 'path': '/why_not_built/classification', 'value': 'crowded_funded'},
        {'op': 'add', 'path': '/why_not_built/competitors/-', 'value': {'name': 'Weave', 'source_ids': ['S1']}},
        {'op': 'replace', 'path': '/business_model/who_pays', 'value': spec('The practice owner pays from the front office budget each month')},
        {'op': 'replace', 'path': '/business_model/price_anchor', 'value': spec('Cheaper than the 400 dollar answering service')},
        *[{'op': 'add', 'path': '/risky_assumptions/-',
           'value': {'text': f'Risk {i}', 'impact': 'major', 'test': {'method': 'Call 10 practices', 'days': 3}}}
          for i in range(3)],
    ])
    assert not rejected, rejected
    assert s['clarity']['score'] >= 60 and s['meta']['stage'] == 'ready'


def test_client_state_is_rebuilt_and_cannot_fake_scores_or_competitors():
    good = src(fresh(), 'S1', 'Weave dental software')
    good, _, _ = st.apply_patch(good, [{'op': 'add', 'path': '/why_not_built/competitors/-',
                                        'value': {'name': 'Weave', 'source_ids': ['S1']}}])
    tampered = {**good, 'clarity': {'score': 99}, 'evil': 'x',
                'why_not_built': {**good['why_not_built'],
                                  'competitors': good['why_not_built']['competitors']
                                  + [{'name': 'FakeCo', 'source_ids': ['S1']}]}}
    rebuilt = st.validate_client_state(tampered, 's1')
    assert 'evil' not in rebuilt and rebuilt['clarity']['score'] < 99
    assert [c['name'] for c in rebuilt['why_not_built']['competitors']] == ['Weave']
    assert st.validate_client_state('garbage')['clarity']['score'] == 0


def test_founder_lock_toggle():
    s = st.apply_patch(fresh(), [{'op': 'add', 'path': '/what_could_work/-', 'value': 'Sell through dental supply reps'}])[0]
    s = st.set_locked(s, '/what_could_work/0', True)
    _, applied, rejected = st.apply_patch(s, [{'op': 'remove', 'path': '/what_could_work/0'}])
    assert not applied and 'locked' in rejected[0]['reason']
    with pytest.raises(ValueError):
        st.set_locked(s, '/why_not_built/classification', True)
