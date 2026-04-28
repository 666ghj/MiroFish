"""
Intelligent simulation configuration generator
Uses an LLM to automatically produce a fine-grained simulation parameter set from the
simulation requirement, document content, and graph information. The goal is full
automation, with no manual parameter tweaking.

A step-by-step generation strategy is used to avoid failures caused by producing too
much content in a single call:
1. Generate the time configuration
2. Generate the event configuration
3. Generate agent configurations in batches
4. Generate the platform configurations
"""

import json
import math
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.simulation_config')

# China daily-schedule configuration (Beijing time)
CHINA_TIMEZONE_CONFIG = {
    # Late-night window (almost no activity)
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # Morning window (people gradually wake up)
    "morning_hours": [6, 7, 8],
    # Working hours
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # Evening peak (most active)
    "peak_hours": [19, 20, 21, 22],
    # Late-evening window (activity declines)
    "night_hours": [23],
    # Activity multipliers
    "activity_multipliers": {
        "dead": 0.05,      # Almost nobody around in the small hours
        "morning": 0.4,    # Activity ramps up in the morning
        "work": 0.7,       # Moderate during working hours
        "peak": 1.5,       # Evening peak
        "night": 0.5       # Declines late at night
    }
}


@dataclass
class AgentActivityConfig:
    """Activity configuration for a single agent"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str

    # Activity-level configuration (0.0-1.0)
    activity_level: float = 0.5  # Overall activity level

    # Posting frequency (expected posts per hour)
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0

    # Active hours (24-hour clock, 0-23)
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))

    # Response speed (delay reacting to hot events, in simulated minutes)
    response_delay_min: int = 5
    response_delay_max: int = 60

    # Sentiment bias (-1.0 to 1.0, negative to positive)
    sentiment_bias: float = 0.0

    # Stance (attitude toward a specific topic)
    stance: str = "neutral"  # supportive, opposing, neutral, observer

    # Influence weight (probability that this agent's posts are seen by other agents)
    influence_weight: float = 1.0


@dataclass
class TimeSimulationConfig:
    """Time-simulation configuration (based on Chinese daily-schedule habits)"""
    # Total simulated duration (in simulated hours)
    total_simulation_hours: int = 72  # Defaults to 72 simulated hours (3 days)

    # Time represented per round (simulated minutes) - default 60 minutes (1 hour) for faster time progression
    minutes_per_round: int = 60

    # Range of agents activated per hour
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20

    # Peak hours (19:00-22:00 evening, the most active time for Chinese users)
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5

    # Off-peak hours (00:00-05:00, almost no activity)
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # Activity is extremely low overnight

    # Morning window
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4

    # Working hours
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """Event configuration"""
    # Initial events (triggers fired when the simulation starts)
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)

    # Scheduled events (events triggered at specific times)
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)

    # Hot-topic keywords
    hot_topics: List[str] = field(default_factory=list)

    # Narrative steering direction
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """Platform-specific configuration"""
    platform: str  # twitter or reddit

    # Recommendation algorithm weights
    recency_weight: float = 0.4  # Time recency
    popularity_weight: float = 0.3  # Popularity
    relevance_weight: float = 0.3  # Relevance

    # Viral spread threshold (number of interactions required to trigger diffusion)
    viral_threshold: int = 10

    # Echo-chamber strength (how strongly similar opinions cluster)
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """Complete simulation parameter configuration"""
    # Basic info
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str

    # Time configuration
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)

    # List of agent configurations
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)

    # Event configuration
    event_config: EventConfig = field(default_factory=EventConfig)

    # Platform configurations
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None

    # LLM configuration
    llm_model: str = ""
    llm_base_url: str = ""

    # Generation metadata
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # The LLM's reasoning notes

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict"""
        time_dict = asdict(self.time_config)
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to a JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    Intelligent simulation configuration generator

    Uses an LLM to analyze the simulation requirement, document content, and graph
    entity information, and automatically produce an optimal simulation parameter set.

    Step-by-step generation strategy:
    1. Generate the time configuration and event configuration (lightweight)
    2. Generate agent configurations in batches (10-20 per batch)
    3. Generate the platform configurations
    """

    # Maximum context character count
    MAX_CONTEXT_LENGTH = 50000
    # Number of agents generated per batch
    AGENTS_PER_BATCH = 15

    # Per-step context truncation lengths (character counts)
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # Time configuration
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # Event configuration
    ENTITY_SUMMARY_LENGTH = 300          # Entity summary
    AGENT_SUMMARY_LENGTH = 300           # Entity summary inside agent configuration
    ENTITIES_PER_TYPE_DISPLAY = 20       # Number of entities displayed per type

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY is not configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> SimulationParameters:
        """
        Intelligently generate the full simulation configuration (step by step).

        Args:
            simulation_id: Simulation ID
            project_id: Project ID
            graph_id: Graph ID
            simulation_requirement: Simulation requirement description
            document_text: Original document content
            entities: Filtered entity list
            enable_twitter: Whether to enable Twitter
            enable_reddit: Whether to enable Reddit
            progress_callback: Progress callback function (current_step, total_steps, message)

        Returns:
            SimulationParameters: complete simulation parameters
        """
        logger.info(f"Starting intelligent simulation configuration generation: simulation_id={simulation_id}, entity count={len(entities)}")

        # Compute the total number of steps
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # Time config + event config + N agent batches + platform config
        current_step = 0

        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")

        # 1. Build the basic context
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )

        reasoning_parts = []

        # ========== Step 1: Generate time configuration ==========
        report_progress(1, t('progress.generatingTimeConfig'))
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"{t('progress.timeConfigLabel')}: {time_config_result.get('reasoning', t('common.success'))}")

        # ========== Step 2: Generate event configuration ==========
        report_progress(2, t('progress.generatingEventConfig'))
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"{t('progress.eventConfigLabel')}: {event_config_result.get('reasoning', t('common.success'))}")

        # ========== Steps 3-N: Generate agent configurations in batches ==========
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]

            report_progress(
                3 + batch_idx,
                t('progress.generatingAgentConfig', start=start_idx + 1, end=end_idx, total=len(entities))
            )

            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement
            )
            all_agent_configs.extend(batch_configs)

        reasoning_parts.append(t('progress.agentConfigResult', count=len(all_agent_configs)))

        # ========== Assign poster agents to initial posts ==========
        logger.info("Assigning suitable poster agents to initial posts...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(t('progress.postAssignResult', count=assigned_count))

        # ========== Final step: Generate platform configurations ==========
        report_progress(total_steps, t('progress.generatingPlatformConfig'))
        twitter_config = None
        reddit_config = None

        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )

        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )

        # Build the final parameters
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )

        logger.info(f"Simulation configuration generation complete: {len(params.agent_configs)} agent configurations")

        return params

    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Build the LLM context, truncating to the maximum length"""

        # Entity summary
        entity_summary = self._summarize_entities(entities)

        # Build the context
        context_parts = [
            f"## Simulation Requirement\n{simulation_requirement}",
            f"\n## Entity Information ({len(entities)} entities)\n{entity_summary}",
        ]

        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # Leave a 500-character margin

        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(document truncated)"
            context_parts.append(f"\n## Original Document Content\n{doc_text}")

        return "\n".join(context_parts)

    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """Generate the entity summary"""
        lines = []

        # Group by type
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)

        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)} entities)")
            # Use the configured display count and summary length
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... and {len(type_entities) - display_count} more")

        return "\n".join(lines)

    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """LLM call with retry, including JSON-repair logic"""
        import re

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # Lower the temperature on each retry
                    # Do not set max_tokens; let the LLM produce as much as needed
                )

                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                # Check whether the output was truncated
                if finish_reason == 'length':
                    logger.warning(f"LLM output was truncated (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)

                # Try to parse the JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parsing failed (attempt {attempt+1}): {str(e)[:80]}")

                    # Try to repair the JSON
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed

                    last_error = e

            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))

        raise last_error or Exception("LLM call failed")

    def _fix_truncated_json(self, content: str) -> str:
        """Repair truncated JSON"""
        content = content.strip()

        # Count unclosed braces and brackets
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # Check for an unclosed string
        if content and content[-1] not in '",}]':
            content += '"'

        # Close brackets and braces
        content += ']' * open_brackets
        content += '}' * open_braces

        return content

    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Try to repair the configuration JSON"""
        import re

        # Repair the truncation case first
        content = self._fix_truncated_json(content)

        # Extract the JSON portion
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # Remove newline characters inside strings
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s

            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)

            try:
                return json.loads(json_str)
            except:
                # Try removing all control characters
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass

        return None

    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Generate the time configuration"""
        # Use the configured context truncation length
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]

        # Compute the maximum allowed value (90% of the agent count)
        max_agents_allowed = max(1, int(num_entities * 0.9))

        prompt = f"""Based on the following simulation requirement, generate a time-simulation configuration.

{context_truncated}

## Task
Produce the time configuration as JSON.

### Basic principles (for reference only; adjust flexibly based on the specific event and the participating audience):
- Infer the target user group's timezone and daily schedule from the simulation scenario; the example below uses UTC+8 as a reference
- Almost no activity between 00:00 and 05:00 (activity multiplier 0.05)
- Activity gradually picks up between 06:00 and 08:00 (activity multiplier 0.4)
- Moderate activity during working hours 09:00-18:00 (activity multiplier 0.7)
- Evening peak between 19:00 and 22:00 (activity multiplier 1.5)
- Activity declines after 23:00 (activity multiplier 0.5)
- General pattern: low activity overnight, ramp-up in the morning, moderate during working hours, peak in the evening
- **Important**: the example values below are references only; tailor each window to the nature of the event and the audience
  - For example: a student audience may peak between 21:00 and 23:00; media accounts are active all day; official institutions are active only during working hours
  - For example: a breaking news event may produce late-night discussion, so off_peak_hours can be shortened accordingly

### Return JSON format (no markdown)

Example:
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "morning_hours": [6, 7, 8],
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    "reasoning": "Explanation of the time configuration for this event"
}}

Field descriptions:
- total_simulation_hours (int): total simulated duration, 24-168 hours; short for breaking events, long for ongoing topics
- minutes_per_round (int): minutes per round, 30-120; 60 minutes is recommended
- agents_per_hour_min (int): minimum number of agents activated per hour (range: 1-{max_agents_allowed})
- agents_per_hour_max (int): maximum number of agents activated per hour (range: 1-{max_agents_allowed})
- peak_hours (int array): peak hours, adjusted for the event's audience
- off_peak_hours (int array): off-peak hours, typically late-night/early-morning
- morning_hours (int array): morning hours
- work_hours (int array): working hours
- reasoning (string): brief explanation of why this configuration was chosen"""

        system_prompt = "You are a social-media simulation expert. Return pure JSON; the time configuration must match the daily schedule of the target user group in the simulation scenario."
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"LLM time-config generation failed: {e}; using default configuration")
            return self._get_default_time_config(num_entities)

    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Get the default time configuration (Chinese daily schedule)"""
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # One hour per round to speed up time progression
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Using the default Chinese daily-schedule configuration (1 hour per round)"
        }

    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Parse the time-config result and verify that agents_per_hour values do not exceed the total agent count"""
        # Get the raw values
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))

        # Validate and correct: ensure they do not exceed the total agent count
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) exceeds total agent count ({num_entities}); corrected")
            agents_per_hour_min = max(1, num_entities // 10)

        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) exceeds total agent count ({num_entities}); corrected")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)

        # Make sure min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max; corrected to {agents_per_hour_min}")

        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),  # Default to 1 hour per round
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,  # Almost nobody around overnight
            morning_hours=result.get("morning_hours", [6, 7, 8]),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(range(9, 19))),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )

    def _generate_event_config(
        self,
        context: str,
        simulation_requirement: str,
        entities: List[EntityNode]
    ) -> Dict[str, Any]:
        """Generate the event configuration"""

        # Get the list of available entity types for the LLM to reference
        entity_types_available = list(set(
            e.get_entity_type() or "Unknown" for e in entities
        ))

        # List representative entity names for each type
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)

        type_info = "\n".join([
            f"- {t}: {', '.join(examples)}"
            for t, examples in type_examples.items()
        ])

        # Use the configured context truncation length
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]

        prompt = f"""Based on the following simulation requirement, generate the event configuration.

Simulation requirement: {simulation_requirement}

{context_truncated}

## Available entity types and examples
{type_info}

## Task
Produce the event configuration as JSON:
- Extract hot-topic keywords
- Describe the direction in which the discourse will develop
- Design the initial posts; **each post must specify poster_type (the publisher's type)**

**Important**: poster_type MUST be chosen from the "available entity types" listed above so that initial posts can be assigned to a suitable agent.
For example, official statements should be posted by Official/University types, news by MediaOutlet, and student opinions by Student.

Return JSON format (no markdown):
{{
    "hot_topics": ["keyword 1", "keyword 2", ...],
    "narrative_direction": "<description of how the discourse will develop>",
    "initial_posts": [
        {{"content": "post content", "poster_type": "entity type (must come from the available types)"}},
        ...
    ],
    "reasoning": "<brief explanation>"
}}"""

        system_prompt = "You are an expert in public-opinion analysis. Return pure JSON. Note that poster_type must precisely match an available entity type."
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'poster_type' field value MUST be in English PascalCase exactly matching the available entity types. Only 'content', 'narrative_direction', 'hot_topics' and 'reasoning' fields should use the specified language."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"LLM event-config generation failed: {e}; using default configuration")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "Using the default configuration"
            }

    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Parse the event-config result"""
        return EventConfig(
            initial_posts=result.get("initial_posts", []),
            scheduled_events=[],
            hot_topics=result.get("hot_topics", []),
            narrative_direction=result.get("narrative_direction", "")
        )

    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        Assign suitable poster agents to initial posts.

        Matches each post's poster_type against the most suitable agent_id.
        """
        if not event_config.initial_posts:
            return event_config

        # Build an agent index by entity type
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)

        # Type alias mapping (handles different formats the LLM may emit)
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }

        # Track the next-agent index used per type to avoid reusing the same agent
        used_indices: Dict[str, int] = {}

        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")

            # Try to find a matching agent
            matched_agent_id = None

            # 1. Direct match
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Match via aliases
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break

            # 3. If no match was found, use the agent with the highest influence
            if matched_agent_id is None:
                logger.warning(f"No matching agent found for type '{poster_type}'; using the highest-influence agent")
                if agent_configs:
                    # Sort by influence and pick the highest
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0

            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })

            logger.info(f"Initial post assigned: poster_type='{poster_type}' -> agent_id={matched_agent_id}")

        event_config.initial_posts = updated_posts
        return event_config

    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """Generate agent configurations in batches"""

        # Build the entity info (use the configured summary length)
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })

        prompt = f"""Based on the following information, generate a social-media activity configuration for each entity.

Simulation requirement: {simulation_requirement}

## Entity list
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Task
Generate an activity configuration for each entity. Note the following:
- **Times must match the target user group's daily schedule**: the example below uses UTC+8; adjust based on the simulation scenario
- **Official institutions** (University/GovernmentAgency): low activity (0.1-0.3), active during working hours (9-17), slow response (60-240 minutes), high influence (2.5-3.0)
- **Media** (MediaOutlet): moderate activity (0.4-0.6), active all day (8-23), fast response (5-30 minutes), high influence (2.0-2.5)
- **Individuals** (Student/Person/Alumni): high activity (0.6-0.9), mostly active in the evening (18-23), fast response (1-15 minutes), low influence (0.8-1.2)
- **Public figures/experts**: moderate activity (0.4-0.6), medium-to-high influence (1.5-2.0)

Return JSON format (no markdown):
{{
    "agent_configs": [
        {{
            "agent_id": <must match the input>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <posting frequency>,
            "comments_per_hour": <commenting frequency>,
            "active_hours": [<list of active hours, taking the target audience's daily schedule into account>],
            "response_delay_min": <minimum response delay in minutes>,
            "response_delay_max": <maximum response delay in minutes>,
            "sentiment_bias": <-1.0 to 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <influence weight>
        }},
        ...
    ]
}}"""

        system_prompt = "You are an expert in social-media behavior analysis. Return pure JSON; configurations must match the daily schedule of the target user group in the simulation scenario."
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'stance' field value MUST be one of the English strings: 'supportive', 'opposing', 'neutral', 'observer'. All JSON field names and numeric values must remain unchanged. Only natural language text fields should use the specified language."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"LLM agent-config batch generation failed: {e}; falling back to rule-based generation")
            llm_configs = {}

        # Build AgentActivityConfig objects
        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})

            # If the LLM did not produce a config, fall back to rule-based generation
            if not cfg:
                cfg = self._generate_agent_config_by_rule(entity)

            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=entity.name,
                entity_type=entity.get_entity_type() or "Unknown",
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0)
            )
            configs.append(config)

        return configs

    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """Rule-based generation of a single agent configuration (Chinese daily schedule)"""
        entity_type = (entity.get_entity_type() or "Unknown").lower()

        if entity_type in ["university", "governmentagency", "ngo"]:
            # Official institutions: active during working hours, low frequency, high influence
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Media: active all day, moderate frequency, high influence
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Experts/professors: active during working hours and evenings, moderate frequency
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Students: mostly active in the evening, high frequency
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Late morning + evening
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Alumni: mostly active in the evening
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # Lunch break + evening
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Generic individual: evening peak
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # Daytime + evening
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }

