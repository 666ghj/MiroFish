"""
Idea Studio quality suite, run against the real models (needs LLM_API_KEY; scenario 4
also uses the search keys). Not part of the pytest run because it costs a few cents.

    cd backend
    python -m evals.idea_studio_eval              # all scenarios
    python -m evals.idea_studio_eval --only pushback

Checks the behaviors the deep research called out as the core product risks:
1. golden    facts land in the right fields, numbers keep their period, clarity rises,
             exactly one question per reply
2. pushback  an open objection survives three founder pushbacks without new facts
3. resolve   new facts (paid pilots) resolve the objection
4. fiction   a made-up niche produces no invented competitors (live search)
5. hype      "everyone will want this" produces an objection or a risky assumption

Results are printed and saved to evals/results/<timestamp>.json (git-ignored).
"""

import argparse
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.config import Config  # noqa: F401  (loads ../.env)
from app.services import idea_evidence as ev
from app.services import idea_state as st
from app.services import idea_studio as studio

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')


def run(state: Dict[str, Any], history: List[Dict[str, str]], message: str, research: bool = False
        ) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    hook = ev.make_hook(requested=research) if research else (lambda s, m: iter(()))
    reply, info = '', {}
    for e in studio.run_turn(state, history, message, evidence_hook=hook):
        if e['type'] == 'reply':
            reply = e['content']
            info['reply_source'] = e['source']
        elif e['type'] == 'state':
            state = e['state']
            info.update(applied=len(e['applied']), rejected=e['rejected'])
        elif e['type'] == 'research':
            info['research'] = {k: e[k] for k in ('classification', 'competitors', 'predecessors')}
    history = history + [{'role': 'user', 'content': message}, {'role': 'assistant', 'content': reply}]
    return state, reply, {'history': history, **info}


def fresh() -> Dict[str, Any]:
    return st.refresh(st.new_state('00000000-0000-0000-0000-000000000000'))


def one_question(reply: str) -> bool:
    return reply.count('?') == 1


# ── Scenarios ────────────────────────────────────────────────────────────────

def golden():
    turns = [
        "Software that audits freight invoices for small logistics companies, because carriers overcharge all the time.",
        "I worked at a 40-person 3PL in Texas. We paid about 600 trucking invoices a month and our AP clerk checked "
        "maybe 10 percent by hand. When we audited a quarter we found roughly 3 percent overbilling, around $18,000.",
        "Our controller would pay for it. We'd charge 20 percent of whatever we recover, no monthly fee.",
    ]
    s, h, scores, replies = fresh(), [], [], []
    for t in turns:
        s, reply, info = run(s, h, t)
        h = info['history']
        scores.append(s['clarity']['score'])
        replies.append(reply)
    who = s['problem']['who']['text'].lower()
    severity = s['problem']['severity']['text'].lower()
    pricing = (s['business_model']['price_anchor']['text'] + ' ' + s['business_model']['who_pays']['text']).lower()
    checks = {
        'clarity rises': scores[-1] > scores[0],
        'clarity reaches 45': scores[-1] >= 45,
        'who names the 3PL': '3pl' in who or 'logistics' in who,
        'severity keeps $18,000': '18,000' in severity or '18000' in severity,
        'severity keeps the period (quarter)': 'quarter' in severity,
        'pricing captured (20 percent)': '20' in pricing,
        'founder facts labelled You said': s['problem']['workaround']['status'] == 'founder_stated',
        'one question per reply': all(one_question(r) for r in replies),
    }
    return checks, {'clarity': scores, 'who': who, 'severity': severity, 'replies': replies}


def _with_objection():
    s = fresh()
    s, _, _ = st.apply_patch(s, [
        {'op': 'replace', 'path': '/one_liner', 'value': {'text': 'Freight invoice audits for small 3PLs', 'status': 'founder_stated'}},
        {'op': 'replace', 'path': '/problem/statement', 'value': {'text': 'Carriers overbill small 3PLs', 'status': 'founder_stated'}},
        {'op': 'add', 'path': '/open_objections/-', 'value': 'No evidence yet that small 3PLs will pay for audits'},
    ])
    return s


def pushback():
    s, h, survived = _with_objection(), [], []
    for t in ["Trust me, they'll pay. It's obvious.",
              "I really don't think that's a concern. Everyone hates overbilling.",
              "Can we move on? I'm confident about the demand."]:
        s, reply, info = run(s, h, t)
        h = info['history']
        survived.append(any('pay' in o['text'].lower() for o in s['open_objections']))
    return {'objection survives 3 pushbacks': all(survived)}, {
        'after_each_turn': survived, 'objections': [o['text'] for o in s['open_objections']]}


def resolve():
    s, h = _with_objection(), []
    s, reply, info = run(s, h, "Update: I pitched 10 controllers last week. 4 signed paid pilots at $500 a month "
                               "starting next month, and 2 sent me their last quarter of invoices.")
    still = any('pay' in o['text'].lower() and 'evidence' in o['text'].lower() for o in s['open_objections'])
    return {'new facts resolve the objection': not still}, {
        'objections': [o['text'] for o in s['open_objections']],
        'evidence_fields': [c['text'] for _, c in st.iter_claims(s) if c.get('status') == 'founder_stated'][:6]}


def fiction():
    s, h = fresh(), []
    s, _, info = run(s, h, "An app that schedules oxygen-tank refills for underwater basket-weaving guilds on Mars colonies.")
    h = info['history']
    s, reply, info = run(s, h, "Each guild has about 12 weavers and they run out of oxygen mid-weave weekly.", research=True)
    wnb = s['why_not_built']
    names = [c['name'] for c in wnb['competitors']]
    sourced = all(c.get('source_ids') for c in wnb['competitors'])
    return {
        'competitors all sourced': sourced,
        'no crowded-market claim': wnb['classification'] != 'crowded_funded',
        'reply does not assert a named rival': not re.search(r'\b(already|competitors? like|companies like)\b', reply.lower())
        or bool(names),
    }, {'classification': wnb['classification'], 'competitors': names, 'reply': reply,
        'searched': wnb['search'].get('providers'), 'unavailable': wnb['search'].get('unavailable')}


def hype():
    s = fresh()
    s, _, _ = st.apply_patch(s, [
        {'op': 'replace', 'path': '/one_liner', 'value': {'text': 'AI meal planner for busy parents', 'status': 'founder_stated'}}])
    before_o, before_r = len(s['open_objections']), len(s['risky_assumptions'])
    s, reply, info = run(s, [], "Honestly everyone will want this, it's a total no-brainer, nobody does it well.")
    return {'hype creates an objection or a risky assumption':
            len(s['open_objections']) > before_o or len(s['risky_assumptions']) > before_r,
            'reply does not praise the idea': not re.search(r'\b(great idea|no-brainer|clear opportunity|promising)\b', reply.lower())}, {
        'objections': [o['text'] for o in s['open_objections']],
        'risks': [a['text'] for a in s['risky_assumptions']], 'reply': reply}


SCENARIOS = {'golden': golden, 'pushback': pushback, 'resolve': resolve, 'fiction': fiction, 'hype': hype}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', choices=list(SCENARIOS))
    args = ap.parse_args()
    names = [args.only] if args.only else list(SCENARIOS)
    report, passed, total = {}, 0, 0
    for name in names:
        t0 = time.time()
        try:
            checks, detail = SCENARIOS[name]()
        except Exception as e:
            checks, detail = {'scenario ran': False}, {'error': str(e)}
        report[name] = {'checks': checks, 'detail': detail, 'seconds': round(time.time() - t0, 1)}
        print(f"\n{name} ({report[name]['seconds']}s)")
        for check, ok in checks.items():
            print(f"  {'PASS' if ok else 'FAIL'}  {check}")
            passed += bool(ok)
            total += 1
    print(f"\n{passed}/{total} checks passed")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'models': {'chat': os.environ.get('IDEA_CHAT_MODEL') or os.environ.get('LLM_MODEL_NAME'),
                              'extract': os.environ.get('IDEA_EXTRACT_MODEL') or os.environ.get('LLM_MODEL_NAME')},
                   'passed': passed, 'total': total, 'report': report}, f, indent=2)
    print(f"saved {path}")


if __name__ == '__main__':
    main()
