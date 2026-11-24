"""
GTM Persona Generator - produces realistic B2B buyer personas from a GTM brief.

Personas are generated in parallel batches of BATCH_SIZE so large audiences are not
truncated by a single response's token limit. Each batch gets its exact share of the
audience's role mix and regions, and a different spread of persona types.

Honesty rules:
- A failed batch is retried once, then dropped. Missing personas are never padded with
  sample data; the result reports how many were generated.
- Sample data is used only when too few batches succeed (or the LLM is unavailable),
  and the result is labelled source="mock" with the reason.
"""

import os
import json
import math
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

from ..utils.llm_client import LLMClient
from ..utils.text_style import strip_em_dashes
from ..utils.logger import get_logger
from .gtm_audience import (
    ARCHETYPE_IDS, apportion, audience_prompt, enrich_personas, market_context,
)

logger = get_logger('mirofish.gtm_persona_generator')

_MOCK_PATH = os.path.join(
    os.path.dirname(__file__), '../../mock_data/gtm_personas_full.json'
)

PERSONA_TYPES = [
    'founder_seller', 'vp_sales', 'revops_lead', 'sdr_manager',
    'marketing_lead', 'cfo', 'enterprise_buyer', 'startup_operator',
    'agency_owner', 'sales_enablement', 'skeptical_buyer', 'champion_user',
]

VALID_REACTIONS = {'interested', 'neutral', 'objection'}

BATCH_SIZE = 10            # personas per LLM call; ~10 fit comfortably in one response
MAX_PARALLEL_BATCHES = 6
MIN_COVERAGE = 0.5         # below this share of requested personas, fall back to labelled sample data
VALID_SENSITIVITIES = {'low', 'medium', 'high'}

SYSTEM_PROMPT = """You are a senior B2B GTM strategist. Your job is to generate realistic,
distinct buyer persona profiles for a given product and go-to-market brief.

Each persona must feel like a real person who would realistically encounter this product
in the market. Vary their roles, company stages, goals, objections, and communication styles.
Avoid generic or repetitive profiles.

Never use em dashes in any field; use commas, periods, colons, or parentheses instead.
Return ONLY a valid JSON array. No markdown, no explanation, no wrapper keys.

Each persona object must have these exact fields:
{
  "id": "<unique snake_case id>",
  "name": "<realistic full name>",
  "title": "<job title>",
  "company_type": "<e.g. B2B SaaS, Agency, Enterprise, Startup>",
  "company_stage": "<e.g. Pre-revenue, Seed, Series A, Series B, Bootstrapped, Public>",
  "persona_type": "<one of: founder_seller, vp_sales, revops_lead, sdr_manager, marketing_lead, cfo, enterprise_buyer, startup_operator, agency_owner, sales_enablement, skeptical_buyer, champion_user>",
  "primary_goal": "<one sentence: what they are trying to achieve>",
  "pain_points": ["<2-3 specific pain points as strings>"],
  "buying_triggers": ["<2-3 conditions that would make them buy>"],
  "objections": ["<2-3 realistic objections they would raise>"],
  "communication_style": "<one sentence description of how they communicate and evaluate>",
  "budget_sensitivity": "<one of: low, medium, high>",
  "risk_tolerance": "<one of: low, medium, high>",
  "preferred_channels": ["<subset of: outbound_email, linkedin, cold_call, plg, inbound>"],
  "likely_message_angle": "<one of: pain_led, roi_led, social_proof_led>",
  "summary": "<one sentence: what it takes to win this buyer>",
  "reaction": "<one of: interested, neutral, objection>",
  "skepticism_level": <integer 1-5>,
  "likely_response": "<one sentence quote of what they would actually say to your outreach>",
  "objection_category": "<one of: status_quo_bias, integration_concern, budget_concern, trust_deficit, feature_gap, process_barrier, adoption_risk - or null if reaction is interested>",
  "archetype_mix": {"decision_maker": <0-100>, "champion": <0-100>, "evaluator": <0-100>},
  "region": "<region id from the audience settings, or null if none were given>"
}

archetype_mix says how much of each buying role this person plays, as whole numbers
that sum to 100. Decision maker = owns budget and the final call. Champion = feels the
pain and pushes for change. Evaluator = checks fit, risk, and integration. Most people
blend two or three roles (a founder might be 60/30/10)."""


def _build_user_prompt(brief: Any, count: int, batch: Optional[Dict[str, Any]] = None) -> str:
    competitors = ', '.join(brief.competitors) if brief.competitors else 'None specified'
    audience = getattr(brief, 'audience', None)
    if batch and audience:
        audience = {**audience, 'regions': batch['regions'] or audience.get('regions', [])}
    role_counts = batch['role_counts'] if batch else None
    types = batch['persona_types'] if batch else PERSONA_TYPES
    batch_line = ''
    if batch and batch['total'] > 1:
        batch_line = (f"This is batch {batch['index'] + 1} of {batch['total']} for the same audience. "
                      'Other batches cover other personas, so give every persona a distinct, '
                      'region-appropriate full name and avoid generic archetypes.\n')
    mix_rule = ('Include at least 3 "interested", 3 "neutral", and 3 "objection" reactions.'
                if count >= 9 else 'Include a realistic mix of "interested", "neutral", and "objection" reactions.')
    return f"""GTM Brief:
Product: {brief.product_name} - {brief.product_description}
ICP: {brief.icp}
Pricing: {brief.pricing_model}
Target Market: {brief.target_market}
Sales Channel: {brief.sales_channel}
Main Pain Point: {brief.pain_point}
GTM Goal: {brief.gtm_goal}
Competitors: {competitors}
Company Stage: {brief.company_stage or 'Not specified'}
Team Size: {brief.team_size or 'Not specified'}
Existing Problems: {brief.existing_problems or 'Not specified'}

{audience_prompt(audience, count, role_counts)}

{market_context(audience)}
If live market context is given, let it shape each persona: economic conditions drive budget pressure and urgency,
local outreach rules and culture shape how they react to cold outreach, and upcoming holidays or fiscal year-ends
affect timing objections.

{batch_line}Generate exactly {count} distinct buyer personas as a JSON array.
Use a different persona_type for each persona where possible, preferring in this order: {', '.join(types)}.
Repeat types only when you need more than {len(PERSONA_TYPES)} personas.
Make them context-aware - their goals, objections, and communication styles should
reflect the specific product and ICP described above.
Vary skepticism levels (some should be 1-2, some 3, some 4-5).
{mix_rule}"""


def _load_mock(count: int) -> List[Dict]:
    try:
        with open(_MOCK_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data[:count]
    except Exception as e:
        logger.error(f"Could not load mock personas: {e}")
        return []


def _validate(persona: Dict) -> bool:
    required = [
        'id', 'name', 'title', 'company_type', 'company_stage', 'persona_type',
        'primary_goal', 'pain_points', 'buying_triggers', 'objections',
        'communication_style', 'budget_sensitivity', 'risk_tolerance',
        'preferred_channels', 'likely_message_angle', 'summary',
        'reaction', 'skepticism_level', 'likely_response', 'objection_category',
    ]
    for field in required:
        if field not in persona:
            return False
    if persona.get('reaction') not in VALID_REACTIONS:
        return False
    if persona.get('budget_sensitivity') not in VALID_SENSITIVITIES:
        return False
    if persona.get('risk_tolerance') not in VALID_SENSITIVITIES:
        return False
    if not isinstance(persona.get('skepticism_level'), (int, float)):
        return False
    return True


def _ensure_unique_ids(personas: List[Dict]) -> List[Dict]:
    seen = set()
    for p in personas:
        pid = p.get('id', '')
        if not pid or pid in seen:
            p['id'] = p.get('persona_type', 'persona') + '_' + str(uuid.uuid4())[:8]
        seen.add(p['id'])
    return personas


def plan_batches(audience: Optional[Dict[str, Any]], count: int, seed: int = 7) -> List[Dict[str, Any]]:
    """Split `count` personas into batches with exact role counts, regions, and persona types."""
    n_batches = max(1, math.ceil(count / BATCH_SIZE))
    sizes = apportion([1] * n_batches, count)
    rand = random.Random(seed)

    # Dominant role per persona, matching the audience mix exactly, then interleaved
    mix = (audience or {}).get('mix') or {}
    role_totals = apportion([mix.get(k, 0) for k in ARCHETYPE_IDS], count) if any(mix.values()) else None
    roles: List[int] = []
    if role_totals:
        roles = [i for i, n in enumerate(role_totals) for _ in range(n)]
        rand.shuffle(roles)

    regions_all = (audience or {}).get('regions') or []
    region_slots = [regions_all[i % len(regions_all)] for i in range(count)] if regions_all else []
    if region_slots:
        rand.shuffle(region_slots)

    batches, start = [], 0
    for b, size in enumerate(sizes):
        chunk = slice(start, start + size)
        role_counts = None
        if roles:
            role_counts = [sum(1 for r in roles[chunk] if r == i) for i in range(len(ARCHETYPE_IDS))]
        regions = list(dict.fromkeys(region_slots[chunk])) if region_slots else []
        offset = (b * 5) % len(PERSONA_TYPES)
        batches.append({
            'index': b,
            'total': n_batches,
            'size': size,
            'role_counts': role_counts,
            'regions': regions,
            'persona_types': PERSONA_TYPES[offset:] + PERSONA_TYPES[:offset],
        })
        start += size
    return batches


def _extract_list(result: Any) -> List[Dict]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for val in result.values():
            if isinstance(val, list):
                return val
        raise ValueError("LLM response dict contained no list value")
    raise ValueError(f"Unexpected LLM response type: {type(result)}")


class GTMPersonaGenerator:

    def __init__(self):
        self._llm: Optional[LLMClient] = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def generate(self, brief: Any, count: int = 12) -> List[Dict]:
        """Backward-compatible: returns only the persona list."""
        return self.generate_detailed(brief, count)['personas']

    def generate_detailed(self, brief: Any, count: int = 12) -> Dict[str, Any]:
        """
        Generate `count` personas in parallel batches.

        Returns {
          'personas':       list,
          'meta': {
            'source':         'llm' | 'mock',
            'mock_reason':    str | None,
            'requested':      int,
            'generated':      int,
            'batches':        int,
            'batches_failed': int,
          }
        }
        """
        audience = getattr(brief, 'audience', None)
        meta = {'source': 'llm', 'mock_reason': None, 'requested': count,
                'generated': 0, 'batches': 0, 'batches_failed': 0}

        if os.environ.get('MOCK_MODE', '').lower() == 'true':
            return self._mock(count, meta, 'MOCK_MODE is enabled', audience)
        try:
            self._get_llm()
        except Exception as e:
            return self._mock(count, meta, f'LLM unavailable: {e}', audience)

        batches = plan_batches(audience, count, seed=(audience or {}).get('seed', 7))
        meta['batches'] = len(batches)
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_BATCHES, len(batches))) as pool:
            results = list(pool.map(lambda b: self._run_batch(brief, b), batches))

        personas: List[Dict] = []
        for got in results:
            if got is None:
                meta['batches_failed'] += 1
            else:
                personas.extend(got)

        if len(personas) < max(1, math.ceil(count * MIN_COVERAGE)):
            return self._mock(
                count, meta,
                f'Only {len(personas)} of {count} personas could be generated', audience,
            )

        personas = _ensure_unique_ids(personas[:count])
        meta['generated'] = len(personas)
        logger.info(f"Generated {len(personas)}/{count} personas in {len(batches)} batches "
                    f"({meta['batches_failed']} failed)")
        return {'personas': enrich_personas(personas, audience), 'meta': meta}

    def _run_batch(self, brief: Any, batch: Dict[str, Any], attempts: int = 2) -> Optional[List[Dict]]:
        """One LLM call for one batch, retried once. Returns None if it never succeeds."""
        for attempt in range(1, attempts + 1):
            try:
                messages = [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': _build_user_prompt(brief, batch['size'], batch)},
                ]
                raw = strip_em_dashes(self._get_llm().chat_json(
                    messages, temperature=0.75, max_tokens=900 * batch['size'] + 500))
                valid = [p for p in _extract_list(raw) if isinstance(p, dict) and _validate(p)]
                if len(valid) < max(1, batch['size'] // 2):
                    raise ValueError(f"only {len(valid)}/{batch['size']} valid personas")
                return valid[:batch['size']]
            except Exception as e:
                logger.warning(f"Persona batch {batch['index'] + 1}/{batch['total']} failed "
                               f"(attempt {attempt}/{attempts}): {e}")
        return None

    def _mock(self, count: int, meta: Dict[str, Any], reason: str, audience: Any) -> Dict[str, Any]:
        logger.warning(f"Using sample personas: {reason}")
        personas = _load_mock(count)
        return {
            'personas': enrich_personas(personas, audience),
            'meta': {**meta, 'source': 'mock', 'mock_reason': reason, 'generated': len(personas)},
        }
