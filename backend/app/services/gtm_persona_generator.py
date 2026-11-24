"""
GTM Persona Generator - produces 10-12 realistic B2B buyer personas from a GTM brief.
Uses LLMClient.chat_json() with a structured prompt; falls back to mock data if the
LLM is unavailable or returns invalid output.
"""

import os
import json
import uuid
from typing import List, Dict, Any, Optional

from ..utils.llm_client import LLMClient
from ..utils.text_style import strip_em_dashes
from ..utils.logger import get_logger

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
  "objection_category": "<one of: status_quo_bias, integration_concern, budget_concern, trust_deficit, feature_gap, process_barrier, adoption_risk - or null if reaction is interested>"
}"""


def _build_user_prompt(brief: Any, count: int) -> str:
    competitors = ', '.join(brief.competitors) if brief.competitors else 'None specified'
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

Generate exactly {count} distinct buyer personas as a JSON array.
Each persona must use a different persona_type from: {', '.join(PERSONA_TYPES)}.
Make them context-aware - their goals, objections, and communication styles should
reflect the specific product and ICP described above.
Vary skepticism levels (some should be 1-2, some 3, some 4-5).
Include at least 3 "interested", 3 "neutral", and 3 "objection" reactions."""


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


class GTMPersonaGenerator:

    def __init__(self):
        self._llm: Optional[LLMClient] = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def generate(self, brief: Any, count: int = 12) -> List[Dict]:
        """
        Generate `count` buyer personas from a GTMBrief.
        Falls back to mock data on any error.
        """
        try:
            messages = [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': _build_user_prompt(brief, count)},
            ]
            result = strip_em_dashes(self._get_llm().chat_json(messages, temperature=0.75, max_tokens=6000))

            # chat_json returns a dict - look for the array
            if isinstance(result, list):
                personas = result
            elif isinstance(result, dict):
                # model may wrap the array in a key
                for val in result.values():
                    if isinstance(val, list):
                        personas = val
                        break
                else:
                    raise ValueError("LLM response dict contained no list value")
            else:
                raise ValueError(f"Unexpected LLM response type: {type(result)}")

            valid = [p for p in personas if _validate(p)]
            if len(valid) < count // 2:
                logger.warning(f"Too few valid personas from LLM ({len(valid)}/{count}), using mock fallback")
                return _load_mock(count)

            # Pad with mock if LLM returned fewer than requested
            if len(valid) < count:
                mock = _load_mock(count)
                used_types = {p.get('persona_type') for p in valid}
                extras = [p for p in mock if p.get('persona_type') not in used_types]
                valid += extras[:count - len(valid)]

            _ensure_unique_ids(valid)
            logger.info(f"Generated {len(valid)} buyer personas via LLM")
            return valid[:count]

        except Exception as e:
            logger.warning(f"Persona generation via LLM failed ({e}), using mock fallback")
            return _load_mock(count)
