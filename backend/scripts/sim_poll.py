"""
The end-of-run outcome poll: prompt construction and answer parsing.

Distributions across ensemble runs need one number per run. Action counts alone
do not answer the user's question, so every replicate finishes by interviewing
each agent once on 1-3 *outcome questions*. This module holds the pure part of
that: building the single JSON-only prompt and parsing the (often messy) reply.
The OASIS side (actually interviewing the agents) lives in ``sim_runtime``.

Question schema::

    {"id": "q1", "text": "...", "type": "probability"}                      # 0-100
    {"id": "q2", "text": "...", "type": "choice", "options": ["a", "b"]}    # one of options
    {"id": "q3", "text": "...", "type": "number", "unit": "%"}             # any number

A ``choice`` question may carry ``stance_map`` (option -> supportive / opposing
/ neutral) which lets the aggregator measure stance drift.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

POLL_INTRO = "The simulation has ended. Answer as yourself, based only on what you have seen."
MAX_REASON_CHARS = 500

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def build_poll_prompt(questions: Sequence[Mapping[str, Any]]) -> str:
    """The one prompt every agent gets: the questions, then a JSON-only reply format."""
    lines = [POLL_INTRO, "", "Questions:"]
    template: List[str] = []
    for question in questions:
        qid = question["id"]
        qtype = question["type"]
        if qtype == "probability":
            lines.append(f'{qid} (probability, a number from 0 to 100): {question["text"]}')
            template.append(f'"{qid}": <0-100>')
        elif qtype == "choice":
            options = list(question["options"])
            lines.append(f'{qid} (choose exactly one of: {", ".join(options)}): {question["text"]}')
            template.append(f'"{qid}": "<{"|".join(options)}>"')
        else:
            unit = question.get("unit") or ""
            suffix = f" in {unit}" if unit else ""
            lines.append(f"{qid} (a number{suffix}): {question['text']}")
            template.append(f'"{qid}": <number>')
    template.append('"reason": "<one sentence>"')
    lines += [
        "",
        "Reply with ONLY a JSON object, with no other text: {" + ", ".join(template) + "}",
    ]
    return "\n".join(lines)


def extract_json_object(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """The first JSON object found in a model reply, tolerating the usual mess.

    Handles reasoning wrappers (``<think>``), Markdown code fences and prose
    around the object. Returns None when no object can be decoded.
    """
    if not raw:
        return None
    text = re.sub(r"<(think|thinking|thought)>[\s\S]*?</\1>", "", str(raw), flags=re.IGNORECASE).lstrip("﻿").strip()
    candidates: List[str] = []
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = _NUMBER.search(value.replace(",", ""))
        if not match:
            return None
        number = float(match.group())
    else:
        return None
    return number if number == number and abs(number) != float("inf") else None


def _coerce_choice(value: Any, options: Sequence[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("\"'.!,;:() ").lower()
    by_lower = {option.lower(): option for option in options}
    if cleaned in by_lower:
        return by_lower[cleaned]
    # "I would say bullish." -> exactly one option mentioned as a whole word
    mentioned = [
        option for option in options
        if re.search(r"(?<!\w)" + re.escape(option.lower()) + r"(?!\w)", cleaned)
    ]
    return mentioned[0] if len(mentioned) == 1 else None


def coerce_answer(question: Mapping[str, Any], value: Any) -> Optional[Any]:
    """A valid answer for the question, or None.

    probability: a number in [0, 100] ("70", "70%", 70.0 are all accepted);
    choice: one of the options (case-insensitive); number: any finite number.
    """
    qtype = question["type"]
    if qtype == "choice":
        return _coerce_choice(value, question["options"])
    number = _coerce_number(value)
    if number is None:
        return None
    if qtype == "probability" and not 0.0 <= number <= 100.0:
        return None
    return number


def parse_poll_answer(
    raw: Optional[str], questions: Sequence[Mapping[str, Any]]
) -> Tuple[Dict[str, Any], str, bool]:
    """Parse one agent's reply into ``(answers, reason, parse_ok)``.

    ``answers`` holds every question that parsed. ``parse_ok`` is True only when
    *all* questions did: an agent with a partial answer is excluded from the
    statistics but still counted in the parse rate.
    """
    parsed = extract_json_object(raw)
    if parsed is None:
        return {}, "", False

    answers: Dict[str, Any] = {}
    for question in questions:
        if question["id"] not in parsed:
            continue
        answer = coerce_answer(question, parsed[question["id"]])
        if answer is not None:
            answers[question["id"]] = answer

    reason = parsed.get("reason")
    reason = reason.strip()[:MAX_REASON_CHARS] if isinstance(reason, str) else ""
    return answers, reason, len(answers) == len(questions)


def poll_row(
    agent_id: int,
    agent_name: str,
    stance_initial: str,
    raw: Optional[str],
    questions: Sequence[Mapping[str, Any]],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """One ``final_poll.json`` entry."""
    answers, reason, parse_ok = parse_poll_answer(raw, questions)
    row = {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "stance_initial": stance_initial,
        "answers": answers,
        "reason": reason,
        "raw": raw if isinstance(raw, str) else None,
        "parse_ok": parse_ok,
    }
    if error:
        row["error"] = error
    return row
