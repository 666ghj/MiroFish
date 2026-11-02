"""
Shared agent-behaviour logic for the simulation run scripts.

Everything here is a pure function (or a small stateful helper) with **no OASIS
or camel imports**, so it can be unit tested without the simulation stack. The
three run scripts (``run_parallel_simulation.py``, ``run_twitter_simulation.py``
and ``run_reddit_simulation.py``) share it, which replaces the activation logic
that used to be copied into each of them.

Two behaviour versions exist and are selected by ``config["behavior_version"]``:

* **v1 (legacy)** - the original semantics: a per-round agent count drawn from
  ``agents_per_hour_min/max`` times a time-of-day multiplier, filtered by
  ``active_hours`` and ``activity_level``. Existing simulations keep running
  this way, apart from the RNG source (see below).
* **v2** - the generated agent/event fields actually drive the run: a persona
  directive (stance + sentiment), rate-based activation, reaction delays, a
  seeded follow graph and user-authored scheduled events. ``BEHAVIOR_V2_ENABLED=false``
  in the environment forces v1 everywhere (kill switch).

Reproducibility: every random decision made here goes through an explicit
``random.Random`` derived from the run seed, never the global ``random`` module.
A seed makes the *schedule* (who is woken, reaction delays, the seeded follow
graph, scheduled events) reproducible. It does **not** make LLM outputs
bit-identical.
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

LEGACY_BEHAVIOR_VERSION = 1
CURRENT_BEHAVIOR_VERSION = 2

# --- tunables (kept as constants so they are easy to adjust) -----------------

#: Upper bound on the per-agent, per-round activation probability in v2.
ACTIVATION_PROBABILITY_CAP = 0.95
#: Base probability that one agent follows another when seeding the follow graph.
FOLLOW_BASE_PROBABILITY = 0.3
#: Upper bound on any single seeded-follow probability.
FOLLOW_PROBABILITY_CAP = 0.9
#: Used when a platform config carries no ``echo_chamber_strength``.
DEFAULT_ECHO_CHAMBER_STRENGTH = {"twitter": 0.5, "reddit": 0.6}

VALID_STANCES = ("supportive", "opposing", "neutral", "observer")

#: Number of characters of ``simulation_requirement`` used as a topic fallback.
TOPIC_FALLBACK_CHARS = 120

# Defaults copied from the legacy scripts so v1 behaviour is unchanged.
_DEFAULT_PEAK_HOURS = [9, 10, 11, 14, 15, 20, 21, 22]
_DEFAULT_OFF_PEAK_HOURS = [0, 1, 2, 3, 4, 5]
_DEFAULT_ACTIVE_HOURS = list(range(8, 23))


# --- version / kill switch ---------------------------------------------------

def _env_flag(name: str, default: bool, environ: Optional[Mapping[str, str]] = None) -> bool:
    environ = os.environ if environ is None else environ
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def behavior_version(config: Mapping[str, Any]) -> int:
    """The behaviour version stored in the config (missing/invalid -> 1)."""
    try:
        return int(config.get("behavior_version", LEGACY_BEHAVIOR_VERSION))
    except (TypeError, ValueError):
        return LEGACY_BEHAVIOR_VERSION


def is_behavior_v2(
    config: Mapping[str, Any], environ: Optional[Mapping[str, str]] = None
) -> bool:
    """Whether v2 behaviour applies (config opts in and the kill switch is on)."""
    return behavior_version(config) >= CURRENT_BEHAVIOR_VERSION and _env_flag(
        "BEHAVIOR_V2_ENABLED", True, environ
    )


# --- seeded randomness -------------------------------------------------------

def derive_rng(seed: int, platform: str, purpose: str = "") -> random.Random:
    """An independent RNG for one platform (and optionally one purpose).

    ``derive_rng(seed, "twitter")`` is ``random.Random(f"{seed}:twitter")``.
    Seeding with a string is deterministic across processes and Python versions
    (it does not depend on ``PYTHONHASHSEED``).
    """
    key = f"{seed}:{platform}"
    if purpose:
        key = f"{key}:{purpose}"
    return random.Random(key)


# --- round context and time-of-day multiplier --------------------------------

@dataclass(frozen=True)
class RoundContext:
    """Where the run currently is. ``round_num`` is the 0-based loop index."""

    round_num: int
    simulated_hour: int  # hour of day, 0-23
    minutes_per_round: int


def hour_multiplier(time_config: Mapping[str, Any], hour: int, *, v2: bool) -> float:
    """Time-of-day activity multiplier.

    v1 only knows peak / off-peak (everything else is 1.0), exactly like the old
    scripts. v2 additionally honours the generated ``morning_hours`` and
    ``work_hours`` multipliers, which v1 silently ignored.
    """
    if hour in time_config.get("peak_hours", _DEFAULT_PEAK_HOURS):
        return time_config.get("peak_activity_multiplier", 1.5)
    if hour in time_config.get("off_peak_hours", _DEFAULT_OFF_PEAK_HOURS):
        return time_config.get("off_peak_activity_multiplier", 0.3)
    if v2:
        if hour in time_config.get("morning_hours", []):
            return time_config.get("morning_activity_multiplier", 1.0)
        if hour in time_config.get("work_hours", []):
            return time_config.get("work_activity_multiplier", 1.0)
    return 1.0


# --- reaction delays ---------------------------------------------------------

class EligibilityTracker:
    """``response_delay_min/max`` as reaction latency.

    On every *trigger* (the initial posts, each fired scheduled event) every
    agent draws ``delay ~ U[response_delay_min, response_delay_max]`` simulated
    minutes. The agent cannot be activated before
    ``trigger_round + ceil(delay / minutes_per_round)``; the latest trigger wins.
    Agents with no trigger yet are always eligible. With 60-minute rounds any
    delay up to 60 minutes therefore costs exactly one round.
    """

    def __init__(self, agent_configs: Iterable[Mapping[str, Any]], minutes_per_round: int):
        self._minutes_per_round = max(1, int(minutes_per_round or 1))
        self._delays: Dict[int, Tuple[float, float]] = {}
        for cfg in agent_configs:
            agent_id = cfg.get("agent_id")
            if agent_id is None:
                continue
            low = max(0.0, float(cfg.get("response_delay_min", 0) or 0))
            high = max(low, float(cfg.get("response_delay_max", low) or low))
            self._delays[int(agent_id)] = (low, high)
        self._ready_round: Dict[int, int] = {}

    def on_trigger(self, round_num: int, rng: random.Random) -> None:
        """Draw a fresh reaction delay for every agent (in agent-id order)."""
        for agent_id in sorted(self._delays):
            low, high = self._delays[agent_id]
            delay = rng.uniform(low, high)
            self._ready_round[agent_id] = round_num + math.ceil(
                delay / self._minutes_per_round
            )

    def is_eligible(self, agent_id: int, round_num: int) -> bool:
        ready = self._ready_round.get(agent_id)
        return ready is None or round_num >= ready


# --- activation --------------------------------------------------------------

def activation_probability(
    agent_cfg: Mapping[str, Any],
    time_config: Mapping[str, Any],
    ctx: RoundContext,
) -> float:
    """v2 per-agent, per-round activation probability.

    ``p = clamp(activity_level * (1 - exp(-(posts_per_hour + comments_per_hour)
    * minutes_per_round / 60)) * hour_multiplier, 0, 0.95)``

    The rates shape *how often* an agent is woken; what it then does (post,
    comment, like, nothing ...) is still chosen by the LLM.
    """
    activity = max(0.0, float(agent_cfg.get("activity_level", 0.5) or 0.0))
    posts = max(0.0, float(agent_cfg.get("posts_per_hour", 1.0) or 0.0))
    comments = max(0.0, float(agent_cfg.get("comments_per_hour", 2.0) or 0.0))
    expected = (posts + comments) * ctx.minutes_per_round / 60.0
    probability = (
        activity
        * (1.0 - math.exp(-expected))
        * hour_multiplier(time_config, ctx.simulated_hour, v2=True)
    )
    return min(max(probability, 0.0), ACTIVATION_PROBABILITY_CAP)


def select_active_agents(
    config: Mapping[str, Any],
    ctx: RoundContext,
    rng: random.Random,
    eligibility: Optional[EligibilityTracker] = None,
    *,
    v2: Optional[bool] = None,
) -> List[int]:
    """Choose the agent ids to wake this round.

    The legacy (v1) branch consumes ``rng`` in exactly the order the original
    scripts consumed the global ``random`` module (one ``uniform``, one
    ``random`` per agent active this hour, one ``sample``), so a ``Random``
    seeded like the old global RNG selects the same agents.

    v2 keeps ``agents_per_hour_min/max`` (times the legacy peak/off-peak
    multiplier) as an *upper bound*: when more agents pass their individual draw
    than that, the survivors are subsampled with ``rng.sample``. Each in-hour
    agent always consumes its own draw, whether or not it is eligible, so
    reaction delays never shift which agent gets which draw within a round.
    """
    use_v2 = is_behavior_v2(config) if v2 is None else v2
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])

    base_min = time_config.get("agents_per_hour_min", 5)
    base_max = time_config.get("agents_per_hour_max", 20)
    cap_multiplier = hour_multiplier(time_config, ctx.simulated_hour, v2=False)
    target_count = int(rng.uniform(base_min, base_max) * cap_multiplier)

    candidates: List[int] = []
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        active_hours = cfg.get("active_hours", _DEFAULT_ACTIVE_HOURS)
        if ctx.simulated_hour not in active_hours:
            continue

        if not use_v2:
            if rng.random() < cfg.get("activity_level", 0.5):
                candidates.append(agent_id)
            continue

        draw = rng.random()
        if eligibility is not None and not eligibility.is_eligible(agent_id, ctx.round_num):
            continue
        if draw < activation_probability(cfg, time_config, ctx):
            candidates.append(agent_id)

    if not candidates:
        return []
    return rng.sample(candidates, min(target_count, len(candidates)))


# --- seeded follow graph -----------------------------------------------------

def _stance(agent_cfg: Mapping[str, Any]) -> str:
    stance = str(agent_cfg.get("stance", "neutral") or "neutral").strip().lower()
    return stance if stance in VALID_STANCES else "neutral"


def _stance_relation(a: str, b: str) -> int:
    """+1 same side, -1 opposite sides, 0 otherwise (neutral/observer count as neither)."""
    if a == b and a in ("supportive", "opposing"):
        return 1
    if {a, b} == {"supportive", "opposing"}:
        return -1
    return 0


def echo_chamber_strength(config: Mapping[str, Any], platform: str) -> float:
    platform_config = config.get(f"{platform}_config") or {}
    value = platform_config.get(
        "echo_chamber_strength", DEFAULT_ECHO_CHAMBER_STRENGTH.get(platform, 0.5)
    )
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return DEFAULT_ECHO_CHAMBER_STRENGTH.get(platform, 0.5)


def plan_seed_follows(
    config: Mapping[str, Any],
    rng: random.Random,
    platform: str = "twitter",
) -> List[Tuple[int, int]]:
    """Plan the follow graph the run starts with, as ``(follower, followee)``.

    The follow graph is the lever MiroFish controls for influence and
    echo-chamber effects (OASIS feeds agents the posts of accounts they follow):

    ``P(i follows j) = base * norm_influence(j) * (1 + echo * same(i,j) - echo * opposite(i,j))``

    clamped to ``[0, 0.9]``, with ``base = 0.3``, ``norm_influence`` =
    ``influence_weight / max(influence_weight)`` and ``echo`` = the platform's
    ``echo_chamber_strength``. Exactly one draw is made per ordered pair so the
    random stream has a fixed length for a given agent list.
    """
    agents = sorted(
        (cfg for cfg in config.get("agent_configs", []) if cfg.get("agent_id") is not None),
        key=lambda cfg: int(cfg["agent_id"]),
    )
    if len(agents) < 2:
        return []

    echo = echo_chamber_strength(config, platform)
    influence = {
        int(cfg["agent_id"]): max(0.0, float(cfg.get("influence_weight", 1.0) or 0.0))
        for cfg in agents
    }
    max_influence = max(influence.values()) or 1.0

    follows: List[Tuple[int, int]] = []
    for follower in agents:
        follower_id = int(follower["agent_id"])
        for followee in agents:
            followee_id = int(followee["agent_id"])
            if follower_id == followee_id:
                continue
            relation = _stance_relation(_stance(follower), _stance(followee))
            probability = (
                FOLLOW_BASE_PROBABILITY
                * (influence[followee_id] / max_influence)
                * (1.0 + echo * (relation == 1) - echo * (relation == -1))
            )
            probability = min(max(probability, 0.0), FOLLOW_PROBABILITY_CAP)
            if rng.random() < probability:
                follows.append((follower_id, followee_id))
    return follows


# --- scheduled events --------------------------------------------------------

def event_round(event: Mapping[str, Any], minutes_per_round: int) -> Optional[int]:
    """The loop round (0-based) an event fires in, or None when ``at_sim_hour`` is unusable."""
    try:
        at_hour = float(event.get("at_sim_hour"))
    except (TypeError, ValueError):
        return None
    return math.floor(at_hour * 60 / max(1, int(minutes_per_round or 1)))


def due_scheduled_events(config: Mapping[str, Any], round_num: int) -> List[Dict[str, Any]]:
    """Enabled scheduled events that fire at the start of loop round ``round_num``."""
    minutes_per_round = config.get("time_config", {}).get("minutes_per_round", 60)
    events = (config.get("event_config") or {}).get("scheduled_events") or []
    due = []
    for event in events:
        if not event.get("enabled", True):
            continue
        if event_round(event, minutes_per_round) == round_num:
            due.append(event)
    due.sort(key=lambda e: (float(e["at_sim_hour"]), str(e.get("id", ""))))
    return due


# --- persona directive -------------------------------------------------------

#: The directive text. Edit here to tune how strongly agents anchor on their
#: starting view. The closing sentence is required: without it the outcome is
#: fixed before the run starts and stance drift cannot happen.
DIRECTIVE_TEXT: Dict[str, Dict[str, Any]] = {
    "en": {
        "stance": {
            "supportive": "supportive",
            "opposing": "opposing",
            "neutral": "neutral",
            "observer": "neutral, and you mostly read and rarely post your own opinions",
        },
        "tone": [
            "clearly negative",
            "slightly negative",
            "balanced",
            "slightly positive",
            "clearly positive",
        ],
        "template": (
            '[Starting disposition] On "{topic}", you currently lean {stance}.\n'
            "Your tone tends to be {tone}.\n"
            "{not_a_script}"
        ),
        "not_a_script": (
            "This is your starting view, not a script: update it if you see "
            "convincing evidence or arguments."
        ),
    },
    "zh": {
        "stance": {
            "supportive": "支持",
            "opposing": "反对",
            "neutral": "中立",
            "observer": "中立，并且你主要是围观，很少发表自己的观点",
        },
        "tone": ["明显负面", "略偏负面", "平衡", "略偏正面", "明显正面"],
        "template": (
            "【初始倾向】关于“{topic}”，你目前的态度倾向于{stance}。\n"
            "你的语气通常{tone}。\n"
            "{not_a_script}"
        ),
        "not_a_script": "这只是你的初始看法，而不是剧本：如果看到有说服力的证据或论点，请更新你的看法。",
    },
}


def sentiment_bucket(value: float) -> int:
    """0..4 for <=-0.5, (-0.5,-0.15], (-0.15,0.15), [0.15,0.5), >=0.5."""
    if value <= -0.5:
        return 0
    if value <= -0.15:
        return 1
    if value < 0.15:
        return 2
    if value < 0.5:
        return 3
    return 4


def resolve_topic(config: Mapping[str, Any]) -> str:
    """The short topic phrase used in persona directives.

    ``event_config.topic`` when set, otherwise the first 120 characters of the
    simulation requirement. ``narrative_direction`` is deliberately never used:
    it is the generator's guess at the outcome, and feeding it back to agents
    would make the forecast circular.
    """
    topic = (config.get("event_config") or {}).get("topic")
    if topic and str(topic).strip():
        return str(topic).strip()
    return str(config.get("simulation_requirement") or "").strip()[:TOPIC_FALLBACK_CHARS]


def build_behavior_directive(
    agent_cfg: Mapping[str, Any], requirement_topic: str, locale: str = "en"
) -> str:
    """The persona paragraph appended to an agent's profile in v2 runs."""
    text = DIRECTIVE_TEXT.get(str(locale or "en").lower().split("-")[0], DIRECTIVE_TEXT["en"])
    try:
        sentiment = float(agent_cfg.get("sentiment_bias", 0.0) or 0.0)
    except (TypeError, ValueError):
        sentiment = 0.0
    sentiment = min(max(sentiment, -1.0), 1.0)
    return text["template"].format(
        topic=requirement_topic,
        stance=text["stance"][_stance(agent_cfg)],
        tone=text["tone"][sentiment_bucket(sentiment)],
        not_a_script=text["not_a_script"],
    )


def write_effective_profiles(
    sim_dir: str, config: Mapping[str, Any], out_suffix: str = ".effective"
) -> Dict[str, str]:
    """Write per-run profile copies with the behaviour directive appended.

    ``twitter_profiles.csv`` -> ``twitter_profiles.effective.csv`` (``user_char``)
    and ``reddit_profiles.json`` -> ``reddit_profiles.effective.json``
    (``persona``). The originals are never modified, so the UI and ``/profiles``
    keep showing them. Agent ``i`` is the ``i``-th profile row, exactly as OASIS
    numbers them. Returns ``{"twitter": path, "reddit": path}`` for the files
    that exist.
    """
    topic = resolve_topic(config)
    locale = str(config.get("locale") or "en")
    by_id = {
        int(cfg["agent_id"]): cfg
        for cfg in config.get("agent_configs", [])
        if cfg.get("agent_id") is not None
    }

    def extend(text: Optional[str], agent_id: int) -> str:
        text = text or ""
        cfg = by_id.get(agent_id)
        if cfg is None:
            return text
        directive = build_behavior_directive(cfg, topic, locale)
        return f"{text}\n\n{directive}" if text else directive

    outputs: Dict[str, str] = {}

    twitter_path = os.path.join(sim_dir, "twitter_profiles.csv")
    if os.path.exists(twitter_path):
        with open(twitter_path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        if "user_char" in fieldnames:
            for index, row in enumerate(rows):
                row["user_char"] = extend(row.get("user_char"), index)
        out_path = os.path.join(sim_dir, f"twitter_profiles{out_suffix}.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        outputs["twitter"] = out_path

    reddit_path = os.path.join(sim_dir, "reddit_profiles.json")
    if os.path.exists(reddit_path):
        with open(reddit_path, "r", encoding="utf-8") as handle:
            profiles = json.load(handle)
        for index, profile in enumerate(profiles):
            profile["persona"] = extend(profile.get("persona"), index)
        out_path = os.path.join(sim_dir, f"reddit_profiles{out_suffix}.json")
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(profiles, handle, ensure_ascii=False, indent=2)
        outputs["reddit"] = out_path

    return outputs


# --- per-platform convenience wrapper ---------------------------------------

class PlatformBehavior:
    """All behaviour state for one platform of one run.

    Owns the platform's RNGs (activation, reaction delay, follow graph - all
    derived from the run seed and the platform name, so Twitter and Reddit never
    consume each other's streams) and, in v2, the reaction-delay tracker.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        platform: str,
        seed: int,
        *,
        v2: Optional[bool] = None,
    ):
        self.config = config
        self.platform = platform
        self.seed = seed
        self.v2 = is_behavior_v2(config) if v2 is None else v2
        time_config = config.get("time_config", {})
        self.minutes_per_round = time_config.get("minutes_per_round", 30)
        self.rng = derive_rng(seed, platform)
        self._delay_rng = derive_rng(seed, platform, "delay")
        self._follow_rng = derive_rng(seed, platform, "follow")
        self.eligibility = (
            EligibilityTracker(config.get("agent_configs", []), self.minutes_per_round)
            if self.v2
            else None
        )

    def select_active(self, round_num: int, simulated_hour: int) -> List[int]:
        ctx = RoundContext(round_num, simulated_hour, self.minutes_per_round)
        return select_active_agents(
            self.config, ctx, self.rng, self.eligibility, v2=self.v2
        )

    def initial_posts_published(self) -> None:
        """Start reaction delays for the initial posts (a trigger at round 0)."""
        if self.eligibility is not None:
            self.eligibility.on_trigger(0, self._delay_rng)

    def events_due(self, round_num: int) -> List[Dict[str, Any]]:
        """Scheduled events firing now. Each one triggers fresh reaction delays."""
        if not self.v2:
            return []
        due = due_scheduled_events(self.config, round_num)
        for _ in due:
            self.eligibility.on_trigger(round_num, self._delay_rng)
        return due

    def planned_follows(self) -> List[Tuple[int, int]]:
        if not self.v2:
            return []
        return plan_seed_follows(self.config, self._follow_rng, self.platform)


# --- run settings ------------------------------------------------------------

def resolve_run_settings(
    config: Mapping[str, Any],
    cli_seed: Optional[int] = None,
    cli_max_rounds: Optional[int] = None,
) -> Dict[str, Any]:
    """Merge the ``run`` block of the config with CLI overrides (CLI wins).

    Returns ``seed`` (None when neither source sets one), ``max_rounds``,
    ``replicate_index``, ``ensemble_id``, ``llm_temperature``,
    ``llm_pass_seed``, ``llm_semaphore`` (max concurrent LLM requests per
    platform; None means the default of 30) and ``outcome_questions``.
    """
    run = config.get("run") or {}
    seed = cli_seed if cli_seed is not None else run.get("seed")
    max_rounds = cli_max_rounds if cli_max_rounds else run.get("max_rounds")
    return {
        "seed": int(seed) if seed is not None else None,
        "max_rounds": int(max_rounds) if max_rounds else None,
        "replicate_index": run.get("replicate_index"),
        "ensemble_id": run.get("ensemble_id"),
        "llm_temperature": run.get("llm_temperature"),
        "llm_pass_seed": bool(run.get("llm_pass_seed", False)),
        "llm_semaphore": run.get("llm_semaphore"),
        "llm_concurrency_share": run.get("llm_concurrency_share"),
        "outcome_questions": run.get("outcome_questions") or [],
    }


def llm_model_config(
    run_settings: Optional[Mapping[str, Any]], seed: Optional[int] = None
) -> Dict[str, Any]:
    """The camel ``model_config_dict`` implied by the run settings.

    ``temperature`` is passed when ``run.llm_temperature`` is set. ``seed`` is
    passed only when ``run.llm_pass_seed`` is true: several OpenAI-compatible
    providers reject unknown parameters, and camel-ai 0.2.78's config does not
    list ``seed`` at all, so callers must be ready to retry without it.
    """
    run_settings = run_settings or {}
    model_config: Dict[str, Any] = {}
    temperature = run_settings.get("llm_temperature")
    if temperature is not None:
        try:
            model_config["temperature"] = float(temperature)
        except (TypeError, ValueError):
            pass
    if run_settings.get("llm_pass_seed") and seed is not None:
        model_config["seed"] = int(seed)
    return model_config
