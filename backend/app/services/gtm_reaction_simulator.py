"""
GTM Reaction Simulator - simulates buyer reactions to outreach messages.

How a simulation works:
- Personas are scored in small batches (BATCH_SIZE per LLM call) so each persona is
  judged against only a few neighbours instead of being ranked inside one big list.
- The whole simulation is repeated `runs` times with a different persona order each
  run. Scores are averaged across runs and the per-run results are kept so the
  aggregator can report how stable the winning message is.
- Failed batches are retried once. Batches that still fail are dropped (never
  replaced with mock data); coverage is reported.
- Mock data is used only when the LLM is unavailable (MOCK_MODE, no key, or too
  little coverage), and the result is always labelled with source="mock".
"""

import os
import json
import math
import uuid
import random
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

from ..utils.llm_client import LLMClient
from ..utils.text_style import strip_em_dashes
from ..utils.logger import get_logger

logger = get_logger('mirofish.gtm_reaction_simulator')

_MOCK_PATH = os.path.join(
    os.path.dirname(__file__), '../../mock_data/gtm_reactions.json'
)

DEFAULT_RUNS = 3
BATCH_SIZE = 6
MAX_LLM_CALLS = 60          # budget per simulation; runs are reduced to stay under it
MAX_PARALLEL_CALLS = 6
MIN_COVERAGE = 0.5          # below this, the LLM result is not trusted and mock is used

SCORE_FIELDS = ('interest_score', 'clarity_score', 'trust_score', 'urgency_score')
TEXT_FIELDS = ('objection', 'buying_trigger', 'preferred_cta', 'risk_signal', 'simulated_reply')

SYSTEM_PROMPT = """You are a B2B buyer simulation engine.
For each buyer persona, generate a realistic reaction to the outreach message below.

Rules:
- Judge each persona independently, only from that persona's goals, pain points, objections,
  skepticism level, and communication style. Do not rank personas against each other.
- Use the full 0-10 range when the persona's profile justifies it; do not default to the middle.
- interest_score is primary; drive verdict from it (>=7 = positive, 4-6.9 = neutral, <4 = negative)
- simulated_reply should sound like a real person - concise, authentic, includes their likely skepticism or enthusiasm
- Never use em dashes. Use commas, periods, colons, or parentheses instead.
- Return ONLY a valid JSON array, no markdown

Each reaction object must have these exact fields:
{
  "id": "<unique id>",
  "persona_id": "<from persona list>",
  "message_id": "<from message>",
  "interest_score": <0.0-10.0>,
  "clarity_score": <0.0-10.0>,
  "trust_score": <0.0-10.0>,
  "urgency_score": <0.0-10.0>,
  "objection": "<specific objection this persona would raise>",
  "buying_trigger": "<what would make them actually move forward>",
  "preferred_cta": "<their preferred next step>",
  "risk_signal": "<one concern or risk they perceive>",
  "simulated_reply": "<one sentence they'd actually write back>",
  "verdict": "<positive | neutral | negative>"
}"""


def _build_reaction_prompt(message: dict, personas: list) -> str:
    persona_list = []
    for p in personas:
        persona_list.append(
            f"- {p['id']}: {p['name']}, {p['title']} at {p['company_type']} ({p['company_stage']}). "
            f"Goal: {p['primary_goal']}. "
            f"Likely message angle: {p.get('likely_message_angle', 'unknown')}. "
            f"Skepticism: {p.get('skepticism_level', 3)}/5. "
            f"Main objection: {p.get('objections', ['unknown'])[0] if p.get('objections') else 'unknown'}."
        )
    personas_text = '\n'.join(persona_list)

    return f"""Outreach Message:
Angle: {message['angle']}
Subject: {message['subject_line']}
Body: {message['body']}

Buyer Personas ({len(personas)} total):
{personas_text}

Generate one reaction object per persona (total: {len(personas)} reactions).
Set message_id to "{message['id']}" for all reactions."""


def _compute_verdict(interest_score: float) -> str:
    if interest_score >= 7.0:
        return 'positive'
    if interest_score >= 4.0:
        return 'neutral'
    return 'negative'


def _validate_reaction(r: dict) -> bool:
    required = ('id', 'persona_id', 'message_id', 'verdict') + SCORE_FIELDS + TEXT_FIELDS
    if not all(f in r for f in required):
        return False
    for score_field in SCORE_FIELDS:
        try:
            val = float(r[score_field])
            if not (0 <= val <= 10):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _load_mock_reactions() -> List[Dict]:
    try:
        with open(_MOCK_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('reactions', [])
    except Exception as e:
        logger.error(f"Could not load mock reactions: {e}")
        return []


def _plan_runs(requested_runs: int, n_messages: int, n_personas: int) -> int:
    """Reduce runs so the total number of LLM calls stays within MAX_LLM_CALLS."""
    calls_per_run = n_messages * math.ceil(n_personas / BATCH_SIZE)
    if calls_per_run == 0:
        return 0
    return max(1, min(requested_runs, MAX_LLM_CALLS // calls_per_run))


def _merge_runs(run_reactions: List[List[Dict]]) -> List[Dict]:
    """Average scores per persona × message across runs.

    Text fields come from the run whose interest score is closest to the mean, so the
    quoted reply matches the reported score.
    """
    cells: Dict[tuple, List[Dict]] = {}
    for run in run_reactions:
        for r in run:
            cells.setdefault((r['persona_id'], r['message_id']), []).append(r)

    merged = []
    for (persona_id, message_id), samples in cells.items():
        means = {f: round(statistics.fmean(s[f] for s in samples), 2) for f in SCORE_FIELDS}
        interest_runs = [s['interest_score'] for s in samples]
        representative = min(samples, key=lambda s: abs(s['interest_score'] - means['interest_score']))
        reaction = {
            'id': f"rxn_{persona_id}_{message_id}",
            'persona_id': persona_id,
            'message_id': message_id,
            **means,
            **{f: representative.get(f, '') for f in TEXT_FIELDS},
            'verdict': _compute_verdict(means['interest_score']),
            'interest_score_runs': interest_runs,
            'interest_score_spread': round(max(interest_runs) - min(interest_runs), 2),
        }
        merged.append(reaction)
    return merged


class GTMReactionSimulator:

    def __init__(self, llm: Optional[LLMClient] = None):
        self._llm = llm

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    # ── Public API ────────────────────────────────────────────────────────────

    def simulate(self, messages: list, personas: list, runs: int = DEFAULT_RUNS) -> Dict[str, Any]:
        """
        Simulate reactions for all messages × personas, repeated `runs` times.

        Returns:
            {
              'reactions':       merged reactions (scores averaged across runs),
              'run_reactions':   list of per-run reaction lists (for stability),
              'source':          'llm' | 'mock',
              'mock_reason':     why mock data was used, else None,
              'runs_requested':  int,
              'runs_completed':  int,
              'coverage':        share of persona × message × run cells that succeeded,
            }
        """
        if os.environ.get('MOCK_MODE', '').lower() == 'true':
            return self._mock_result('MOCK_MODE is enabled', runs)
        if not messages or not personas:
            return self._mock_result('No messages or personas to simulate', runs)
        try:
            self._get_llm()
        except Exception as e:
            return self._mock_result(f'LLM unavailable: {e}', runs)

        planned_runs = _plan_runs(runs, len(messages), len(personas))
        jobs = []
        for run_index in range(planned_runs):
            order = list(personas)
            random.Random(run_index).shuffle(order)
            for message in messages:
                for start in range(0, len(order), BATCH_SIZE):
                    jobs.append((run_index, message, order[start:start + BATCH_SIZE]))

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            results = list(pool.map(lambda job: (job[0], self._simulate_batch(job[1], job[2])), jobs))

        run_reactions: List[List[Dict]] = [[] for _ in range(planned_runs)]
        for run_index, batch in results:
            run_reactions[run_index].extend(batch)

        expected_cells = planned_runs * len(messages) * len(personas)
        got_cells = sum(len(r) for r in run_reactions)
        coverage = round(got_cells / expected_cells, 3) if expected_cells else 0.0

        if coverage < MIN_COVERAGE:
            logger.warning(f"LLM coverage too low ({coverage:.0%}); using labelled mock data")
            return self._mock_result(
                f'Only {coverage:.0%} of simulated reactions succeeded', runs
            )

        completed = [r for r in run_reactions if r]
        logger.info(
            f"Simulated {got_cells} reactions over {len(completed)} runs "
            f"(coverage {coverage:.0%})"
        )
        return {
            'reactions': _merge_runs(completed),
            'run_reactions': completed,
            'source': 'llm',
            'mock_reason': None,
            'runs_requested': runs,
            'runs_completed': len(completed),
            'coverage': coverage,
        }

    def simulate_all(self, messages: list, personas: list) -> List[Dict]:
        """Backward-compatible wrapper: returns only the merged reaction list."""
        return self.simulate(messages, personas)['reactions']

    # ── Internals ─────────────────────────────────────────────────────────────

    def _mock_result(self, reason: str, runs: int) -> Dict[str, Any]:
        logger.warning(f"Using mock reactions: {reason}")
        reactions = _load_mock_reactions()
        return {
            'reactions': reactions,
            'run_reactions': [reactions] if reactions else [],
            'source': 'mock',
            'mock_reason': reason,
            'runs_requested': runs,
            'runs_completed': 0,
            'coverage': 0.0,
        }

    def _simulate_batch(self, message: dict, personas: list, attempts: int = 2) -> List[Dict]:
        """One LLM call for 1 message × a small batch of personas, retried once."""
        for attempt in range(1, attempts + 1):
            try:
                return self._call_llm(message, personas)
            except Exception as e:
                logger.warning(
                    f"Batch failed for message {message.get('id')} "
                    f"(attempt {attempt}/{attempts}): {e}"
                )
        return []

    def _call_llm(self, message: dict, personas: list) -> List[Dict]:
        prompt_messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': _build_reaction_prompt(message, personas)},
        ]
        result = strip_em_dashes(self._get_llm().chat_json(prompt_messages, temperature=0.6, max_tokens=3000))

        if isinstance(result, list):
            reactions = result
        elif isinstance(result, dict):
            reactions = next((v for v in result.values() if isinstance(v, list)), [])
        else:
            raise ValueError(f"Unexpected response type: {type(result)}")

        persona_ids = {p['id'] for p in personas}
        valid: Dict[str, Dict] = {}
        for r in reactions:
            if not isinstance(r, dict) or r.get('persona_id') not in persona_ids:
                continue
            try:
                for score in SCORE_FIELDS:
                    r[score] = max(0.0, min(10.0, float(r[score])))
            except (KeyError, TypeError, ValueError):
                continue  # a missing score is dropped, never defaulted to a fake 5.0
            r['verdict'] = _compute_verdict(r['interest_score'])
            r['message_id'] = message['id']
            if not r.get('id'):
                r['id'] = f"rxn_{r['persona_id']}_{message['id']}_{str(uuid.uuid4())[:6]}"
            if _validate_reaction(r):
                valid.setdefault(r['persona_id'], r)

        if len(valid) < len(personas) * 0.5:
            raise ValueError(f"Only {len(valid)}/{len(personas)} valid reactions in batch")
        return list(valid.values())
