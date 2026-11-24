"""
Audience settings for persona generation.

The simulate page lets a founder shape who the buyers are: the mix of buying roles
(decision maker, champion, evaluator), regions, company sizes, and behavior traits
(risk appetite, budget sensitivity, skepticism, decision speed).

This module validates that input, turns it into prompt instructions for the persona
generator, and guarantees every persona leaves with a valid `region` and an
`archetype_mix` (whole percents per buying role, summing to 100). The frontend uses
that mix to color each persona as an exact blend of the three role colors.
"""

import re
from typing import Any, Dict, List, Optional

ARCHETYPES = {
    'decision_maker': 'decision makers (own the budget and the final call)',
    'champion': 'champions (feel the pain daily and push for change)',
    'evaluator': 'evaluators (check fit, risk, and integration)',
}
ARCHETYPE_IDS = list(ARCHETYPES)
_ROLE_NAMES = {
    'decision_maker': ('decision maker', 'decision makers'),
    'champion': ('champion', 'champions'),
    'evaluator': ('evaluator', 'evaluators'),
}
_ROLE_DESC = {
    'decision_maker': 'owns the budget and the final call',
    'champion': 'feels the pain daily and pushes for change',
    'evaluator': 'checks fit, risk, and integration',
}

DEFAULT_COLORS = {'decision_maker': '#3987e5', 'champion': '#d95926', 'evaluator': '#199e70'}

REGIONS = {
    'north_america': 'North America',
    'latam': 'Latin America',
    'uk_ireland': 'UK & Ireland',
    'western_europe': 'Western Europe',
    'dach': 'DACH (Germany, Austria, Switzerland)',
    'nordics': 'Nordics',
    'middle_east': 'Middle East',
    'africa': 'Africa',
    'india': 'India',
    'southeast_asia': 'Southeast Asia',
    'anz': 'Australia & New Zealand',
    'east_asia': 'Japan & Korea',
}

COMPANY_SIZES = ['1-10', '11-50', '51-200', '201-1000', '1000+']

TRAIT_LEVELS = ['very low', 'low', 'moderate', 'high', 'very high']
TRAITS = ('risk_appetite', 'budget_sensitivity', 'skepticism', 'decision_speed')

# Base blend for each persona_type, used when the model omits archetype_mix (and for mock data).
PERSONA_TYPE_MIX = {
    'founder_seller': (60, 30, 10),
    'vp_sales': (35, 55, 10),
    'revops_lead': (10, 25, 65),
    'sdr_manager': (10, 75, 15),
    'marketing_lead': (15, 60, 25),
    'cfo': (65, 0, 35),
    'enterprise_buyer': (45, 5, 50),
    'startup_operator': (35, 45, 20),
    'agency_owner': (55, 35, 10),
    'sales_enablement': (5, 55, 40),
    'skeptical_buyer': (25, 0, 75),
    'champion_user': (5, 80, 15),
}

_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def apportion(weights: List[float], total: int) -> List[int]:
    """Integer split of `total` proportional to `weights` (largest remainder)."""
    clean = [max(0.0, float(w)) for w in weights]
    s = sum(clean) or 1.0
    exact = [w / s * total for w in clean]
    out = [int(x) for x in exact]
    order = sorted(range(len(exact)), key=lambda i: exact[i] - out[i], reverse=True)
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def _int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def normalize_audience(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate audience input from the client. Unknown keys and values are dropped."""
    if not isinstance(raw, dict):
        return None

    mix_in = raw.get('mix') if isinstance(raw.get('mix'), dict) else {}
    mix = {k: _int(mix_in.get(k), 0, 100, 0) for k in ARCHETYPE_IDS}
    if not any(mix.values()):
        mix = {'decision_maker': 30, 'champion': 45, 'evaluator': 25}

    colors_in = raw.get('colors') if isinstance(raw.get('colors'), dict) else {}
    colors = {
        k: colors_in[k] if isinstance(colors_in.get(k), str) and _HEX.match(colors_in[k]) else DEFAULT_COLORS[k]
        for k in ARCHETYPE_IDS
    }

    regions = [r for r in (raw.get('regions') or []) if r in REGIONS] if isinstance(raw.get('regions'), list) else []
    sizes = [s for s in (raw.get('company_sizes') or []) if s in COMPANY_SIZES] \
        if isinstance(raw.get('company_sizes'), list) else []

    traits_in = raw.get('traits') if isinstance(raw.get('traits'), dict) else {}
    traits = {t: _int(traits_in.get(t), 1, 5, 3) for t in TRAITS}

    return {
        'mix': mix,
        'colors': colors,
        'regions': list(dict.fromkeys(regions)),
        'company_sizes': list(dict.fromkeys(sizes)),
        'traits': traits,
        'seed': _int(raw.get('seed'), 0, 2**31 - 1, 7),
    }


def audience_prompt(audience: Optional[Dict[str, Any]], count: int) -> str:
    """Prompt section describing the audience. Empty when no audience was set."""
    if not audience:
        return ''
    counts = apportion([audience['mix'][k] for k in ARCHETYPE_IDS], count)
    role_line = ', '.join(
        f"about {n} {_ROLE_NAMES[k][0 if n == 1 else 1]} ({_ROLE_DESC[k]})" for k, n in zip(ARCHETYPE_IDS, counts)
    )
    t = audience['traits']
    lines = [
        'Audience settings (follow these closely):',
        f'- Buying roles: {role_line}. A persona can blend roles; its archetype_mix must say by how much.',
    ]
    if audience['regions']:
        names = ', '.join(REGIONS[r] for r in audience['regions'])
        ids = ', '.join(audience['regions'])
        lines.append(
            f'- Regions: spread personas evenly across {names}. Set "region" to one of: {ids}. '
            'Make names, company context, regulations, and communication style fit each region.'
        )
    if audience['company_sizes']:
        lines.append(f"- Company size: {', '.join(audience['company_sizes'])} employees.")
    lines += [
        f"- Risk appetite: {TRAIT_LEVELS[t['risk_appetite'] - 1]} ({t['risk_appetite']}/5). "
        'Reflect it in risk_tolerance; higher means more early adopters willing to try new tools.',
        f"- Budget sensitivity: {TRAIT_LEVELS[t['budget_sensitivity'] - 1]} ({t['budget_sensitivity']}/5). "
        'Reflect it in budget_sensitivity and in budget-related objections.',
        f"- Skepticism: {TRAIT_LEVELS[t['skepticism'] - 1]} ({t['skepticism']}/5). "
        f"Center skepticism_level around {t['skepticism']}, varying by about one point.",
        f"- Decision speed: {TRAIT_LEVELS[t['decision_speed'] - 1]} ({t['decision_speed']}/5). "
        'Low means committee-led and slow; high means one person decides quickly. Reflect it in communication_style.',
    ]
    return '\n'.join(lines)


def _mix_from(value: Any) -> Optional[Dict[str, int]]:
    if not isinstance(value, dict):
        return None
    raw = []
    for k in ARCHETYPE_IDS:
        try:
            raw.append(max(0.0, float(value.get(k, 0))))
        except (TypeError, ValueError):
            return None
    if not any(raw):
        return None
    return dict(zip(ARCHETYPE_IDS, apportion(raw, 100)))


def enrich_personas(personas: List[Dict[str, Any]], audience: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure every persona has archetype_mix (sums to 100) and, when regions are set, a valid region."""
    regions = (audience or {}).get('regions') or []
    for i, p in enumerate(personas):
        mix = _mix_from(p.get('archetype_mix'))
        if mix is None:
            base = PERSONA_TYPE_MIX.get(p.get('persona_type'), (34, 33, 33))
            mix = dict(zip(ARCHETYPE_IDS, base))
        p['archetype_mix'] = mix
        if regions:
            if p.get('region') not in regions:
                p['region'] = regions[i % len(regions)]
        elif p.get('region') not in REGIONS:
            p.pop('region', None)
    return personas
