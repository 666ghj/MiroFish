"""
Idea Studio agent team.

After each conversation turn, a team of specialist agents works on the idea in parallel.
Each agent declares:
  needs  - idea fields that must be filled before it can do useful work (else it waits)
  reads  - state paths whose content it depends on (its fingerprint; it re-runs only when they change)
  stage  - 1 runs on the idea state; 2 also reads stage-1 output (experiments); 3 reads everyone (chief of staff)

Outputs are normalized in code: enums clamped, lengths capped, em dashes stripped, and
arithmetic (market size) computed here rather than by the model. Agents never name real
companies; only the researcher does that, from sources. Customer reactions are synthetic
and labelled so.

Events (one dict each, streamed by POST /api/idea/team):
  {"type": "plan", "agents": [{"id", "status": "queued"|"waiting"|"fresh", "missing": [...]}]}
  {"type": "agent", "id", "status": "running"}
  {"type": "agent", "id", "status": "done", "output": {...}, "fingerprint", "source": "model"|"sample"}
  {"type": "agent", "id", "status": "failed", "error": "..."}
  {"type": "done", "ran": n}
"""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Iterator, List, Optional

from ..utils.logger import get_logger
from ..utils.text_style import strip_em_dashes
from . import idea_state as st

logger = get_logger('mirofish.idea_agents')

MAX_WORKERS = 5

COMMON_RULES = """Rules for every agent on this team:
- Work only from the IDEA STATE you are given. Fields marked ai_inference are guesses, not facts.
- Never name real companies, products, or people. Describe them by type instead ("an incumbent freight-audit firm").
- Never present a guess as a fact. Say "estimate" or "assumption" where it is one.
- Plain, specific English. No hype words. Never use em dashes.
- Return one JSON object exactly in the requested shape. Keep every text field under 30 words unless told otherwise.
- "headline" states your single most useful FINDING as a claim someone could disagree with, under 14 words.
  Not a topic label. Bad: "Key challenges threaten viability". Good: "Carrier disputes could stall every refund for 60 days"."""


# ── Agent definitions ────────────────────────────────────────────────────────

AGENTS: List[Dict[str, Any]] = [
    {
        'id': 'skeptic', 'name': 'Skeptic', 'role': 'Finds the strongest reasons this fails', 'stage': 1,
        'needs': ['/problem/statement', '/solution/core'],
        'reads': ['/problem', '/solution', '/customer', '/business_model', '/why_now', '/why_not_built/classification'],
        'prompt': """You are the Skeptic: a sharp, fair red-teamer. Find the 3 strongest reasons this idea fails.
Prefer specific mechanisms (who refuses, what breaks, what it costs) over generic risks ("competition", "funding").
Return {"headline": str, "risks": [{"title": str (under 8 words), "why": str, "severity": "minor"|"major"|"fatal",
"answer_with": str (the evidence or fact that would defuse it)}]}""",
    },
    {
        'id': 'customers', 'name': 'Customer panel', 'role': 'Three synthetic buyers react to it', 'stage': 1,
        'needs': ['/problem/who', '/solution/core'],
        'reads': ['/problem', '/solution', '/customer', '/business_model'],
        'prompt': """You are the Customer panel. Role-play 3 DIFFERENT people from the target customer described:
one eager early adopter, one busy pragmatist, one skeptic who is happy with today's workaround.
Each reacts honestly to the solution in first person, as they would on a first call.
Return {"headline": str, "panel": [{"persona": str (their job and company, e.g. "AP clerk at a 40-person 3PL"; never a label like "eager adopter"),
"reaction": str (first-person quote, under 35 words), "would_try": "yes"|"maybe"|"no",
"objection": str, "would_pay_if": str}]}""",
    },
    {
        'id': 'market', 'name': 'Market sizer', 'role': 'Rough bottom-up market size', 'stage': 1,
        'needs': ['/problem/who', '/solution/core'],
        'reads': ['/problem/who', '/customer', '/business_model', '/solution/core'],
        'prompt': """You are the Market sizer. Build a rough BOTTOM-UP estimate for the reachable market:
how many paying units exist (companies or people matching the target customer, in the stated geography or the US if none),
times a realistic yearly price per unit (use the founder's price if stated; otherwise estimate and say so).
Do not compute the product; just give the two numbers and their basis. Give integers, not ranges.
Return {"headline": str, "unit": str (what one paying unit is, under 8 words),
"count": int, "count_basis": str, "price_per_year": int (USD), "price_basis": str,
"confidence": "low"|"medium", "assumptions": [str] (2 to 3), "bigger_market": str (the adjacent market if this one works)}""",
    },
    {
        'id': 'pitch', 'name': 'Pitch writer', 'role': 'Sharpens how you say it', 'stage': 1,
        'needs': ['/problem/statement', '/problem/who', '/solution/core'],
        'reads': ['/one_liner', '/problem', '/solution', '/why_now'],
        'prompt': """You are the Pitch writer. Make the idea easy to say out loud.
Write 3 different one-liners (customer + pain + outcome, under 16 words each, no buzzwords),
a 30-second spoken pitch (under 70 words) for the target customer, and one phrase to stop using.
Return {"headline": str, "one_liners": [str, str, str], "elevator": str, "avoid": str}""",
    },
    {
        'id': 'gtm', 'name': 'GTM strategist', 'role': 'How to land the first 10 customers', 'stage': 1,
        'needs': ['/problem/who', '/solution/core'],
        'reads': ['/problem/who', '/customer', '/solution', '/business_model'],
        'prompt': """You are the GTM strategist. Plan how a solo founder lands the first 10 paying customers by hand.
Pick ONE channel that fits where these customers already are, and say why.
Return {"headline": str, "channel": str (under 8 words), "why_channel": str,
"message_angle": str (the hook for a first message), "first_10": [str] (3 to 4 concrete steps),
"week_one": [str] (3 to 4 things to do in the next 7 days)}""",
    },
    {
        'id': 'experiments', 'name': 'Experiment designer', 'role': 'Cheapest tests for the riskiest bets', 'stage': 2,
        'needs': ['/problem/statement', '/solution/core'],
        'reads': ['/risky_assumptions', '/problem', '/solution'], 'uses': ['skeptic'],
        'prompt': """You are the Experiment designer. Using the riskiest assumptions in the IDEA STATE and the Skeptic's
findings, design the 3 cheapest experiments that could prove the idea WRONG fast. No building the product.
Each needs a pass threshold decided in advance.
Return {"headline": str, "tests": [{"assumption": str, "method": str, "cost": str (e.g. "$0", "$50"),
"days": int, "pass_if": str}]}""",
    },
    {
        'id': 'chief', 'name': 'Chief of staff', 'role': 'Weighs the team and calls the next move', 'stage': 3,
        'needs': ['/problem/statement', '/solution/core'],
        'reads': ['/problem', '/solution'], 'uses': ['skeptic', 'customers', 'market', 'pitch', 'gtm', 'experiments'],
        'min_inputs': 3,
        'prompt': """You are the Chief of staff. Read the whole team's findings and decide the founder's next move.
Be decisive and fair. Name where the team disagrees.
verdict: "keep_going" (signals hold up), "narrow" (promising but the customer or scope is too broad), or "rethink" (a likely fatal flaw).
Return {"headline": str, "verdict": "keep_going"|"narrow"|"rethink", "why": str (under 40 words),
"next_actions": [str] (exactly 3, ordered, each doable this week), "disagreement": str}""",
    },
]
AGENT_IDS = [a['id'] for a in AGENTS]
BY_ID = {a['id']: a for a in AGENTS}


# ── Readiness and fingerprints ───────────────────────────────────────────────

def _filled(state: Dict[str, Any], path: str) -> bool:
    try:
        node = st._get(state, path)
    except Exception:
        return False
    if isinstance(node, dict):
        return bool((node.get('text') or '').strip())
    return bool(node)


FIELD_LABELS = {
    '/problem/statement': 'the problem', '/problem/who': 'who has it', '/solution/core': 'the solution',
}


def missing_for(agent: Dict[str, Any], state: Dict[str, Any]) -> List[str]:
    return [FIELD_LABELS.get(p, p.strip('/').replace('/', ' ')) for p in agent['needs'] if not _filled(state, p)]


def _slice(state: Dict[str, Any], prefix: str) -> Any:
    """The content an agent reads under a path, without volatile metadata."""
    try:
        node = st._get(state, prefix)
    except Exception:
        return None

    def clean(x):
        if isinstance(x, dict):
            if 'text' in x and 'status' in x:      # a claim: only its text and status matter
                return [x.get('text', ''), x.get('status')]
            return {k: clean(v) for k, v in sorted(x.items()) if k not in ('history', 'turn', 'updated_turn', 'source_ids')}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x
    return clean(node)


def fingerprint(agent: Dict[str, Any], state: Dict[str, Any], prior: Dict[str, Any]) -> str:
    payload = {p: _slice(state, p) for p in agent['reads']}
    payload['_uses'] = {u: (prior.get(u) or {}).get('fingerprint') for u in agent.get('uses', [])}
    payload['_v'] = 1
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── Output normalization ─────────────────────────────────────────────────────

def _s(v: Any, limit: int = 220) -> str:
    return strip_em_dashes(str(v or '')).strip()[:limit]


def _enum(v: Any, allowed: List[str], default: str) -> str:
    v = str(v or '').strip().lower().replace(' ', '_')
    return v if v in allowed else default


def _int(v: Any) -> int:
    try:
        return max(0, int(float(str(v).replace(',', '').replace('$', ''))))
    except (TypeError, ValueError):
        return 0


def _strs(v: Any, n: int, limit: int = 220) -> List[str]:
    return [s for s in (_s(x, limit) for x in (v if isinstance(v, list) else [])) if s][:n]


def _items(v: Any, n: int) -> List[Dict[str, Any]]:
    return [x for x in (v if isinstance(v, list) else []) if isinstance(x, dict)][:n]


def normalize(agent_id: str, raw: Any) -> Dict[str, Any]:
    r = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {'headline': _s(r.get('headline'), 120)}
    if agent_id == 'skeptic':
        out['risks'] = [{'title': _s(x.get('title'), 80), 'why': _s(x.get('why')),
                         'severity': _enum(x.get('severity'), ['minor', 'major', 'fatal'], 'major'),
                         'answer_with': _s(x.get('answer_with'))} for x in _items(r.get('risks'), 3) if x.get('title')]
    elif agent_id == 'customers':
        panel = [{'persona': _s(x.get('persona'), 90), 'reaction': _s(x.get('reaction'), 260),
                  'would_try': _enum(x.get('would_try'), ['yes', 'maybe', 'no'], 'maybe'),
                  'objection': _s(x.get('objection')), 'would_pay_if': _s(x.get('would_pay_if'))}
                 for x in _items(r.get('panel'), 3) if x.get('reaction')]
        out['panel'] = panel
        out['tally'] = {k: sum(1 for p in panel if p['would_try'] == k) for k in ('yes', 'maybe', 'no')}
        out['synthetic'] = True
    elif agent_id == 'market':
        count, price = _int(r.get('count')), _int(r.get('price_per_year'))
        out.update({'unit': _s(r.get('unit'), 80), 'count': count, 'count_basis': _s(r.get('count_basis')),
                    'price_per_year': price, 'price_basis': _s(r.get('price_basis')),
                    'estimate': count * price,      # computed here, never by the model
                    'confidence': _enum(r.get('confidence'), ['low', 'medium'], 'low'),
                    'assumptions': _strs(r.get('assumptions'), 3), 'bigger_market': _s(r.get('bigger_market'))})
    elif agent_id == 'pitch':
        out.update({'one_liners': _strs(r.get('one_liners'), 3, 160), 'elevator': _s(r.get('elevator'), 520),
                    'avoid': _s(r.get('avoid'), 120)})
    elif agent_id == 'gtm':
        out.update({'channel': _s(r.get('channel'), 80), 'why_channel': _s(r.get('why_channel')),
                    'message_angle': _s(r.get('message_angle')), 'first_10': _strs(r.get('first_10'), 4),
                    'week_one': _strs(r.get('week_one'), 4)})
    elif agent_id == 'experiments':
        out['tests'] = [{'assumption': _s(x.get('assumption')), 'method': _s(x.get('method')),
                         'cost': _s(x.get('cost'), 30), 'days': min(_int(x.get('days')), 90),
                         'pass_if': _s(x.get('pass_if'))} for x in _items(r.get('tests'), 3) if x.get('method')]
    elif agent_id == 'chief':
        out.update({'verdict': _enum(r.get('verdict'), ['keep_going', 'narrow', 'rethink'], 'narrow'),
                    'why': _s(r.get('why'), 300), 'next_actions': _strs(r.get('next_actions'), 3),
                    'disagreement': _s(r.get('disagreement'))})
    return out


def is_useful(agent_id: str, out: Dict[str, Any]) -> bool:
    key = {'skeptic': 'risks', 'customers': 'panel', 'market': 'count', 'pitch': 'one_liners',
           'gtm': 'channel', 'experiments': 'tests', 'chief': 'next_actions'}[agent_id]
    return bool(out.get(key)) and bool(out.get('headline'))


# ── Prompting ────────────────────────────────────────────────────────────────

def _summarize_output(agent_id: str, out: Dict[str, Any]) -> str:
    """Compact view of a teammate's output for stage-2 agents."""
    o = dict(out)
    o.pop('synthetic', None)
    return f"{BY_ID[agent_id]['name']}: {json.dumps(o, ensure_ascii=False)[:1200]}"


def build_messages(agent: Dict[str, Any], state: Dict[str, Any], prior: Dict[str, Any]) -> List[Dict[str, str]]:
    from .idea_studio import pick_next_questions, render_sources
    team = [_summarize_output(u, prior[u]['output']) for u in agent.get('uses', [])
            if (prior.get(u) or {}).get('output')]
    targets = pick_next_questions(state)
    context = {
        'fields': dict(st.iter_claims(state)),
        'next_missing_slot': targets[0]['field'] if targets else None,
        'parked': state['parked'],
        'risky_assumptions': state['risky_assumptions'],
        'open_objections': state['open_objections'],
        'market': state['why_not_built'],
    }
    user = f"IDEA STATE:\n{json.dumps(context, ensure_ascii=False)}\n\nEVIDENCE:\n{render_sources(state)}"
    if team:
        user += "\n\nTEAM FINDINGS (from other agents; treat as input, not fact):\n" + '\n'.join(team)
    user += "\n\nReturn the JSON object now."
    return [{'role': 'system', 'content': agent['prompt'] + '\n\n' + COMMON_RULES + '\nUse existing fields as context. Ask only about the next missing field or evidence gaps. Never ask a founder to repeat a locked decision.'},
            {'role': 'user', 'content': user}]


# ── Sample output for MOCK_MODE (always labelled source="sample") ────────────

SAMPLE: Dict[str, Dict[str, Any]] = {
    'skeptic': {'headline': 'Buyers may not trust a new vendor with their invoices.',
                'risks': [{'title': 'Data access is the gate', 'why': 'Finance teams rarely hand invoice data to an unknown startup.',
                           'severity': 'major', 'answer_with': 'Three teams agreeing to share last month of invoices.'}]},
    'customers': {'headline': 'Two of three would try it if setup takes under an hour.',
                  'panel': [{'persona': 'Ops lead at a small team', 'reaction': 'If it finds money we are losing, I want it yesterday.',
                             'would_try': 'yes', 'objection': 'Setup time', 'would_pay_if': 'It pays for itself in a month'}]},
    'market': {'headline': 'Sample estimate only.', 'unit': 'small company', 'count': 10000, 'count_basis': 'sample',
               'price_per_year': 2400, 'price_basis': 'sample', 'confidence': 'low', 'assumptions': ['Sample data'],
               'bigger_market': 'Mid-size companies'},
    'pitch': {'headline': 'Lead with the money recovered, not the software.',
              'one_liners': ['Sample one-liner.'], 'elevator': 'Sample pitch.', 'avoid': 'AI-powered'},
    'gtm': {'headline': 'Start with founder-led outreach in one community.', 'channel': 'Founder-led outreach',
            'why_channel': 'Sample data.', 'message_angle': 'Sample angle.', 'first_10': ['Sample step'], 'week_one': ['Sample task']},
    'experiments': {'headline': 'Test data access before building anything.',
                    'tests': [{'assumption': 'Teams will share data', 'method': 'Ask 10 teams for one month of data',
                               'cost': '$0', 'days': 7, 'pass_if': '3 of 10 agree'}]},
    'chief': {'headline': 'Promising, but prove data access first.', 'verdict': 'narrow', 'why': 'Sample data.',
              'next_actions': ['Sample action one', 'Sample action two', 'Sample action three'], 'disagreement': ''},
}


# ── Orchestration ────────────────────────────────────────────────────────────

def _mock_mode() -> bool:
    return os.environ.get('MOCK_MODE', '').lower() == 'true'


def default_llm_factory(agent_id: str):
    from .idea_studio import _llm
    return _llm('IDEA_AGENT_MODEL')


def _run_one(agent: Dict[str, Any], state: Dict[str, Any], prior: Dict[str, Any],
             llm_factory: Callable[[str], Any]) -> Dict[str, Any]:
    if _mock_mode():
        return {'output': normalize(agent['id'], SAMPLE[agent['id']]), 'source': 'sample'}
    llm = llm_factory(agent['id'])
    raw = llm.chat_json(build_messages(agent, state, prior), temperature=0.5, max_tokens=900)
    out = normalize(agent['id'], raw)
    if not is_useful(agent['id'], out):
        raise ValueError('the agent returned nothing usable')
    return {'output': out, 'source': 'model'}


def run_team(raw_state: Any, prior: Optional[Dict[str, Any]] = None, only: Optional[List[str]] = None,
             force: bool = False, llm_factory: Optional[Callable[[str], Any]] = None) -> Iterator[Dict[str, Any]]:
    """Run the agents whose inputs changed (or `only`, forced). Each stage runs in parallel, stages in order."""
    state = st.validate_client_state(raw_state)
    prior = {k: v for k, v in (prior or {}).items() if k in BY_ID and isinstance(v, dict)}
    llm_factory = llm_factory or default_llm_factory
    wanted = set(only or AGENT_IDS) & set(AGENT_IDS)

    plan = []
    for a in AGENTS:
        missing = missing_for(a, state)
        status = 'waiting' if missing else ('queued' if a['id'] in wanted else 'fresh')
        plan.append({'id': a['id'], 'status': status, 'missing': missing})
    # Stage-1 plan is final; stage-2 freshness is decided after stage 1 (its inputs may change)
    yield {'type': 'plan', 'agents': plan}
    ready = {p['id'] for p in plan if p['status'] != 'waiting'}

    ran = 0
    results = dict(prior)
    for stage in (1, 2, 3):
        todo = []
        for a in AGENTS:
            if a['stage'] != stage or a['id'] not in ready or a['id'] not in wanted:
                continue
            if a.get('min_inputs'):
                have = sum(1 for u in a['uses'] if (results.get(u) or {}).get('output'))
                if have < a['min_inputs']:
                    yield {'type': 'agent', 'id': a['id'], 'status': 'waiting',
                           'missing': [f"{a['min_inputs'] - have} more teammate reports"]}
                    continue
            fp = fingerprint(a, state, results)
            if not force and (results.get(a['id']) or {}).get('fingerprint') == fp:
                yield {'type': 'agent', 'id': a['id'], 'status': 'fresh'}
                continue
            todo.append((a, fp))
        if not todo:
            continue
        for a, _ in todo:
            yield {'type': 'agent', 'id': a['id'], 'status': 'running'}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_run_one, a, state, results, llm_factory): (a, fp) for a, fp in todo}
            for fut in as_completed(futures):
                a, fp = futures[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    logger.warning(f"Agent {a['id']} failed: {e}")
                    yield {'type': 'agent', 'id': a['id'], 'status': 'failed',
                           'error': 'This agent could not finish. Its last result is kept.'}
                    continue
                ran += 1
                results[a['id']] = {'output': r['output'], 'fingerprint': fp, 'source': r['source'],
                                    'turn': state['meta']['turn']}
                yield {'type': 'agent', 'id': a['id'], 'status': 'done', 'output': r['output'],
                       'fingerprint': fp, 'source': r['source'], 'turn': state['meta']['turn']}
    yield {'type': 'done', 'ran': ran}


def roster() -> List[Dict[str, Any]]:
    """Public description of the specialist agents (for the UI)."""
    return [{'id': a['id'], 'name': a['name'], 'role': a['role'], 'stage': a['stage'],
             'uses': a.get('uses', [])} for a in AGENTS]
