"""
User-authored scheduled events ("God's-eye view").

A scheduled event is a post made by a chosen agent at a chosen simulated hour.
They are written by the user and never invented by the LLM: injecting made-up
future events would put fabricated facts into a forecast. The generator keeps
``scheduled_events`` empty and only offers disabled ``suggested_events``.

Event schema (``event_config.scheduled_events[]``)::

    {"id": "evt_1", "at_sim_hour": 26, "poster_agent_id": 4,
     "poster_type": "MediaOutlet", "content": "...",
     "source": "user|llm_suggested", "enabled": true}

The run scripts fire an enabled event at the start of the round containing its
hour (see ``scripts/sim_behavior.py``).
"""

import math
from typing import Any, Dict, List, Tuple

from .simulation_config_generator import assign_poster_agents

MAX_SCHEDULED_EVENTS = 50
MAX_EVENT_CONTENT_CHARS = 5000
VALID_SOURCES = ("user", "llm_suggested")


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_scheduled_events(
    events: Any, config: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate and normalize a replacement list of scheduled events.

    Returns ``(normalized_events, errors)``. When ``errors`` is non-empty the
    events must not be saved. Checks: the hour lies inside the simulation, the
    poster agent exists (or can be resolved from ``poster_type``), the content
    is non-empty, ids are unique (missing ids are generated) and the flags have
    the right types. The result is ordered by hour.
    """
    errors: List[str] = []
    if not isinstance(events, list):
        return [], ["scheduled_events must be a list"]
    if len(events) > MAX_SCHEDULED_EVENTS:
        return [], [f"at most {MAX_SCHEDULED_EVENTS} scheduled events are allowed"]

    agents = config.get("agent_configs") or []
    agent_ids = {a.get("agent_id") for a in agents if isinstance(a, dict)}
    types_by_id = {a.get("agent_id"): a.get("entity_type") for a in agents if isinstance(a, dict)}
    total_hours = (config.get("time_config") or {}).get("total_simulation_hours", 72)

    given_ids = {
        e.get("id") for e in events
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e.get("id").strip()
    }
    next_number = 1

    def fresh_id() -> str:
        nonlocal next_number
        while f"evt_{next_number}" in given_ids:
            next_number += 1
        new_id = f"evt_{next_number}"
        given_ids.add(new_id)
        return new_id

    normalized: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, event in enumerate(events):
        label = f"event {index + 1}"
        if not isinstance(event, dict):
            errors.append(f"{label}: must be an object")
            continue

        event_id = event.get("id")
        if isinstance(event_id, str) and event_id.strip():
            event_id = event_id.strip()
        else:
            event_id = fresh_id()
        if event_id in seen_ids:
            errors.append(f"{label}: duplicate id '{event_id}'")
            continue
        seen_ids.add(event_id)

        hour = event.get("at_sim_hour")
        if not _is_number(hour):
            errors.append(f"{label}: at_sim_hour must be a number")
            continue
        if hour < 0 or hour >= total_hours:
            errors.append(
                f"{label}: at_sim_hour {hour} is outside the simulation "
                f"(0 to {total_hours} hours)"
            )
            continue
        hour = int(hour) if float(hour).is_integer() else hour

        content = event.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{label}: content must be a non-empty string")
            continue
        content = content.strip()
        if len(content) > MAX_EVENT_CONTENT_CHARS:
            errors.append(f"{label}: content is longer than {MAX_EVENT_CONTENT_CHARS} characters")
            continue

        source = event.get("source", "user")
        if source not in VALID_SOURCES:
            errors.append(f"{label}: source must be one of {', '.join(VALID_SOURCES)}")
            continue
        enabled = event.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{label}: enabled must be true or false")
            continue

        poster_id = event.get("poster_agent_id")
        poster_type = event.get("poster_type")
        if poster_id is not None:
            if isinstance(poster_id, bool) or not isinstance(poster_id, int) or poster_id not in agent_ids:
                errors.append(f"{label}: poster_agent_id {poster_id!r} is not an agent in this simulation")
                continue
            if not (isinstance(poster_type, str) and poster_type.strip()):
                poster_type = types_by_id.get(poster_id) or "Unknown"
        elif isinstance(poster_type, str) and poster_type.strip():
            resolved = assign_poster_agents(
                [{"poster_type": poster_type}], agents, preserve_fields=True
            )
            poster_id = resolved[0]["poster_agent_id"]
            if poster_id not in agent_ids:
                errors.append(f"{label}: could not find an agent for poster_type '{poster_type}'")
                continue
        else:
            errors.append(f"{label}: provide poster_agent_id or poster_type")
            continue

        normalized.append({
            "id": event_id,
            "at_sim_hour": hour,
            "poster_agent_id": poster_id,
            "poster_type": str(poster_type).strip(),
            "content": content,
            "source": source,
            "enabled": enabled,
        })

    normalized.sort(key=lambda e: (e["at_sim_hour"], e["id"]))
    return normalized, errors
