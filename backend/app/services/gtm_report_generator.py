"""
GTM Report Generator — produces a structured GTMReport from existing simulation data.
Hybrid approach: deterministic fields computed from cached aggregations + single LLM call
for narrative sections (executive summary, recommendations, 7-day experiment, etc.).
Falls back to mock_data/gtm_report.json on any LLM or validation failure.
"""

import os
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.gtm_report_generator')

_MOCK_PATH = os.path.join(
    os.path.dirname(__file__), '../../mock_data/gtm_report.json'
)

REQUIRED_KEYS = [
    'id', 'created_at', 'brief_id',
    'executive_summary', 'best_icp', 'winning_message',
    'top_objections', 'buyer_readiness', 'risk_signals',
    'recommended_workflow', 'seven_day_experiment', 'next_experiment',
]

SYSTEM_PROMPT = """You are a B2B GTM strategist generating a structured report for a founder.
Given simulation data (buyer personas, message performance, reactions, and aggregated scores),
produce an actionable GTM decision report.

Rules:
- Be specific — reference the actual product, ICP, and simulation results provided
- Do not give generic marketing advice; ground every insight in the data
- seven_day_experiment must have exactly 7 entries (day 1 through 7)
- risk_signals: identify 2-4 risks from the common risk_signal themes in the reactions
- recommended_workflow.steps: 6-8 agentic steps (discover → enrich → send → follow up → log → route → update)
- Return ONLY a valid JSON object, no markdown, no wrapper keys

JSON schema:
{
  "executive_summary": "<2-3 sentences summarizing simulation outcome and recommended action>",
  "best_icp": {
    "segment": "<specific segment description>",
    "reasoning": "<why this segment scored highest>",
    "confidence_score": <0.0-1.0>
  },
  "winning_message": {
    "reasoning": "<why this angle won in the simulation>"
  },
  "top_objections": [
    { "objection": "<objection text>", "frequency": <int>, "suggested_response": "<how to address it>" }
  ],
  "buyer_readiness": {
    "reasoning": "<what the score means and what would improve it>"
  },
  "risk_signals": [
    { "signal": "<risk description>", "severity": "<low|medium|high>", "mitigation": "<how to address>" }
  ],
  "recommended_workflow": {
    "title": "Agentic GTM Workflow",
    "steps": ["<step 1>", "..."]
  },
  "seven_day_experiment": [
    { "day": 1, "goal": "<goal>", "action": "<specific action>", "success_metric": "<what good looks like>" }
  ],
  "next_experiment": "<one sentence: what to test next after this outbound run>"
}"""


def _build_user_prompt(brief, personas: list, deterministic: dict, summaries: list, winner: dict) -> str:
    winning_msg = deterministic.get('winning_message', {})
    readiness = deterministic.get('buyer_readiness', {})
    top_obj = deterministic.get('top_objections', [])

    best_personas = []
    worst_personas = []
    if summaries:
        winning_summary = next((s for s in summaries if s.get('angle') == winner.get('winner_angle')), None)
        if winning_summary:
            best_personas = winning_summary.get('best_fit_personas', [])[:3]
            worst_personas = winning_summary.get('worst_fit_personas', [])[:3]

    # Map persona IDs to names
    persona_map = {p['id']: p.get('name', p['id']) for p in personas}
    best_names = [persona_map.get(pid, pid) for pid in best_personas]
    worst_names = [persona_map.get(pid, pid) for pid in worst_personas]

    competitors = ', '.join(brief.competitors) if brief.competitors else 'not specified'
    obj_summary = '; '.join(
        f'"{o["objection"]}" (×{o["frequency"]})' for o in top_obj[:3]
    )

    # Per-message score summary
    msg_scores = []
    for s in summaries:
        msg_scores.append(
            f"  {s['angle']}: avg interest {s['average_interest_score']}, "
            f"{s['positive_count']} positive / {s['neutral_count']} neutral / {s['negative_count']} negative"
        )
    scores_text = '\n'.join(msg_scores)

    return f"""GTM Brief:
Product: {brief.product_name} — {brief.product_description}
ICP: {brief.icp}
Pricing: {brief.pricing_model}
Target Market: {brief.target_market}
Sales Channel: {brief.sales_channel}
Pain Point: {brief.pain_point}
GTM Goal: {brief.gtm_goal}
Competitors: {competitors}
Company Stage: {brief.company_stage or 'not specified'}
Team Size: {brief.team_size or 'not specified'}

Simulation Results ({len(personas)} buyer personas × 3 message angles):
{scores_text}

Winning Angle: {winner.get('winner_angle', 'unknown')}
  Average interest score: {winning_msg.get('average_score', 'N/A')}
  Recommended subject line: {winning_msg.get('recommended_subject_line', 'N/A')}

Buyer Readiness Score: {readiness.get('score', 'N/A')}/10 ({readiness.get('label', 'N/A')})

Top Objections Raised:
{obj_summary or 'No objections recorded'}

Best-fit personas: {', '.join(best_names) or 'N/A'}
Worst-fit personas: {', '.join(worst_names) or 'N/A'}

Generate the GTM report JSON now. Be specific to this product and simulation data."""


def _compute_deterministic(messages: list, reactions: list, summaries: list, winner: dict) -> dict:
    """Compute fields that don't need LLM — extracted directly from simulation data."""
    # Winning message fields
    winning_angle = winner.get('winner_angle', '')
    winning_msg_obj = next((m for m in messages if m.get('angle') == winning_angle), None)
    winning_summary = next((s for s in summaries if s.get('angle') == winning_angle), None)

    winning_message = {
        'angle': winning_angle,
        'average_score': winning_summary.get('average_interest_score', 0.0) if winning_summary else 0.0,
        'recommended_subject_line': winning_msg_obj.get('subject_line', '') if winning_msg_obj else '',
        'recommended_body': winning_msg_obj.get('body', '') if winning_msg_obj else '',
        'reasoning': '',  # filled by LLM
    }

    # Buyer readiness: mean interest across all reactions
    all_scores = [r.get('interest_score', 5.0) for r in reactions if isinstance(r.get('interest_score'), (int, float))]
    avg_score = round(sum(all_scores) / len(all_scores), 2) if all_scores else 5.0
    if avg_score >= 7.0:
        readiness_label = 'high'
    elif avg_score >= 5.0:
        readiness_label = 'medium'
    else:
        readiness_label = 'low'

    buyer_readiness = {
        'score': avg_score,
        'label': readiness_label,
        'reasoning': '',  # filled by LLM
    }

    # Top objections from winning-message reactions
    winning_msg_id = winning_msg_obj.get('id', '') if winning_msg_obj else ''
    winning_reactions = [r for r in reactions if r.get('message_id') == winning_msg_id]
    objection_counts = Counter(
        r['objection'] for r in winning_reactions
        if r.get('objection') and isinstance(r['objection'], str)
    )
    top_objections = [
        {'objection': obj, 'frequency': count, 'suggested_response': ''}
        for obj, count in objection_counts.most_common(3)
    ]

    return {
        'winning_message': winning_message,
        'buyer_readiness': buyer_readiness,
        'top_objections': top_objections,
    }


def _validate(report: dict) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in report]
    if missing:
        raise ValueError(f"GTM report missing required keys: {missing}")
    if not isinstance(report.get('seven_day_experiment'), list) or len(report['seven_day_experiment']) != 7:
        raise ValueError("seven_day_experiment must be a list of exactly 7 items")
    if not isinstance(report.get('risk_signals'), list) or not report['risk_signals']:
        raise ValueError("risk_signals must be a non-empty list")


def _load_mock() -> dict:
    try:
        with open(_MOCK_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Could not load mock GTM report: {e}")
        return {}


class GTMReportGenerator:

    def __init__(self):
        self._llm: Optional[LLMClient] = None

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def generate(self, brief, personas: list, messages: list, reactions: list,
                 summaries: list, winner: dict) -> dict:
        """
        Build deterministic fields from aggregated data, then call LLM for narrative
        sections. Falls back to mock on any error.
        """
        deterministic = _compute_deterministic(messages, reactions, summaries, winner)

        try:
            prompt_messages = [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': _build_user_prompt(
                    brief, personas, deterministic, summaries, winner
                )},
            ]
            result = self._get_llm().chat_json(prompt_messages, temperature=0.5, max_tokens=4000)

            if not isinstance(result, dict):
                raise ValueError(f"Unexpected response type: {type(result)}")

            # Merge: LLM provides narrative, deterministic overrides factual fields
            report = {**result}

            # Merge winning_message (keep LLM reasoning, override factual fields)
            if isinstance(report.get('winning_message'), dict):
                report['winning_message'].update({
                    k: v for k, v in deterministic['winning_message'].items()
                    if k != 'reasoning'
                })
            else:
                report['winning_message'] = deterministic['winning_message']

            # Merge buyer_readiness
            if isinstance(report.get('buyer_readiness'), dict):
                report['buyer_readiness']['score'] = deterministic['buyer_readiness']['score']
                report['buyer_readiness']['label'] = deterministic['buyer_readiness']['label']
            else:
                report['buyer_readiness'] = deterministic['buyer_readiness']

            # Merge top_objections: use LLM's suggested_responses if available
            llm_objs = report.get('top_objections', [])
            det_objs = deterministic['top_objections']
            merged_objs = []
            for i, det_obj in enumerate(det_objs):
                llm_obj = llm_objs[i] if i < len(llm_objs) else {}
                merged_objs.append({
                    'objection': det_obj['objection'],
                    'frequency': det_obj['frequency'],
                    'suggested_response': llm_obj.get('suggested_response', ''),
                })
            report['top_objections'] = merged_objs

            # Stamp metadata
            report['id'] = f"rpt_{str(uuid.uuid4())[:8]}"
            report['created_at'] = datetime.now(timezone.utc).isoformat()
            report['brief_id'] = brief.brief_id

            _validate(report)
            logger.info(f"GTM report generated for brief {brief.brief_id}")
            return report

        except Exception as e:
            logger.warning(f"GTM report LLM generation failed ({e}), using mock fallback")
            mock = _load_mock()
            # Patch mock with deterministic fields so it reflects actual simulation data
            if mock:
                mock['id'] = f"rpt_{str(uuid.uuid4())[:8]}"
                mock['created_at'] = datetime.now(timezone.utc).isoformat()
                mock['brief_id'] = brief.brief_id
                if 'winning_message' in mock:
                    mock['winning_message'].update({
                        k: v for k, v in deterministic['winning_message'].items()
                        if k != 'reasoning'
                    })
                if 'buyer_readiness' in mock:
                    mock['buyer_readiness']['score'] = deterministic['buyer_readiness']['score']
                    mock['buyer_readiness']['label'] = deterministic['buyer_readiness']['label']
            return mock
