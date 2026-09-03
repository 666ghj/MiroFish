"""Simulation configuration generator.

Derive the full set of simulation parameters from the simulation requirement,
the source documents and the knowledge graph, so no parameter has to be set by
hand.

Generation is stepwise, because one long response fails far more often:
1. Time configuration
2. Event configuration
3. Agent configuration, in batches
4. Platform configuration
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
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('sosim.simulation_config')


@dataclass
class AgentActivityConfig:
    """How one agent behaves over the simulated day."""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # Overall activity, 0.0 to 1.0
    activity_level: float = 0.5

    # Expected posts and comments per simulated hour
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0

    # Hours of the day this agent is active, 0 to 23
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))

    # Reaction delay to a trending event, in simulated minutes
    response_delay_min: int = 5
    response_delay_max: int = 60

    # Sentiment leaning, -1.0 negative to 1.0 positive
    sentiment_bias: float = 0.0

    # Position on the topic: supportive, opposing, neutral or observer
    stance: str = "neutral"

    # How likely this agent's posts are to be seen by others
    influence_weight: float = 1.0


@dataclass
class TimeSimulationConfig:
    """The simulated clock and the daily rhythm laid over it.

    The defaults describe a UTC+8 audience; the model is asked to adjust them
    to whatever audience the scenario actually implies.
    """
    # Total simulated span, in hours. Three days by default.
    total_simulation_hours: int = 72

    # Simulated minutes per round. One hour keeps the clock moving quickly.
    minutes_per_round: int = 60

    # How many agents may be activated in one simulated hour
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20

    # Evening peak, the busiest part of the day
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5

    # Small hours, when almost nobody is posting
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05

    # Morning, as the audience wakes up
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4

    # Working hours
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """The events that drive the simulation."""
    # Posts that exist when the simulation starts
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)

    # Events injected at a specific simulated time
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)

    # Trending topic keywords
    hot_topics: List[str] = field(default_factory=list)

    # How the narrative is expected to develop
    narrative_direction: str = ""


@dataclass
class PlatformConfig:
    """Per-platform feed behaviour."""
    platform: str  # twitter or reddit

    # Recommendation weights
    recency_weight: float = 0.4
    popularity_weight: float = 0.3
    relevance_weight: float = 0.3

    # Interactions needed before a post starts spreading widely
    viral_threshold: int = 10

    # How strongly similar opinions cluster together
    echo_chamber_strength: float = 0.5


@dataclass
class SimulationParameters:
    """Every parameter one simulation run needs."""
    # Identity
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str

    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)

    agent_configs: List[AgentActivityConfig] = field(default_factory=list)

    event_config: EventConfig = field(default_factory=EventConfig)

    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None

    llm_model: str = ""
    llm_base_url: str = ""

    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # The model's own explanation of the choices it made
    generation_reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Render every parameter as a dictionary."""
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
        """Render every parameter as a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """Derive simulation parameters from the requirement, documents and graph.

    Generation is stepwise, because one long response fails far more often:
    the lightweight time and event configurations first, then the agent
    configurations in batches of 10 to 20, then the platform configuration.
    """

    # Longest context handed to the model, in characters
    MAX_CONTEXT_LENGTH = 50000
    # Agents configured per model call
    AGENTS_PER_BATCH = 15

    # Per-step context budgets, in characters
    TIME_CONFIG_CONTEXT_LENGTH = 10000
    EVENT_CONFIG_CONTEXT_LENGTH = 8000
    ENTITY_SUMMARY_LENGTH = 300
    AGENT_SUMMARY_LENGTH = 300
    ENTITIES_PER_TYPE_DISPLAY = 20
    
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
            raise ValueError("LLM_API_KEY is not configured.")
        
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
        """Generate the full simulation configuration, one step at a time.

        Args:
            simulation_id: The simulation being configured.
            project_id: The owning project.
            graph_id: The knowledge graph backing the simulation.
            simulation_requirement: What the simulation needs to model.
            document_text: The source document text.
            entities: The filtered entity list.
            enable_twitter: Whether to configure the Twitter platform.
            enable_reddit: Whether to configure the Reddit platform.
            progress_callback: Called as (current_step, total_steps, message).

        Returns:
            The complete simulation parameters.
        """
        logger.info(
            f"Generating the simulation config for {simulation_id} "
            f"from {len(entities)} entities"
        )

        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        # Time config, event config, N agent batches, platform config.
        total_steps = 3 + num_batches
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities
        )
        
        reasoning_parts = []
        
        # Step 1: time configuration.
        report_progress(1, t('progress.generatingTimeConfig'))
        num_entities = len(entities)
        time_config_result = self._generate_time_config(context, num_entities)
        time_config = self._parse_time_config(time_config_result, num_entities)
        reasoning_parts.append(f"{t('progress.timeConfigLabel')}: {time_config_result.get('reasoning', t('common.success'))}")
        
        # Step 2: event configuration.
        report_progress(2, t('progress.generatingEventConfig'))
        event_config_result = self._generate_event_config(context, simulation_requirement, entities)
        event_config = self._parse_event_config(event_config_result)
        reasoning_parts.append(f"{t('progress.eventConfigLabel')}: {event_config_result.get('reasoning', t('common.success'))}")
        
        # Steps 3 to N: agent configuration, one batch at a time.
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
        
        logger.info("Assigning a poster agent to each initial post")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(t('progress.postAssignResult', count=assigned_count))
        
        # Final step: platform configuration.
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
        
        logger.info(f"Generated the simulation config with {len(params.agent_configs)} agent configs")
        
        return params
    
    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode]
    ) -> str:
        """Build the shared model context, truncated to the budget."""

        entity_summary = self._summarize_entities(entities)

        context_parts = [
            f"## Simulation requirement\n{simulation_requirement}",
            f"\n## Entities ({len(entities)})\n{entity_summary}",
        ]

        current_length = sum(len(p) for p in context_parts)
        # Leave 500 characters of headroom for the section header below.
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500

        if remaining_length > 0 and document_text:
            doc_text = document_text[:remaining_length]
            if len(document_text) > remaining_length:
                doc_text += "\n...(document truncated)"
            context_parts.append(f"\n## Source document\n{doc_text}")

        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """Summarize the entities, grouped by type."""
        lines = []

        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append(e)

        for entity_type, type_entities in by_type.items():
            lines.append(f"\n### {entity_type} ({len(type_entities)})")
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                summary_preview = (e.summary[:summary_len] + "...") if len(e.summary) > summary_len else e.summary
                lines.append(f"- {e.name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... and {len(type_entities) - display_count} more")

        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """Call the model, retrying and repairing malformed JSON."""
        import re
        
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                response = create_chat_completion(
                    self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    # Lower the temperature on every retry.
                    temperature=0.7 - (attempt * 0.1),
                    # No max_tokens: the configuration is deliberately long.
                )
                
                content = extract_chat_completion_text(response)
                finish_reason = response.choices[0].finish_reason
                
                if finish_reason == 'length':
                    logger.warning(f"Model output was truncated (attempt {attempt+1})")
                    content = self._fix_truncated_json(content)

                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse the model's JSON (attempt {attempt+1}): {str(e)[:80]}")

                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed
                    
                    last_error = e
                    
            except Exception as e:
                logger.warning(f"Model call failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))

        raise last_error or RuntimeError("The model call failed.")
    
    def _fix_truncated_json(self, content: str) -> str:
        """Close a JSON document the model stopped emitting part-way through."""
        content = content.strip()

        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # A last character that cannot end a value means the string itself was
        # cut off, so close the quote before closing the brackets.
        if content and content[-1] not in '",}]':
            content += '"'

        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Recover as much as possible from malformed model JSON."""
        import re

        content = self._fix_truncated_json(content)

        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # Raw newlines inside string values are the most common defect.
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except Exception:
                # Strip control characters and collapse whitespace.
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except Exception:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """Generate the time configuration."""
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]

        # Never activate every agent in a single hour.
        max_agents_allowed = max(1, int(num_entities * 0.9))

        prompt = f"""Generate the time configuration for this simulation.

{context_truncated}

## Task
Return the time configuration as JSON.

### Guidance, to adapt to the event and the audience rather than copy verbatim:
- Infer the target audience's time zone and daily rhythm from the scenario. The figures below are a UTC+8 example.
- 00:00 to 05:00, almost nobody is posting (activity multiplier 0.05)
- 06:00 to 08:00, the audience wakes up (activity multiplier 0.4)
- 09:00 to 18:00, working hours, moderate activity (activity multiplier 0.7)
- 19:00 to 22:00, the evening peak (activity multiplier 1.5)
- After 23:00, activity falls away (activity multiplier 0.5)
- The general shape: quiet overnight, rising through the morning, moderate at work, peaking in the evening
- **Important**: adjust the specific hours to the nature of the event and the people involved
  - A student audience may peak from 21:00 to 23:00; media are active all day; official bodies only during working hours
  - A breaking story can carry discussion into the night, so off_peak_hours may need to be shorter

### Return JSON, with no markdown

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
    "reasoning": "Why this timing suits this event"
}}

Fields:
- total_simulation_hours (int): total simulated span, 24 to 168 hours. Breaking events are short, sustained topics are long.
- minutes_per_round (int): simulated minutes per round, 30 to 120. Prefer 60.
- agents_per_hour_min (int): fewest agents activated per hour, from 1 to {max_agents_allowed}
- agents_per_hour_max (int): most agents activated per hour, from 1 to {max_agents_allowed}
- peak_hours (array of int): the busiest hours, adjusted to the audience
- off_peak_hours (array of int): the quietest hours, usually overnight
- morning_hours (array of int): the morning window
- work_hours (array of int): the working window
- reasoning (string): a brief explanation of these choices"""

        system_prompt = (
            "You are an expert in social media simulation. Return pure JSON. "
            "The time configuration must match the daily rhythm of the audience "
            "the scenario implies."
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Failed to generate the time config: {e}; using the defaults")
            return self._get_default_time_config(num_entities)

    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """Return the default time configuration, on a UTC+8 daily rhythm."""
        return {
            "total_simulation_hours": 72,
            # One simulated hour per round keeps the clock moving quickly.
            "minutes_per_round": 60,
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": [19, 20, 21, 22],
            "off_peak_hours": [0, 1, 2, 3, 4, 5],
            "morning_hours": [6, 7, 8],
            "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "reasoning": "Default UTC+8 daily rhythm, one simulated hour per round"
        }
    
    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """Parse the time configuration, clamping agents_per_hour to the agent count."""
        agents_per_hour_min = result.get("agents_per_hour_min", max(1, num_entities // 15))
        agents_per_hour_max = result.get("agents_per_hour_max", max(5, num_entities // 5))

        if agents_per_hour_min > num_entities:
            logger.warning(
                f"Corrected agents_per_hour_min ({agents_per_hour_min}), "
                f"which exceeded the {num_entities} available agents"
            )
            agents_per_hour_min = max(1, num_entities // 10)

        if agents_per_hour_max > num_entities:
            logger.warning(
                f"Corrected agents_per_hour_max ({agents_per_hour_max}), "
                f"which exceeded the {num_entities} available agents"
            )
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)

        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(
                f"Corrected agents_per_hour_min to {agents_per_hour_min}, "
                "which was not below agents_per_hour_max"
            )

        return TimeSimulationConfig(
            total_simulation_hours=result.get("total_simulation_hours", 72),
            minutes_per_round=result.get("minutes_per_round", 60),
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", [19, 20, 21, 22]),
            off_peak_hours=result.get("off_peak_hours", [0, 1, 2, 3, 4, 5]),
            off_peak_activity_multiplier=0.05,
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
        """Generate the event configuration."""

        # List a few representative entities per type, so the model can pick a
        # poster_type that actually exists in this graph.
        type_examples = {}
        for e in entities:
            etype = e.get_entity_type() or "Unknown"
            if etype not in type_examples:
                type_examples[etype] = []
            if len(type_examples[etype]) < 3:
                type_examples[etype].append(e.name)

        type_info = "\n".join([
            f"- {etype}: {', '.join(examples)}"
            for etype, examples in type_examples.items()
        ])

        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]

        prompt = f"""Generate the event configuration for this simulation.

Simulation requirement: {simulation_requirement}

{context_truncated}

## Available entity types, with examples
{type_info}

## Task
Return the event configuration as JSON:
- Extract the trending topic keywords
- Describe how the narrative is expected to develop
- Write the initial posts. **Every post must name a poster_type.**

**Important**: poster_type must come from the available entity types above, so each initial post can be assigned to a suitable agent.
For example, an official statement should come from Official or University, news from MediaOutlet, and a student's view from Student.

Return JSON, with no markdown:
{{
    "hot_topics": ["keyword 1", "keyword 2", ...],
    "narrative_direction": "<how the narrative is expected to develop>",
    "initial_posts": [
        {{"content": "post text", "poster_type": "entity type, chosen from the available types"}},
        ...
    ],
    "reasoning": "<a brief explanation>"
}}"""

        system_prompt = (
            "You are an expert in public opinion analysis. Return pure JSON. "
            "poster_type must exactly match one of the available entity types."
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'poster_type' field value MUST be in English PascalCase exactly matching the available entity types. Only 'content', 'narrative_direction', 'hot_topics' and 'reasoning' fields should use the specified language."

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"Failed to generate the event config: {e}; using the defaults")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "Default event config"
            }

    def _parse_event_config(self, result: Dict[str, Any]) -> EventConfig:
        """Parse the event configuration."""
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
        """Assign a poster agent to each initial post.

        Each post's poster_type is matched to the most suitable agent_id.
        """
        if not event_config.initial_posts:
            return event_config

        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # The model does not always name the type exactly as the graph does.
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
        
        # Round-robin through each type, so one agent does not post everything.
        used_indices: Dict[str, int] = {}
        
        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")
            
            matched_agent_id = None

            # 1. Exact match.
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            else:
                # 2. Alias match.
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
            
            # 3. Fall back to the most influential agent.
            if matched_agent_id is None:
                logger.warning(
                    f"No agent matches poster type '{poster_type}'; "
                    "using the most influential agent instead"
                )
                if agent_configs:
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0
            
            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            })
            
            logger.info(f"Assigned initial post with poster_type '{poster_type}' to agent {matched_agent_id}")
        
        event_config.initial_posts = updated_posts
        return event_config
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str
    ) -> List[AgentActivityConfig]:
        """Generate the agent configurations for one batch of entities."""

        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        for i, e in enumerate(entities):
            entity_list.append({
                "agent_id": start_idx + i,
                "entity_name": e.name,
                "entity_type": e.get_entity_type() or "Unknown",
                "summary": e.summary[:summary_len] if e.summary else ""
            })
        
        prompt = f"""Generate a social media activity configuration for each of these entities.

Simulation requirement: {simulation_requirement}

## Entities
```json
{json.dumps(entity_list, ensure_ascii=False, indent=2)}
```

## Task
Configure every entity, keeping in mind:
- **The hours must match the audience's daily rhythm.** The figures below are a UTC+8 example; adjust them to the scenario.
- **Official bodies** (University, GovernmentAgency): low activity (0.1 to 0.3), working hours (9 to 17), slow to respond (60 to 240 minutes), high influence (2.5 to 3.0)
- **Media** (MediaOutlet): moderate activity (0.4 to 0.6), active all day (8 to 23), quick to respond (5 to 30 minutes), high influence (2.0 to 2.5)
- **Individuals** (Student, Person, Alumni): high activity (0.6 to 0.9), mostly in the evening (18 to 23), quick to respond (1 to 15 minutes), low influence (0.8 to 1.2)
- **Public figures and experts**: moderate activity (0.4 to 0.6), fairly high influence (1.5 to 2.0)

Return JSON, with no markdown:
{{
    "agent_configs": [
        {{
            "agent_id": <must match the input>,
            "activity_level": <0.0 to 1.0>,
            "posts_per_hour": <posts per simulated hour>,
            "comments_per_hour": <comments per simulated hour>,
            "active_hours": [<hours of the day, matching the audience's rhythm>],
            "response_delay_min": <minimum response delay, in minutes>,
            "response_delay_max": <maximum response delay, in minutes>,
            "sentiment_bias": <-1.0 to 1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <influence weight>
        }},
        ...
    ]
}}"""

        system_prompt = (
            "You are an expert in social media behaviour analysis. Return pure "
            "JSON. The configuration must match the daily rhythm of the audience "
            "the scenario implies."
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}\nIMPORTANT: The 'stance' field value MUST be one of the English strings: 'supportive', 'opposing', 'neutral', 'observer'. All JSON field names and numeric values must remain unchanged. Only natural language text fields should use the specified language."

        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
            llm_configs = {cfg["agent_id"]: cfg for cfg in result.get("agent_configs", [])}
        except Exception as e:
            logger.warning(f"Failed to generate an agent config batch: {e}; using the rule-based config")
            llm_configs = {}

        configs = []
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            cfg = llm_configs.get(agent_id, {})

            # Fall back to rules for any agent the model skipped.
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
        """Build one agent configuration from rules, on a UTC+8 daily rhythm."""
        entity_type = (entity.get_entity_type() or "Unknown").lower()

        if entity_type in ["university", "governmentagency", "ngo"]:
            # Official bodies: working hours, low frequency, high influence.
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0
            }
        elif entity_type in ["mediaoutlet"]:
            # Media: active all day, moderate frequency, high influence.
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5
            }
        elif entity_type in ["professor", "expert", "official"]:
            # Experts: working hours plus the evening, moderate frequency.
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0
            }
        elif entity_type in ["student"]:
            # Students: mostly evenings, high frequency.
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8
            }
        elif entity_type in ["alumni"]:
            # Alumni: the lunch break and the evening.
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
        else:
            # Everyone else: daytime, peaking in the evening.
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0
            }
    

