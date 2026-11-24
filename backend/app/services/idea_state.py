"""
Idea Studio state: the structured picture of an idea that sharpens every turn.

Design (from the Idea Studio deep research, deep_researchs/*.md):
- Every claim carries a status: unknown, founder_stated, ai_inference, evidence, contradiction.
  "evidence" requires at least one source in the registry; numbers in an evidence claim
  must appear in a cited source.
- Clarity is computed here, in code, from field coverage and status. The model never
  writes it, so it cannot be inflated. It measures completeness, not quality.
- The model changes the state only through small JSON Patch operations (add, replace,
  remove) on whitelisted paths. Locked fields, the score, the source registry, and meta
  are off limits. Every rejected op is returned with a reason.

The state is plain JSON so the browser can store it (Render's disk is not durable).
"""

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1

STATUSES = ('unknown', 'founder_stated', 'ai_inference', 'evidence', 'contradiction')
CONFIDENCE = ('low', 'medium', 'high')
STAGES = ('vague', 'problem', 'customer', 'solution', 'business_model', 'ready')

MAX_TEXT = 400
MAX_LIST = 6
MAX_ASSUMPTIONS = 5
MAX_QUESTIONS = 3
MAX_OBJECTIONS = 8

CHALLENGE_KINDS = ('technical', 'regulatory', 'go_to_market', 'capital', 'team')
WNB_CLASSES = ('unknown', 'nobody_tried', 'tried_and_failed', 'exists_unknown', 'crowded_funded')
BLOCKER_TYPES = ('regulation', 'distribution', 'unit_economics', 'tech_limits', 'incumbents',
                 'timing', 'capital', 'cold_start', 'trust_liability')
BLOCKER_STATES = ('present', 'changed_recently', 'not_applicable', 'unknown')
IMPACTS = ('fatal', 'major', 'minor')

# Single-claim fields the model may write
CLAIM_PATHS = {
    '/one_liner',
    '/problem/statement', '/problem/who', '/problem/severity', '/problem/frequency', '/problem/workaround',
    '/customer/buyer', '/customer/early_adopters', '/customer/where_they_gather',
    '/solution/core', '/solution/smallest_version',
    '/business_model/who_pays', '/business_model/price_anchor',
    '/why_not_built/summary',
}
# Lists of claims
CLAIM_LISTS = {'/why_now', '/what_could_work', '/what_wont_work'} | {f'/challenges/{k}' for k in CHALLENGE_KINDS}
# Lists of structured items
ITEM_LISTS = {
    '/why_not_built/competitors', '/why_not_built/predecessors', '/why_not_built/blockers',
    '/risky_assumptions', '/open_questions', '/open_objections',
}
LIST_LIMITS = {'/risky_assumptions': MAX_ASSUMPTIONS, '/open_questions': MAX_QUESTIONS,
               '/open_objections': MAX_OBJECTIONS}
SCALAR_PATHS = {'/why_not_built/classification'}

# ── Clarity weights (sum 100) ────────────────────────────────────────────────
CLARITY_WEIGHTS = {
    'problem.statement': 12,
    'problem.who': 12,
    'problem.severity': 8,
    'problem.frequency': 6,
    'problem.workaround': 10,
    'solution.core': 8,
    'customer.early_adopters': 8,
    'why_now': 6,
    'why_not_built': 10,
    'business_model': 8,
    'risky_assumptions': 12,
}
CLARITY_SECTIONS = {
    'Problem': ['problem.statement', 'problem.severity', 'problem.frequency', 'problem.workaround'],
    'Customer': ['problem.who', 'customer.early_adopters'],
    'Solution': ['solution.core'],
    'Market': ['why_now', 'why_not_built'],
    'Business model': ['business_model'],
    'Risks and tests': ['risky_assumptions'],
}
FIELD_LABELS = {
    'problem.statement': 'the problem in plain words',
    'problem.who': 'who has the problem',
    'problem.severity': 'how painful it is',
    'problem.frequency': 'how often it happens',
    'problem.workaround': 'what they do today instead',
    'solution.core': 'what the product does',
    'customer.early_adopters': 'who the first customers are',
    'why_now': 'why this is possible now',
    'why_not_built': 'why this has not been built yet',
    'business_model': 'who pays and how much',
    'risky_assumptions': 'the riskiest assumption and its cheapest test',
}


def _claim(text: str = '', status: str = 'unknown') -> Dict[str, Any]:
    return {'text': text, 'status': status, 'specific': False, 'confidence': 'low',
            'source_ids': [], 'locked': False, 'updated_turn': 0}


def new_state(session_id: str = '') -> Dict[str, Any]:
    return {
        'meta': {'schema_version': SCHEMA_VERSION, 'session_id': session_id, 'turn': 0,
                 'version': 0, 'stage': 'vague'},
        'one_liner': _claim(),
        'problem': {k: _claim() for k in ('statement', 'who', 'severity', 'frequency', 'workaround')},
        'customer': {k: _claim() for k in ('buyer', 'early_adopters', 'where_they_gather')},
        'solution': {k: _claim() for k in ('core', 'smallest_version')},
        'business_model': {k: _claim() for k in ('who_pays', 'price_anchor')},
        'why_now': [],
        'what_could_work': [],
        'what_wont_work': [],
        'challenges': {k: [] for k in CHALLENGE_KINDS},
        'why_not_built': {
            'classification': 'unknown',
            'summary': _claim(),
            'competitors': [],
            'predecessors': [],
            'blockers': [],
            'search': {'terms': [], 'providers': [], 'searched_at': None, 'unavailable': [], 'sweeps': 0},
        },
        'risky_assumptions': [],
        'open_questions': [],
        'open_objections': [],
        'sources': {},
        'clarity': {'score': 0, 'by_section': {}, 'top_missing': [], 'computed_by': 'code'},
        'history': [],
    }


# ── Clarity ──────────────────────────────────────────────────────────────────

def _claim_value(c: Optional[Dict[str, Any]]) -> float:
    if not c or not (c.get('text') or '').strip():
        return 0.0
    status = c.get('status')
    if status == 'evidence':
        return 1.0
    if status == 'founder_stated':
        return 0.7 if c.get('specific') else 0.4
    if status == 'ai_inference':
        return 0.2          # a guess fills a gap only a little; the founder must confirm
    return 0.0              # unknown or contradiction


def _best(claims: List[Dict[str, Any]]) -> float:
    return max((_claim_value(c) for c in claims), default=0.0)


def _field_values(state: Dict[str, Any]) -> Dict[str, float]:
    v = {
        'problem.statement': _claim_value(state['problem']['statement']),
        'problem.who': _claim_value(state['problem']['who']),
        'problem.severity': _claim_value(state['problem']['severity']),
        'problem.frequency': _claim_value(state['problem']['frequency']),
        'problem.workaround': _claim_value(state['problem']['workaround']),
        'solution.core': _claim_value(state['solution']['core']),
        'customer.early_adopters': _claim_value(state['customer']['early_adopters']),
        'why_now': _best(state['why_now']),
        'business_model': (_claim_value(state['business_model']['who_pays'])
                           + _claim_value(state['business_model']['price_anchor'])) / 2,
    }
    wnb = state['why_not_built']
    if wnb['classification'] == 'unknown':
        v['why_not_built'] = 0.0
    else:
        has_sources = any(c.get('source_ids') for c in wnb['competitors'] + wnb['predecessors'])
        v['why_not_built'] = 1.0 if has_sources else 0.4
    tested = [a for a in state['risky_assumptions']
              if (a.get('text') or '').strip() and (a.get('test') or {}).get('method')]
    v['risky_assumptions'] = min(1.0, len(tested) / 3) if tested else (
        0.2 if state['risky_assumptions'] else 0.0)
    return v


def compute_clarity(state: Dict[str, Any]) -> Dict[str, Any]:
    values = _field_values(state)
    total = sum(CLARITY_WEIGHTS.values())
    score = round(100 * sum(CLARITY_WEIGHTS[f] * values[f] for f in CLARITY_WEIGHTS) / total)
    by_section = {}
    for name, fields in CLARITY_SECTIONS.items():
        w = sum(CLARITY_WEIGHTS[f] for f in fields)
        by_section[name] = round(100 * sum(CLARITY_WEIGHTS[f] * values[f] for f in fields) / w)
    gaps = sorted(CLARITY_WEIGHTS, key=lambda f: CLARITY_WEIGHTS[f] * (1 - values[f]), reverse=True)
    top_missing = [FIELD_LABELS[f] for f in gaps if values[f] < 0.7][:3]
    return {'score': score, 'by_section': by_section, 'top_missing': top_missing,
            'field_values': {k: round(v, 2) for k, v in values.items()}, 'computed_by': 'code'}


def compute_stage(state: Dict[str, Any], clarity: Dict[str, Any]) -> str:
    fv = clarity['field_values']
    if fv['problem.statement'] < 0.4:
        return 'vague'
    if fv['problem.workaround'] < 0.4 or fv['problem.frequency'] < 0.4:
        return 'problem'
    if fv['problem.who'] < 0.7 or fv['customer.early_adopters'] < 0.4:
        return 'customer'
    if fv['solution.core'] < 0.4 or fv['why_not_built'] == 0:
        return 'solution'
    if fv['business_model'] < 0.4 or fv['risky_assumptions'] < 0.3:
        return 'business_model'
    return 'ready' if clarity['score'] >= 60 else 'business_model'


def refresh(state: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute derived fields (clarity, stage). Call after every change."""
    prev = state.get('clarity', {}).get('score', 0)
    clarity = compute_clarity(state)
    if clarity['score'] < prev:
        contradictions = [p for p, c in iter_claims(state) if c.get('status') == 'contradiction']
        clarity['last_change_reason'] = (
            'Clarity dropped because something contradicts an earlier answer: ' + ', '.join(contradictions[:2])
            if contradictions else 'Clarity dropped because an earlier answer was replaced by a vaguer one.')
    state['clarity'] = clarity
    state['meta']['stage'] = compute_stage(state, clarity)
    return state


def iter_claims(state: Dict[str, Any]):
    """Yield (path, claim) for every single-claim field and every claim in claim lists."""
    for path in sorted(CLAIM_PATHS):
        node = _get(state, path)
        if isinstance(node, dict):
            yield path, node
    for path in sorted(CLAIM_LISTS):
        for i, c in enumerate(_get(state, path) or []):
            yield f'{path}/{i}', c


# ── JSON pointer helpers ─────────────────────────────────────────────────────

def _parts(path: str) -> List[str]:
    if not path.startswith('/'):
        raise ValueError('path must start with /')
    return [p.replace('~1', '/').replace('~0', '~') for p in path[1:].split('/')]


def _get(doc: Any, path: str) -> Any:
    node = doc
    for part in _parts(path):
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def _parent(doc: Any, path: str) -> Tuple[Any, str]:
    parts = _parts(path)
    node = doc
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node, parts[-1]


# ── Value normalisation ──────────────────────────────────────────────────────

def _clean_text(value: Any) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text.replace('—', '-')[:MAX_TEXT]


def _norm(text: str) -> str:
    return re.sub(r'[^a-z0-9 ]', '', (text or '').lower()).strip()


def _normalize_claim(value: Any, turn: int, sources: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Coerce a model-written claim into the claim shape. Returns (claim, warnings)."""
    warnings = []
    if isinstance(value, str):
        value = {'text': value}
    if not isinstance(value, dict):
        raise ValueError('claim must be a string or object')
    status = value.get('status') if value.get('status') in STATUSES else 'ai_inference'
    source_ids = [s for s in (value.get('source_ids') or []) if isinstance(s, str) and s in sources]
    dropped = len(value.get('source_ids') or []) - len(source_ids)
    if dropped:
        warnings.append(f'dropped {dropped} unknown source id(s)')
    text = _clean_text(value.get('text'))
    if status == 'evidence' and not source_ids:
        status = 'ai_inference'
        warnings.append('evidence without a source downgraded to AI inference')
    if status == 'evidence' and not _numbers_supported(text, source_ids, sources):
        status = 'ai_inference'
        warnings.append('numbers not found in the cited sources; downgraded to AI inference')
    claim = {
        'text': text,
        'status': status if text else 'unknown',
        'specific': bool(value.get('specific')) and _looks_specific(text),
        'confidence': value.get('confidence') if value.get('confidence') in CONFIDENCE else 'low',
        'source_ids': source_ids,
        'locked': False,
        'updated_turn': turn,
    }
    if value.get('reason'):
        claim['reason'] = _clean_text(value['reason'])[:160]
    return claim, warnings


# Review sites, publishers, and platforms that show up in search results but are not competitors
NOT_COMPANIES = {
    'gartner', 'gartner peer insights', 'g2', 'capterra', 'getapp', 'software advice', 'trustradius',
    'forbes', 'techcrunch', 'techradar', 'pcmag', 'reddit', 'youtube', 'linkedin', 'wikipedia', 'medium',
    'hacker news', 'github', 'product hunt', 'crunchbase', 'quora', 'substack', 'google', 'amazon',
}

_NUM = re.compile(r'\d[\d,.]*')


def _looks_specific(text: str) -> bool:
    """The model's "specific" flag only counts if the text carries a number or real detail."""
    return bool(re.search(r'\d', text)) or len(text.split()) >= 8


def _numbers_supported(text: str, source_ids: List[str], sources: Dict[str, Any]) -> bool:
    nums = [n.rstrip('.,') for n in _NUM.findall(text)]
    if not nums:
        return True
    haystack = ' '.join(f"{sources[s].get('title', '')} {sources[s].get('snippet', '')}" for s in source_ids)
    return all(n in haystack for n in nums)


def _name_in_sources(name: str, source_ids: List[str], sources: Dict[str, Any]) -> bool:
    n = _norm(name)
    if not n:
        return False
    for s in source_ids:
        src = sources.get(s, {})
        if n in _norm(f"{src.get('title', '')} {src.get('snippet', '')} {src.get('url', '')}"):
            return True
    return False


def _normalize_item(list_path: str, value: Any, turn: int, sources: Dict[str, Any]) -> Tuple[Any, List[str]]:
    warnings: List[str] = []
    if list_path in CLAIM_LISTS:
        claim, warnings = _normalize_claim(value, turn, sources)
        if list_path == '/what_wont_work' and isinstance(value, dict):
            claim['severity'] = value.get('severity') if value.get('severity') in ('medium', 'high', 'critical') else 'medium'
        return claim, warnings
    if not isinstance(value, (dict, str)):
        raise ValueError('item must be an object')

    if list_path in ('/why_not_built/competitors', '/why_not_built/predecessors'):
        if not isinstance(value, dict):
            raise ValueError('company must be an object')
        name = _clean_text(value.get('name'))[:80]
        source_ids = [s for s in (value.get('source_ids') or []) if s in sources]
        if not source_ids:
            raise ValueError(f'"{name}" has no source; companies need a retrieved source')
        if not _name_in_sources(name, source_ids, sources):
            raise ValueError(f'"{name}" does not appear in its cited source')
        if _norm(name) in NOT_COMPANIES:
            raise ValueError(f'"{name}" is a review site or platform, not a competitor')
        item = {'name': name, 'source_ids': source_ids,
                'url': sources[source_ids[0]].get('url', ''),
                'note': _clean_text(value.get('note') or value.get('positioning') or '')[:200],
                'updated_turn': turn}
        if list_path.endswith('competitors'):
            item['status'] = value.get('status') if value.get('status') in ('active', 'dead', 'unknown') else 'unknown'
        else:
            item['failure_reason'] = _clean_text(value.get('failure_reason'))[:200]
            item['status'] = 'dead' if _mentions_shutdown(source_ids, sources) else 'unknown'
            if item['status'] == 'unknown':
                warnings.append(f'no shutdown language found for "{name}"; status left unknown')
        return item, warnings

    if list_path == '/why_not_built/blockers':
        if not isinstance(value, dict):
            raise ValueError('blocker must be an object')
        claim, warnings = _normalize_claim(value, turn, sources)
        claim['type'] = value.get('type') if value.get('type') in BLOCKER_TYPES else 'distribution'
        claim['state'] = value.get('state') if value.get('state') in BLOCKER_STATES else 'unknown'
        return claim, warnings

    if list_path == '/risky_assumptions':
        if isinstance(value, str):
            value = {'text': value}
        claim, warnings = _normalize_claim(value, turn, sources)
        test = value.get('test') if isinstance(value.get('test'), dict) else {}
        claim['impact'] = value.get('impact') if value.get('impact') in IMPACTS else 'major'
        claim['test'] = {
            'method': _clean_text(test.get('method'))[:240],
            'cost_usd': _num(test.get('cost_usd')),
            'days': _num(test.get('days')),
            'pass_criterion': _clean_text(test.get('pass_criterion'))[:200],
        }
        return claim, warnings

    if list_path == '/open_questions':
        if isinstance(value, str):
            value = {'question': value}
        return {'question': _clean_text(value.get('question'))[:240],
                'field': _clean_text(value.get('field'))[:60]}, warnings

    if list_path == '/open_objections':
        text = _clean_text(value if isinstance(value, str) else value.get('text'))[:240]
        return {'text': text, 'raised_turn': turn}, warnings
    raise ValueError('unsupported list')


def _num(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2) if v is not None and v != '' else None
    except (TypeError, ValueError):
        return None


_SHUTDOWN = re.compile(r'\bshut(s|ting)? ?down|\bshuttered|closed (its|their) doors|ceased operations|'
                       r'\bw(ound|inding) down|post-?mortem|\bdissolved|\bbankrupt|\bsunset(s|ted|ting)?\b|'
                       r'\bdiscontinued|went out of business|\bdefunct|\bfolded\b|why we failed', re.I)


def _mentions_shutdown(source_ids: List[str], sources: Dict[str, Any]) -> bool:
    return any(_SHUTDOWN.search(f"{sources[s].get('title', '')} {sources[s].get('snippet', '')}")
               for s in source_ids)


# ── Patch application ────────────────────────────────────────────────────────

def _list_base(path: str) -> Optional[str]:
    """'/why_now/2' -> '/why_now'; '/why_now/-' -> '/why_now'."""
    for base in CLAIM_LISTS | ITEM_LISTS:
        if path == base or path.startswith(base + '/'):
            rest = path[len(base):]
            if rest == '' or re.fullmatch(r'/(\d+|-)', rest):
                return base
    return None


def apply_patch(state: Dict[str, Any], ops: List[Dict[str, Any]], turn: Optional[int] = None,
                reason: str = '') -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Apply model-proposed ops to a copy of `state`.

    Returns (new_state, applied, rejected). Never raises for a bad op; each one is
    either applied or rejected with a reason, so one bad op cannot block the turn.
    """
    new = copy.deepcopy(state)
    turn = new['meta']['turn'] if turn is None else turn
    sources = new['sources']
    applied, rejected = [], []

    for op in ops if isinstance(ops, list) else []:
        try:
            if not isinstance(op, dict):
                raise ValueError('op must be an object')
            kind, path = op.get('op'), op.get('path', '')
            if kind not in ('add', 'replace', 'remove'):
                raise ValueError(f'op "{kind}" not allowed')
            if not isinstance(path, str) or not path.startswith('/'):
                raise ValueError('bad path')

            if path in CLAIM_PATHS:
                current = _get(new, path)
                if current.get('locked'):
                    raise ValueError('field is locked by the founder')
                if kind == 'remove':
                    parent, key = _parent(new, path)
                    parent[key] = {**_claim(), 'updated_turn': turn}
                    applied.append({'op': 'remove', 'path': path})
                    continue
                claim, warns = _normalize_claim(op.get('value'), turn, sources)
                if (_norm(claim['text']) == _norm(current.get('text', ''))
                        and claim['status'] == current.get('status')):
                    raise ValueError('no-op: same meaning as the current value')
                parent, key = _parent(new, path)
                claim['previous'] = {'text': current.get('text', ''), 'status': current.get('status')} \
                    if (current.get('text') or '').strip() else None
                parent[key] = claim
                applied.append({'op': 'replace', 'path': path, 'warnings': warns})
                continue

            if path in SCALAR_PATHS:
                value = op.get('value')
                if value not in WNB_CLASSES:
                    raise ValueError('invalid classification')
                new['why_not_built']['classification'] = value
                applied.append({'op': 'replace', 'path': path})
                continue

            base = _list_base(path)
            if base is None:
                raise ValueError(f'path {path} is not writable')
            lst = _get(new, base)
            index = path[len(base) + 1:] if path != base else None

            if kind == 'remove':
                if index is None or index == '-':
                    raise ValueError('remove needs an index')
                i = int(index)
                if i >= len(lst):
                    raise ValueError('index out of range')
                if isinstance(lst[i], dict) and lst[i].get('locked'):
                    raise ValueError('item is locked by the founder')
                lst.pop(i)
                applied.append({'op': 'remove', 'path': path})
                continue

            item, warns = _normalize_item(base, op.get('value'), turn, sources)
            limit = LIST_LIMITS.get(base, MAX_LIST)
            if kind == 'add' and (index in (None, '-')):
                key = _norm(item.get('text') or item.get('name') or item.get('question') or '')
                if key and any(_norm(x.get('text') or x.get('name') or x.get('question') or '') == key for x in lst):
                    raise ValueError('no-op: already listed')
                if len(lst) >= limit:
                    raise ValueError(f'list is full ({limit})')
                lst.append(item)
            else:
                i = int(index) if index not in (None, '-') else len(lst)
                if kind == 'add':
                    if len(lst) >= limit:
                        raise ValueError(f'list is full ({limit})')
                    lst.insert(min(i, len(lst)), item)
                else:
                    if i >= len(lst):
                        raise ValueError('index out of range')
                    if isinstance(lst[i], dict) and lst[i].get('locked'):
                        raise ValueError('item is locked by the founder')
                    lst[i] = item
            applied.append({'op': kind, 'path': path, 'warnings': warns})
        except (ValueError, KeyError, IndexError, TypeError) as e:
            rejected.append({'op': op, 'reason': str(e)})

    if base_reranked := _rerank_assumptions(new):
        new['risky_assumptions'] = base_reranked
    if applied:
        new['meta']['version'] += 1
        new['history'] = (new['history'] + [{
            'turn': turn, 'version': new['meta']['version'], 'reason': _clean_text(reason)[:200],
            'paths': [a['path'] for a in applied],
        }])[-30:]
    refresh(new)
    return new, applied, rejected


def _rerank_assumptions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    order = {'fatal': 0, 'major': 1, 'minor': 2}
    items = sorted(state['risky_assumptions'], key=lambda a: order.get(a.get('impact'), 1))
    for i, a in enumerate(items, 1):
        a['rank'] = i
    return items


# ── Founder actions and sources (written by code, never by the model) ───────

def set_locked(state: Dict[str, Any], path: str, locked: bool) -> Dict[str, Any]:
    new = copy.deepcopy(state)
    node = _get(new, path)
    if not isinstance(node, dict) or 'locked' not in node:
        raise ValueError('only claims and claim-list items can be locked')
    node['locked'] = bool(locked)
    return new


def founder_edit(state: Dict[str, Any], path: str, text: str) -> Dict[str, Any]:
    """The founder rewrites a field directly: it becomes founder_stated, specific, and locked."""
    new = copy.deepcopy(state)
    node = _get(new, path)
    if not isinstance(node, dict) or 'status' not in node:
        raise ValueError('only claims can be edited')
    node.update({'text': _clean_text(text), 'status': 'founder_stated' if text.strip() else 'unknown',
                 'specific': True, 'locked': True, 'updated_turn': new['meta']['turn']})
    refresh(new)
    return new


def add_sources(state: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Register retrieved search results. Only the evidence service calls this."""
    new = copy.deepcopy(state)
    for r in results:
        sid = r.get('id')
        if sid and r.get('url'):
            new['sources'][sid] = {
                'url': r['url'], 'title': _clean_text(r.get('title'))[:200],
                'snippet': _clean_text(r.get('snippet'))[:MAX_TEXT], 'provider': r.get('provider', ''),
                'purpose': r.get('purpose', ''),
                'published_at': r.get('published_at'), 'retrieved_at': r.get('retrieved_at'),
            }
    return new


def validate_client_state(raw: Any, session_id: str = '') -> Dict[str, Any]:
    """
    The browser stores the state and sends it back every turn. Rebuild it on the known
    schema so a tampered or stale state cannot inject unknown keys or fake scores.
    """
    if not session_id and isinstance(raw, dict) and isinstance(raw.get('meta'), dict):
        sid = str(raw['meta'].get('session_id') or '')
        session_id = sid if re.fullmatch(r'[0-9a-fA-F-]{8,64}', sid) else ''
    base = new_state(session_id)
    if not isinstance(raw, dict):
        return refresh(base)
    sources = {k: v for k, v in (raw.get('sources') or {}).items()
               if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get('url'), str)}
    base = add_sources(base, [{'id': k, **v} for k, v in sources.items()])
    meta = raw.get('meta') if isinstance(raw.get('meta'), dict) else {}
    base['meta']['turn'] = int(meta.get('turn') or 0)
    base['meta']['version'] = int(meta.get('version') or 0)

    def restore_claim(dst: Dict[str, Any], src: Any) -> None:
        if isinstance(src, dict):
            claim, _ = _normalize_claim(src, int(src.get('updated_turn') or 0), base['sources'])
            claim['locked'] = bool(src.get('locked'))
            if src.get('specific'):
                claim['specific'] = True
            dst.clear()
            dst.update(claim)

    for path in CLAIM_PATHS:
        try:
            restore_claim(_get(base, path), _get(raw, path))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    for path in CLAIM_LISTS | ITEM_LISTS:
        try:
            items = _get(raw, path)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        out = []
        for it in (items if isinstance(items, list) else [])[:LIST_LIMITS.get(path, MAX_LIST)]:
            try:
                norm, _ = _normalize_item(path, it, int((it or {}).get('updated_turn') or 0)
                                          if isinstance(it, dict) else 0, base['sources'])
                if isinstance(it, dict) and it.get('locked'):
                    norm['locked'] = True
                out.append(norm)
            except (ValueError, TypeError, AttributeError):
                continue
        parent, key = _parent(base, path)
        parent[key] = out
    wnb = raw.get('why_not_built') if isinstance(raw.get('why_not_built'), dict) else {}
    if wnb.get('classification') in WNB_CLASSES:
        base['why_not_built']['classification'] = wnb['classification']
    if isinstance(wnb.get('search'), dict):
        s = wnb['search']
        base['why_not_built']['search'] = {
            'terms': [_clean_text(t)[:80] for t in (s.get('terms') or [])][:12],
            'providers': [p for p in (s.get('providers') or []) if isinstance(p, str)][:6],
            'searched_at': s.get('searched_at') if isinstance(s.get('searched_at'), str) else None,
            'unavailable': [p for p in (s.get('unavailable') or []) if isinstance(p, str)][:6],
            'sweeps': max(0, min(10, int(s.get('sweeps') or 0))),
        }
    if isinstance(raw.get('history'), list):
        base['history'] = [h for h in raw['history'] if isinstance(h, dict)][-30:]
    return refresh(base)
