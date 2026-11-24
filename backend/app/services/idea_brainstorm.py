"""Code-owned coaching ladder and founder-authored brainstorm shortlist."""

import re

MODES = ('brainstorm', 'sharpen', 'stress-test')
MAX_CANDIDATES = 12
MAX_CANDIDATE_CHARS = 400

STEPS = (
    ('', 'What recurring task have you watched someone do the hard way at work or in a community you know?'),
    ('Try looking for a tedious handoff, a spreadsheet held together by email, or a job only one person knows how to do.',
     'Which of those patterns have you seen firsthand?'),
    ('Imagine a theater crew copying shift changes from a group chat onto a whiteboard. The opportunity starts with the missed handoff and who has to fix it.',
     'Where have you seen people copy information between tools just to keep work moving?'),
    ('Try filling in this frame: [specific group] repeatedly struggles to [task], so they [workaround]. When that fails, it costs them [consequence].',
     'Which blanks can you fill from a real incident?'),
)

_STUCK = re.compile(
    r"^(?:i (?:don't|do not) know|idk|no idea|i(?:'m| am) stuck|nothing comes to mind|not sure|help)[.!?\s]*$",
    re.I,
)
_SPARKS = re.compile(
    r"\b(?:give|show|suggest|generate|brainstorm)\s+(?:me\s+)?"
    r"(?:some\s+|a few\s+|\d+\s+)?(?:startup\s+|business\s+|concrete\s+|rough\s+)?(?:ideas|sparks|options)\b",
    re.I,
)
_EXAMPLE = re.compile(r"\b(?:show|give)\s+(?:me\s+)?(?:an?\s+|some\s+)?(?:example|hint|nudge)s?\b", re.I)


def clean_workspace(value):
    raw = value if isinstance(value, dict) else {}
    mode = raw.get('mode')
    level = raw.get('hint_level')
    candidates = raw.get('candidates')
    seen = []
    if isinstance(candidates, list):
        for text in candidates[:MAX_CANDIDATES]:
            if isinstance(text, str):
                text = text.strip()[:MAX_CANDIDATE_CHARS]
                if text and text.casefold() not in {item.casefold() for item in seen}:
                    seen.append(text)
    return {
        'mode': mode if mode in MODES else 'sharpen',
        'hint_level': max(0, min(len(STEPS), level)) if type(level) is int else 0,
        'candidates': seen,
    }


def next_level(current, message, assistance):
    if assistance == 'sparks' or _SPARKS.search(message):
        return len(STEPS)
    if assistance == 'hint' or _EXAMPLE.search(message) or _STUCK.fullmatch(message):
        return min(current + 1, len(STEPS) - 1) if current < len(STEPS) else len(STEPS) - 1
    return 0


def coach_prompt(level, question):
    if level == len(STEPS):
        move = (
            'Offer three contrasting, rough problem hypotheses. Tie each to a task, community, '
            'or capability the founder mentioned. If no such detail is available, label the '
            'hypotheses as illustrative and vary the contexts. Give an unknown to check for '
            'each. Avoid pitches, names, market claims, or treating hypotheses as observations.'
        )
    else:
        context, _ = STEPS[level]
        move = (
            'Reflect a specific detail from the founder if available. Stay at the requested '
            'level of help. Do not pitch products, invent founder experience, or offer concrete '
            f'venture ideas. Use this coaching move if provided: {context}'
        )
    ending = (
        f'Finish with one question on its own line, adapting this question to the founder’s latest detail: {question}'
        if level == 0 else f'The app will end the reply with this question: {question}'
    )
    return (
        'You coach startup founders in Brainstorm mode. Keep it under 150 words and '
        f'use no questions in the body. {move}\n'
        + ending
    )
