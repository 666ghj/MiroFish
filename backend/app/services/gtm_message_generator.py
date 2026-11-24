"""
GTM Message Generator - produces 2–5 outreach message variants from a GTM brief and buyer personas.
Default angles: pain_first, roi_first, curiosity_first.
Extended angles: feature_first, social_proof_first.
"""

import os
import json
import uuid
from typing import List, Dict, Any, Optional
from collections import Counter

from ..utils.llm_client import LLMClient
from ..utils.text_style import strip_em_dashes
from ..utils.logger import get_logger

logger = get_logger('mirofish.gtm_message_generator')

_MOCK_PATH = os.path.join(
    os.path.dirname(__file__), '../../mock_data/gtm_messages.json'
)

ALL_ANGLES = ['pain_first', 'roi_first', 'curiosity_first', 'feature_first', 'social_proof_first']
ANGLES = ALL_ANGLES  # kept for validation compatibility

ANGLE_DESCRIPTIONS = {
    'pain_first':        'Lead with the #1 pain point your ICP feels daily',
    'roi_first':         'Lead with concrete ROI, time saved, or revenue impact',
    'curiosity_first':   'Open with an intriguing question or unexpected insight',
    'feature_first':     'Lead with a specific product capability that solves a clear problem',
    'social_proof_first':'Lead with a customer success story or peer validation',
}

SYSTEM_PROMPT = """You are a senior B2B cold outreach copywriter specializing in founder-led sales.
Generate concise, founder-style outreach messages for cold outbound email and LinkedIn.

Rules:
- Max 80 words per message body
- No buzzwords or corporate marketing language
- Never use em dashes. Use commas, periods, colons, or parentheses instead.
- Sound like a real person, not a marketing department
- Use {first_name} as the only personalization token
- Subject line: max 10 words, no clickbait
- Make each angle feel genuinely different in opening style and value framing

Each object must have these exact fields:
{
  "id": "<unique id like msg_pain_001>",
  "angle": "<exact angle name from the list provided>",
  "subject_line": "<compelling subject line>",
  "body": "<80-word max message with {first_name} token>",
  "target_persona_reasoning": "<one sentence on who this angle works best for>"
}
Return ONLY a valid JSON array, no markdown."""


def _build_user_prompt(brief: Any, personas: list, selected_angles: list) -> str:
    angles = [p.get('likely_message_angle', '') for p in personas if p.get('likely_message_angle')]
    angle_dist = Counter(angles)
    angle_summary = ', '.join(f"{k}: {v}" for k, v in angle_dist.most_common())
    competitors = ', '.join(brief.competitors) if brief.competitors else 'not specified'
    angle_list = '\n'.join(f"- {a}: {ANGLE_DESCRIPTIONS[a]}" for a in selected_angles)

    return f"""GTM Brief:
Product: {brief.product_name} - {brief.product_description}
ICP: {brief.icp}
Pricing: {brief.pricing_model}
Target Market: {brief.target_market}
Sales Channel: {brief.sales_channel}
Main Pain Point: {brief.pain_point}
GTM Goal: {brief.gtm_goal}
Competitors: {competitors}

Persona angle preferences (from {len(personas)} buyer personas): {angle_summary}

Generate exactly {len(selected_angles)} outreach messages using these angles:
{angle_list}

Tailor each message to the product and ICP. Make each genuinely different."""


def _validate(msg: dict) -> bool:
    required = ['id', 'angle', 'subject_line', 'body', 'target_persona_reasoning']
    return all(f in msg and msg[f] for f in required) and msg.get('angle') in ANGLES


def _load_mock() -> List[Dict]:
    try:
        with open(_MOCK_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Could not load mock messages: {e}")
        return []


class GTMMessageGenerator:

    def __init__(self):
        self._llm: Optional[LLMClient] = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def generate(self, brief: Any, personas: list, count: int = 3) -> List[Dict]:
        """
        Generate `count` outreach message variants (2–5) from a GTMBrief.
        Falls back to mock data on any error.
        """
        count = max(2, min(5, count))
        selected_angles = ALL_ANGLES[:count]
        try:
            if os.environ.get('MOCK_MODE', '').lower() == 'true':
                raise RuntimeError('MOCK_MODE is enabled')
            messages_prompt = [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': _build_user_prompt(brief, personas, selected_angles)},
            ]
            result = strip_em_dashes(self._get_llm().chat_json(messages_prompt, temperature=0.7, max_tokens=2000 + count * 200))

            if isinstance(result, list):
                msgs = result
            elif isinstance(result, dict):
                msgs = next((v for v in result.values() if isinstance(v, list)), [])
            else:
                raise ValueError(f"Unexpected response type: {type(result)}")

            valid = [m for m in msgs if _validate(m)]
            if len(valid) < max(1, count // 2):
                logger.warning(f"Only {len(valid)} valid messages from LLM, using mock fallback")
                return _load_mock()[:count]

            # Ensure unique ids
            for m in valid:
                if not m.get('id'):
                    m['id'] = f"msg_{m['angle']}_{str(uuid.uuid4())[:6]}"

            logger.info(f"Generated {len(valid[:count])} outreach message variants via LLM")
            return valid[:count]

        except Exception as e:
            logger.warning(f"Message generation via LLM failed ({e}), using mock fallback")
            return _load_mock()[:count]
