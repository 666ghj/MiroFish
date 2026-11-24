"""Idea Studio input handling: park/unpark, idea updates, research in words, idk, staying on the question."""

from app.services import idea_input as inp
from app.services import idea_state as st
from app.services import idea_studio as studio


class FakeJSON:
    def __init__(self, result):
        self.result, self.messages = result, None

    def chat_json(self, messages, **kw):
        self.messages = messages
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeChat:
    def __init__(self, text):
        self.text, self.messages = text, None

    def chat_stream(self, messages, **kw):
        self.messages = messages
        yield self.text


def base():
    s = st.new_state('t')
    s['one_liner'] = {**s['one_liner'], 'text': 'An AI idea generation app for creatives', 'status': 'founder_stated'}
    s['solution']['core'] = {**s['solution']['core'], 'text': 'AI that suggests ideas', 'status': 'founder_stated'}
    return st.refresh(s)


HISTORY = [{'role': 'assistant', 'content': 'Got it.\n\n**What features would help users cut AI use gradually?**'}]


# ── Reading ──────────────────────────────────────────────────────────────────

def test_rules_catch_park_with_priority_and_resolve_the_topic():
    r = inp.read_by_rules('mark that as pending and top priority', HISTORY)
    assert r['kinds'] == ['park']
    assert r['park'][0] == {'topic': 'What features would help users cut AI use gradually', 'priority': 'top', 'field': ''}
    assert inp.read_by_rules("I'm thinking about it, mark this as pending", HISTORY)['park'][0]['priority'] == 'normal'


def test_rules_catch_research_and_idk():
    assert 'research' in inp.read_by_rules('Look up who already does this and who has tried it before.', [])['kinds']
    assert 'research' in inp.read_by_rules('any competitors?', [])['kinds']
    assert inp.read_by_rules('idk honestly', [])['kinds'] == ['dont_know']
    assert inp.read_by_rules('Dentists lose 5 hours a week', [])['kinds'] == ['answer']


def test_model_reading_is_normalized_and_keyword_hits_are_kept():
    s = base()
    raw = {'kinds': ['answer', 'bogus'], 'park': [{'topic': 'this'}],
           'idea_update': {'one_liner': 'Helps people use AI without losing their own thinking'}}
    r = inp.read_input(s, HISTORY, 'mark that as pending', FakeJSON(raw))
    assert 'bogus' not in r['kinds'] and 'park' in r['kinds'] and 'idea_update' in r['kinds']
    assert r['park'][0]['topic'].startswith('What features')          # vague "this" replaced by the rules topic
    # model failure falls back to rules
    assert inp.read_input(s, HISTORY, 'park that', FakeJSON(RuntimeError('down')))['source'] == 'rules'


# ── Acting ───────────────────────────────────────────────────────────────────

def test_parking_saves_dedupes_upgrades_priority_and_unparks():
    s = base()
    s, acts = inp.apply_reading(s, {'kinds': ['park'], 'park': [{'topic': 'Cross-app control', 'priority': 'normal', 'field': ''}]})
    assert acts == [{'kind': 'parked', 'text': 'Cross-app control', 'priority': 'normal'}]
    s, acts = inp.apply_reading(s, {'kinds': ['park'], 'park': [{'topic': 'cross-app control', 'priority': 'top', 'field': ''}]})
    assert acts[0]['kind'] == 'already_parked' and len(s['parked']) == 1 and s['parked'][0]['priority'] == 'top'
    pid = s['parked'][0]['id']
    s, acts = inp.apply_reading(s, {'kinds': ['unpark'], 'unpark': [pid]})
    assert s['parked'] == [] and acts == [{'kind': 'unparked', 'text': 'Cross-app control'}]


def test_idea_update_rewrites_core_fields_but_respects_locks():
    s = base()
    s['solution']['core']['locked'] = True
    s, acts = inp.apply_reading(s, {'kinds': ['idea_update'], 'idea_update': {
        'one_liner': 'Helps people use AI without losing their own thinking', 'solution': 'A coach that limits AI use'}})
    assert s['one_liner']['text'] == 'Helps people use AI without losing their own thinking'
    assert s['solution']['core']['text'] == 'AI that suggests ideas'        # locked: untouched
    assert acts == [{'kind': 'idea_updated', 'text': 'one-liner', 'paths': ['/one_liner']}]


def test_parked_list_survives_the_browser_and_is_sanitized():
    s = base()
    st.park(s, 'Pricing', 'top', 'business_model')
    raw = dict(s)
    raw['parked'] = s['parked'] + [{'text': '<b>x</b>' * 50, 'priority': 'mega', 'field': '/etc', 'id': 'DROP TABLE'}, 'junk']
    back = st.validate_client_state(raw)
    assert back['parked'][0]['text'] == 'Pricing' and back['parked'][0]['priority'] == 'top'
    assert back['parked'][1]['priority'] == 'normal' and back['parked'][1]['field'] == '' and back['parked'][1]['id'] == 'p2'
    assert len(back['parked']) == 2


def test_router_skips_parked_fields():
    s = base()
    first = studio.pick_next_questions(s)[0]['field']
    st.park(s, 'That topic', 'normal', first)
    assert first not in [q['field'] for q in studio.pick_next_questions(s)]


# ── Guidance and staying on track ────────────────────────────────────────────

def test_guidance_names_research_findings_and_parks():
    g = inp.guidance({'kinds': ['research', 'park']},
                     [{'kind': 'parked', 'text': 'Cross-app control', 'priority': 'top'}],
                     {'ran': True, 'competitors': ['Acme', 'Beta'], 'predecessors': ['Gone Inc']})
    assert '"Cross-app control" (top priority)' in g and 'IS saved' in g
    assert 'Acme, Beta' in g and 'Gone Inc' in g and 'unrelated' in g
    assert 'did not run' in inp.guidance({'kinds': ['research']}, [], {'skipped': 'Research limit reached (3 per idea).'})
    assert 'Do not answer it for them' in inp.guidance({'kinds': ['dont_know']}, [], None)
    assert inp.guidance({'kinds': ['answer']}, [], None) == ''


def test_keep_on_track_restores_the_router_question_only_on_drift():
    d = {'field': 'problem.severity', 'question': 'If they do nothing for six months, what breaks?',
         'reason': 'how painful it is', 'enforce': True}
    ok = 'Makes sense.\n\n**What did it cost them the last time?**'
    assert inp.keep_on_track(ok, d, {'kinds': ['answer']}) == (ok, False)            # rephrase on the same topic
    drift = 'Interesting.\n\n**What insights from health apps could inform your approach?**'
    fixed, changed = inp.keep_on_track(drift, d, {'kinds': ['answer']})
    assert changed and fixed == 'Interesting.\n\n**If they do nothing for six months, what breaks?**'
    assert inp.keep_on_track(drift, d, {'kinds': ['brainstorm_help']})[1] is False     # the founder steered it
    assert inp.keep_on_track(drift, {**d, 'enforce': False}, {'kinds': ['answer']})[1] is False


# ── Whole turn ───────────────────────────────────────────────────────────────

def test_turn_parks_reports_actions_and_tells_the_cofounder():
    reader = FakeJSON({'kinds': ['park'], 'park': [{'topic': 'Cross-app AI controls', 'priority': 'top', 'field': ''}]})
    chat = FakeChat('Saved that under Parked.\n\n**In one sentence, what can someone not do well today that your idea fixes?**')
    ev = list(studio.run_turn(base(), HISTORY, 'mark that as pending, top priority', chat,
                              FakeJSON({'founder_facts': {}}), read_llm=reader))
    acts = next(e for e in ev if e['type'] == 'actions')
    assert acts['items'] == [{'kind': 'parked', 'text': 'Cross-app AI controls', 'priority': 'top'}]
    assert 'PARKED BY THE FOUNDER' in chat.messages[1]['content']
    assert chat.messages[-1]['role'] == 'system' and 'IS saved' in chat.messages[-1]['content']   # right after the message
    reply = next(e for e in ev if e['type'] == 'reply')
    assert reply['actions'][0]['kind'] == 'parked'
    final = next(e for e in ev if e['type'] == 'state')['state']
    assert final['parked'][0]['text'] == 'Cross-app AI controls'


def test_research_asked_in_words_runs_the_search_and_the_reply_must_report_it():
    calls = []

    def hook(state, msg, force=False, recent=""):
        calls.append(force)
        if force:
            yield {'type': 'searching', 'terms': ['x'], 'reason': 'requested'}
            yield {'type': 'research', 'analysis': {}}

    reader = FakeJSON({'kinds': ['research']})
    chat = FakeChat('Here is what I found.\n\n**Why would they pick you?**')
    ev = list(studio.run_turn(base(), [], 'who else is doing this?', chat, FakeJSON({'founder_facts': {}}),
                              evidence_hook=hook, read_llm=reader))
    assert calls == [True]
    assert 'Research just ran' in chat.messages[-1]['content']
    reply = next(e for e in ev if e['type'] == 'reply')
    assert reply['actions'][-1]['kind'] == 'researched'
    assert reply['content'].startswith('I searched for "x".')          # the facts are written by code


def test_research_does_not_apply_a_router_suggested_rewrite():
    seen = {}

    def hook(state, msg, force=False, recent=""):
        seen['one_liner'] = state['one_liner']['text']
        return iter([])

    reader = FakeJSON({'kinds': ['idea_update', 'research'],
                       'idea_update': {'one_liner': 'Helps people use AI without losing their own thinking'}})
    list(studio.run_turn(base(), [], 'look it up', FakeChat('Ok. **Who?**'), FakeJSON({'founder_facts': {}}),
                         evidence_hook=hook, read_llm=reader))
    assert seen['one_liner'] == base()['one_liner']['text']


def test_research_line_is_exact():
    line = inp.research_line({'ran': True, 'terms': ['ai habit tracker'], 'competitors': ['A', 'B', 'C', 'D', 'E'],
                              'predecessors': ['Gone']})
    assert line == 'I searched for "ai habit tracker". Closest: A, B, C, D and 1 more. Tried and shut down: Gone.'
    assert 'does not prove' in inp.research_line({'ran': True, 'terms': ['x'], 'competitors': []})
    assert inp.research_line(None) == '' and inp.research_line({'skipped': 'limit'}) == ''


def test_ground_removes_sentences_with_invented_names_but_keeps_known_ones():
    reply = ('Apps like Quit Genius and Noom focus on behavior change. Your founder notes mention ChatGPT a lot. '
             'That is a real signal.\n\n**Who feels this most?**')
    out, bad = inp.ground(reply, 'founder said: I use ChatGPT and Claude every day')
    assert bad == ['Genius', 'Noom', 'Quit']
    assert 'Noom' not in out and 'ChatGPT a lot' in out and out.endswith('**Who feels this most?**')
    assert inp.ground('Makes sense. Monday is busy.\n\n**Why?**', '') == ('Makes sense. Monday is busy.\n\n**Why?**', [])


def test_park_needs_a_cue_in_this_message():
    s = base()
    raw = {'kinds': ['park', 'idea_update'], 'park': [{'topic': 'Cross-app control', 'priority': 'top'}],
           'record_check': {'one_liner': {'fits': False, 'rewrite': 'An extension that helps people cut AI use'}}}
    r = inp.read_input(s, HISTORY, 'what i actually want to build is an extension', FakeJSON(raw))
    assert r['park'] == [] and 'park' not in r['kinds']
    assert r['idea_update'] == {'one_liner': 'An extension that helps people cut AI use'}     # record_check -> update


def test_headings_and_list_labels_are_not_treated_as_names():
    reply = '1. Customer Focus: look at teachers.\n2. Constraint Flip: reward thinking.\n\n**Which angle?**'
    assert inp.ground(reply, '')[1] == []
    assert inp.plain_markup('**Constraint Flip**: reward it. **Which one?**') == 'Constraint Flip: reward it. **Which one?**'


def test_hint_gets_a_nudge_not_answers():
    assert 'hint' in inp.read_by_rules('I am not sure. Can you give me a hint, without answering it for me?', [])['kinds']
    g = inp.guidance({'kinds': ['dont_know', 'hint', 'ask_ai'], 'question_to_ai': 'give me a hint'}, [], None)
    assert 'ONE short hint' in g and 'Answer it first' not in g
