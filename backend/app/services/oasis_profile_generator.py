"""OASIS agent profile generator.

Turn entities held in a Zep graph into the agent profile format the OASIS
simulation platform expects:

1. Enrich each node with a second Zep retrieval pass.
2. Prompt the model for a long, specific persona.
3. Treat individual entities and group or institutional entities differently.
"""

import json
import random
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from ..utils.zep import (
    call_zep_read_with_retry,
    get_zep_client,
    is_retryable_zep_error,
    normalize_zep_search_query,
)
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('sosim.oasis_profile')


def _coerce_to_str(value: Any) -> str:
    """Coerce a value to a plain string.

    Handles dict, list, and other non-string types that may be returned
    by LLM JSON parsing.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ('text', 'value', 'description', 'content', 'summary', 'name'):
            if key in value:
                candidate = _coerce_to_str(value[key])
                if candidate:
                    return candidate
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        str_items = [_coerce_to_str(item) for item in value]
        str_items = [item for item in str_items if item]
        return ', '.join(str_items)
    return str(value)


def _coerce_to_str_list(value: Any) -> List[str]:
    """Coerce a value to a list of strings.

    Handles nested structures that may be returned by LLM JSON parsing.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: List[str] = []
        for item in value:
            if isinstance(item, (list, tuple)):
                result.extend(_coerce_to_str_list(item))
            else:
                text = _coerce_to_str(item)
                if text:
                    result.append(text)
        return result
    text = _coerce_to_str(value)
    return [text] if text else []


@dataclass
class OasisAgentProfile:
    """One OASIS agent profile."""
    # Shared fields
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str

    # Reddit-specific
    karma: int = 1000

    # Twitter-specific
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500

    # Additional persona detail
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)

    # Source entity
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None

    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def __post_init__(self):
        """Normalize structured LLM fields once at the profile boundary."""
        self.bio = _coerce_to_str(self.bio) or self.name
        self.persona = _coerce_to_str(self.persona) or (
            f"{self.name} is a participant in social discussions."
        )
        self.country = _coerce_to_str(self.country) or None
        self.profession = _coerce_to_str(self.profession) or None
        self.gender = _coerce_to_str(self.gender) or None
        self.mbti = _coerce_to_str(self.mbti) or None
        self.interested_topics = _coerce_to_str_list(self.interested_topics)

    def oasis_persona(self) -> str:
        """The persona as OASIS should see it, carrying the language directive.

        OASIS builds each agent's system prompt itself, from `name` and
        `other_info["user_profile"]` -- and its template says nothing about
        language (see oasis/social_platform/config/user.py:to_system_message).
        Every other LLM call in this project appends get_language_instruction()
        to its own system prompt; the simulation runtime is the one path that
        cannot, because the prompt is built inside the library. So the directive
        rides in on the persona, which is the only free-text field of ours that
        reaches the agent.

        Without it the agents' output language is left to the model and to
        whatever language the seed posts happen to be in, and a multilingual
        model drifts to the language of its context.

        Kept out of `persona` itself so the stored profile, the UI and the
        reports show the persona the model actually wrote.
        """
        return f"{self.persona}\n\n{get_language_instruction()}"

    def to_reddit_format(self) -> Dict[str, Any]:
        """Render this profile in the Reddit shape OASIS reads."""
        profile = {
            "user_id": self.user_id,
            # The OASIS library expects 'username', with no underscore.
            "username": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.oasis_persona(),
            "karma": self.karma,
            "created_at": self.created_at,
        }

        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics

        return profile

    def to_twitter_format(self) -> Dict[str, Any]:
        """Render this profile in the Twitter shape OASIS reads."""
        profile = {
            "user_id": self.user_id,
            # The OASIS library expects 'username', with no underscore.
            "username": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.oasis_persona(),
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }

        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.profession:
            profile["profession"] = self.profession
        if self.interested_topics:
            profile["interested_topics"] = self.interested_topics

        return profile

    def to_dict(self) -> Dict[str, Any]:
        """Render every field of this profile as a dictionary."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "created_at": self.created_at,
        }


class OasisProfileGenerator:
    """Turn Zep graph entities into OASIS agent profiles.

    Each profile is built from a second Zep retrieval pass over the entity, so
    the persona carries the entity's real relationships and history rather than
    the node summary alone. Individual entities get a personal persona; groups
    and institutions get a representative account persona.
    """

    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]

    COUNTRIES = [
        "China", "US", "UK", "Japan", "Germany", "France",
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]

    # Entity types that get a personal persona.
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure",
        "expert", "faculty", "official", "journalist", "activist"
    ]

    # Entity types that get a representative account persona.
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo",
        "mediaoutlet", "company", "institution", "group", "community"
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None
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

        # The Zep client is used to retrieve richer context per entity.
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id

        if self.zep_api_key:
            try:
                self.zep_client = get_zep_client(self.zep_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialise the Zep client: {e}")

    def generate_profile_from_entity(
        self,
        entity: EntityNode,
        user_id: int,
        use_llm: bool = True
    ) -> OasisAgentProfile:
        """Build one OASIS agent profile from a Zep entity.

        Args:
            entity: The Zep entity node.
            user_id: The OASIS user ID to assign.
            use_llm: Whether to prompt the model for a detailed persona.

        Returns:
            The generated agent profile.
        """
        entity_type = entity.get_entity_type() or "Entity"

        name = entity.name
        user_name = self._generate_username(name)

        context = self._build_entity_context(entity)

        if use_llm:
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context
            )
        else:
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes
            )

        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{entity_type}: {name}"),
            persona=profile_data.get("persona", entity.summary or f"A {entity_type} named {name}."),
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age"),
            gender=profile_data.get("gender"),
            mbti=profile_data.get("mbti"),
            country=profile_data.get("country"),
            profession=profile_data.get("profession"),
            interested_topics=profile_data.get("interested_topics", []),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )

    def _generate_username(self, name: str) -> str:
        """Derive a lowercase, unique-enough handle from a display name."""
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')

        # A random suffix keeps two entities with the same name apart.
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"

    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """Retrieve richer context for one entity from the Zep graph.

        Zep has no single hybrid-search endpoint, so edges and nodes are
        searched separately and merged. The two requests run in parallel.

        Args:
            entity: The entity node to search around.

        Returns:
            A dictionary of facts, node_summaries and a rendered context block.
        """
        import concurrent.futures

        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}

        entity_name = entity.name

        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }

        # Retrieval is only possible against a specific graph.
        if not self.graph_id:
            logger.debug("Skipping Zep retrieval because no graph_id is set")
            return results

        comprehensive_query = normalize_zep_search_query(
            t('progress.zepSearchQuery', name=entity_name)
        )

        def search_edges():
            """Search edges, which carry the facts and relationships."""
            return call_zep_read_with_retry(
                lambda: self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                ),
                operation_name=f"profile edge search ({entity.uuid})",
            )

        def search_nodes():
            """Search nodes, which carry the entity summaries."""
            return call_zep_read_with_retry(
                lambda: self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                ),
                operation_name=f"profile node search ({entity.uuid})",
            )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)

                # Each request already has the configured HTTP timeout and
                # typed retry budget. A second hard-coded 30s future timeout
                # discarded late successes while the executor still waited.
                edge_result = edge_future.result()
                node_result = node_future.result()

            all_facts = set()
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)

            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"Related entity: {node.name}")
            results["node_summaries"] = list(all_summaries)

            context_parts = []
            if results["facts"]:
                context_parts.append("Facts:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("Related entities:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)

            logger.info(
                f"Retrieved Zep context for {entity_name}: "
                f"{len(results['facts'])} facts, {len(results['node_summaries'])} related nodes"
            )

        except Exception as e:
            logger.warning(f"Failed to retrieve Zep context for {entity_name}: {e}")
            if not is_retryable_zep_error(e):
                raise

        return results

    def _build_entity_context(self, entity: EntityNode) -> str:
        """Assemble the full context block for one entity.

        Combines the entity's own attributes, its edges and related nodes, and
        whatever the Zep retrieval pass adds on top.
        """
        context_parts = []

        # 1. The entity's own attributes.
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### Entity attributes\n" + "\n".join(attrs))

        # 2. Related edges, which carry the facts and relationships.
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")

                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (related entity)")
                    else:
                        relationships.append(f"- (related entity) --[{edge_name}]--> {entity.name}")

            if relationships:
                context_parts.append("### Related facts and relationships\n" + "\n".join(relationships))

        # 3. Related nodes.
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")

                # Drop the default labels, which say nothing about the node.
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""

                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")

            if related_info:
                context_parts.append("### Related entities\n" + "\n".join(related_info))

        # 4. Whatever the Zep retrieval pass adds.
        zep_results = self._search_zep_for_entity(entity)

        if zep_results.get("facts"):
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Facts retrieved from Zep\n" + "\n".join(f"- {f}" for f in new_facts[:15]))

        if zep_results.get("node_summaries"):
            context_parts.append("### Related nodes retrieved from Zep\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))

        return "\n\n".join(context_parts)

    def _is_individual_entity(self, entity_type: str) -> bool:
        """Report whether this entity type represents one person."""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES

    def _is_group_entity(self, entity_type: str) -> bool:
        """Report whether this entity type represents a group or institution."""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES

    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> Dict[str, Any]:
        """Prompt the model for a detailed persona.

        Individual entities get a personal persona; groups and institutions get
        a representative account persona.
        """

        is_individual = self._is_individual_entity(entity_type)

        if is_individual:
            prompt = self._build_individual_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context
            )
        else:
            prompt = self._build_group_persona_prompt(
                entity_name, entity_type, entity_summary, entity_attributes, context
            )

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = create_chat_completion(
                    self.client,
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt(is_individual)},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    # Lower the temperature on every retry.
                    temperature=0.7 - (attempt * 0.1),
                    # No max_tokens: the persona is deliberately long.
                )

                content = extract_chat_completion_text(response)

                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"Model output was truncated (attempt {attempt+1}); repairing it")
                    content = self._fix_truncated_json(content)

                try:
                    result = json.loads(content)

                    # Fill in the two fields the caller cannot do without.
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or f"{entity_name} is a {entity_type}."

                    return result

                except json.JSONDecodeError as je:
                    logger.warning(f"Failed to parse the model's JSON (attempt {attempt+1}): {str(je)[:80]}")

                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result

                    last_error = je

            except Exception as e:
                logger.warning(f"Model call failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                # Back off before retrying.
                time.sleep(1 * (attempt + 1))

        logger.warning(
            f"Failed to generate a persona after {max_attempts} attempts: {last_error}; "
            "falling back to the rule-based persona"
        )
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes
        )

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

    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """Recover as much as possible from malformed model JSON."""
        import re

        # 1. Close anything that was truncated.
        content = self._fix_truncated_json(content)

        # 2. Extract the JSON object from any surrounding prose.
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # 3. Raw newlines inside string values are the most common defect.
            def fix_string_newlines(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s

            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)

            # 4. Try again on the repaired text.
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError:
                # 5. Strip control characters and collapse whitespace.
                try:
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except Exception:
                    pass

        # 6. Salvage the individual fields with a regex.
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        # The persona is the longest field and is the one usually truncated.
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)

        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (entity_summary or f"{entity_name} is a {entity_type}.")

        if bio_match or persona_match:
            logger.info("Salvaged partial fields from malformed model JSON")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }

        # 7. Nothing was recoverable; return the minimum viable profile.
        logger.warning("Failed to repair the model's JSON; returning a minimal profile")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or f"{entity_name} is a {entity_type}."
        }

    def _get_system_prompt(self, is_individual: bool) -> str:
        """Return the system prompt for persona generation."""
        base_prompt = (
            "You are an expert at building social media user personas. Generate "
            "detailed, believable personas for opinion simulation, staying as close "
            "as possible to the real situation described. You must return valid JSON, "
            "and no string value may contain an unescaped newline."
        )
        return f"{base_prompt}\n\n{get_language_instruction()}"

    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build the persona prompt for an individual entity."""

        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "None"
        context_str = context[:3000] if context else "No additional context"

        return f"""Generate a detailed social media persona for this entity, staying as close as possible to the real situation described.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context:
{context_str}

Return JSON with these fields:

1. bio: social media bio, about 200 words
2. persona: a detailed persona description, about 2000 words of plain text, covering:
   - Basic information (age, occupation, education, location)
   - Background (formative experiences, connection to the event, social ties)
   - Personality (MBTI type, core traits, how they express emotion)
   - Social media behaviour (posting frequency, content preferences, interaction style, language habits)
   - Positions and opinions (attitude to the topic, what would anger or move them)
   - Distinctive traits (catchphrases, unusual experiences, personal interests)
   - Personal memories: a key part of the persona. Describe how this individual connects to the event, and what they have already said and done in it.
3. age: age as an integer
4. gender: must be one of the English strings "male" or "female"
5. mbti: MBTI type, for example INTJ or ENFP
6. country: country name in English, for example "China"
7. profession: occupation
8. interested_topics: an array of topics

Requirements:
- Every field value must be a string or a number, with no newline characters
- persona must be one continuous piece of prose
- {get_language_instruction()} (the gender field must still be the English "male" or "female")
- The content must stay consistent with the entity information above
- age must be a valid integer, and gender must be exactly "male" or "female"
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build the persona prompt for a group or institutional entity."""

        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "None"
        context_str = context[:3000] if context else "No additional context"

        return f"""Generate a detailed social media account persona for this organization or group, staying as close as possible to the real situation described.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context:
{context_str}

Return JSON with these fields:

1. bio: official account bio, about 200 words, professional in tone
2. persona: a detailed account description, about 2000 words of plain text, covering:
   - Basic information (formal name, type of organization, founding background, main functions)
   - Account positioning (account type, target audience, core purpose)
   - Voice (language habits, recurring phrasing, topics it avoids)
   - Publishing behaviour (content types, posting frequency, active hours)
   - Positions (official stance on the core topic, how it handles controversy)
   - Notes (the constituency it represents, operational habits)
   - Institutional memories: a key part of the persona. Describe how this organization connects to the event, and what it has already said and done in it.
3. age: always 30, the notional age of an institutional account
4. gender: always the English string "other", which marks the account as non-personal
5. mbti: an MBTI type describing the account's voice, for example ISTJ for rigorous and conservative
6. country: country name in English, for example "China"
7. profession: a description of the organization's function
8. interested_topics: an array of focus areas

Requirements:
- Every field value must be a string or a number, and null is not allowed
- persona must be one continuous piece of prose with no newline characters
- {get_language_instruction()} (the gender field must still be the English "other")
- age must be the integer 30, and gender must be the string "other"
- The account must speak in a way that fits its official role"""

    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a basic persona from rules, with no model call."""

        entity_type_lower = entity_type.lower()

        if entity_type_lower in ["student", "alumni"]:
            return {
                "bio": f"{entity_type} with interests in academics and social issues.",
                "persona": f"{entity_name} is a {entity_type.lower()} who is actively engaged in academic and social discussions. They enjoy sharing perspectives and connecting with peers.",
                "age": random.randint(18, 30),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": "Student",
                "interested_topics": ["Education", "Social Issues", "Technology"],
            }

        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            return {
                "bio": f"Expert and thought leader in their field.",
                "persona": f"{entity_name} is a recognized {entity_type.lower()} who shares insights and opinions on important matters. They are known for their expertise and influence in public discourse.",
                "age": random.randint(35, 60),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(["ENTJ", "INTJ", "ENTP", "INTP"]),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_attributes.get("occupation", "Expert"),
                "interested_topics": ["Politics", "Economics", "Culture & Society"],
            }

        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            return {
                "bio": f"Official account for {entity_name}. News and updates.",
                "persona": f"{entity_name} is a media entity that reports news and facilitates public discourse. The account shares timely updates and engages with the audience on current events.",
                "age": 30,  # Notional age of an institutional account
                "gender": "other",  # Institutional accounts are non-personal
                "mbti": "ISTJ",  # Institutional voice: rigorous and conservative
                "country": "China",
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }

        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters.",
                "age": 30,  # Notional age of an institutional account
                "gender": "other",  # Institutional accounts are non-personal
                "mbti": "ISTJ",  # Institutional voice: rigorous and conservative
                "country": "China",
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }

        else:
            return {
                "bio": entity_summary[:150] if entity_summary else f"{entity_type}: {entity_name}",
                "persona": entity_summary or f"{entity_name} is a {entity_type.lower()} participating in social discussions.",
                "age": random.randint(25, 50),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                "country": random.choice(self.COUNTRIES),
                "profession": entity_type,
                "interested_topics": ["General", "Social Issues"],
            }

    def set_graph_id(self, graph_id: str):
        """Set the graph used for Zep retrieval."""
        self.graph_id = graph_id

    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit"
    ) -> List[OasisAgentProfile]:
        """Generate agent profiles for a list of entities, in parallel.

        Args:
            entities: The entities to build profiles for.
            use_llm: Whether to prompt the model for a detailed persona.
            progress_callback: Called as (current, total, message).
            graph_id: The graph used for Zep retrieval.
            parallel_count: How many profiles to generate at once.
            realtime_output_path: If set, rewrite this file after each profile.
            output_platform: Output format, "reddit" or "twitter".

        Returns:
            The generated agent profiles, in entity order.
        """
        import concurrent.futures
        from threading import Lock

        if graph_id:
            self.graph_id = graph_id

        total = len(entities)
        # Pre-allocated so completions out of order still land in entity order.
        profiles = [None] * total
        # A one-element list so the closures below can mutate the counter.
        completed_count = [0]
        lock = Lock()

        def save_profiles_realtime():
            """Rewrite the output file with every profile finished so far."""
            if not realtime_output_path:
                return

            with lock:
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return

                try:
                    if output_platform == "reddit":
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        with open(realtime_output_path, 'w', encoding='utf-8') as f:
                            json.dump(profiles_data, f, ensure_ascii=False, indent=2)
                    else:
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"Failed to write the profiles file: {e}")

        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """Generate one profile on a worker thread."""
            entity_type = entity.get_entity_type() or "Entity"

            try:
                profile = self.generate_profile_from_entity(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm
                )

                self._print_generated_profile(entity.name, entity_type, profile)

                return idx, profile, None

            except Exception as e:
                logger.error(f"Failed to generate a persona for {entity.name}: {str(e)}")
                fallback_profile = OasisAgentProfile(
                    user_id=idx,
                    user_name=self._generate_username(entity.name),
                    name=entity.name,
                    bio=f"{entity_type}: {entity.name}",
                    persona=entity.summary or "A participant in social discussions.",
                    source_entity_uuid=entity.uuid,
                    source_entity_type=entity_type,
                )
                return idx, fallback_profile, str(e)

        logger.info(f"Generating {total} agent profiles with {parallel_count} workers")
        print(f"\n{'='*60}")
        print(f"Generating agent profiles - {total} entities, {parallel_count} workers")
        print(f"{'='*60}\n")

        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }

            for future in concurrent.futures.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"

                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile

                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]

                    save_profiles_realtime()

                    if progress_callback:
                        progress_callback(
                            current,
                            total,
                            f"Completed {current}/{total}: {entity.name} ({entity_type})"
                        )

                    if error:
                        logger.warning(f"[{current}/{total}] {entity.name} fell back to a basic persona: {error}")
                    else:
                        logger.info(f"[{current}/{total}] Generated a persona for {entity.name} ({entity_type})")

                except Exception as e:
                    logger.error(f"Failed to process entity {entity.name}: {str(e)}")
                    with lock:
                        completed_count[0] += 1
                    profiles[idx] = OasisAgentProfile(
                        user_id=idx,
                        user_name=self._generate_username(entity.name),
                        name=entity.name,
                        bio=f"{entity_type}: {entity.name}",
                        persona=entity.summary or "A participant in social discussions.",
                        source_entity_uuid=entity.uuid,
                        source_entity_type=entity_type,
                    )
                    save_profiles_realtime()

        print(f"\n{'='*60}")
        print(f"Profile generation complete - {len([p for p in profiles if p])} agents")
        print(f"{'='*60}\n")

        return profiles

    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """Print one finished persona to the console, in full."""
        separator = "-" * 70

        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else 'None'

        output_lines = [
            f"\n{separator}",
            t('progress.profileGenerated', name=entity_name, type=entity_type),
            f"{separator}",
            f"Username: {profile.user_name}",
            f"",
            f"[Bio]",
            f"{profile.bio}",
            f"",
            f"[Persona]",
            f"{profile.persona}",
            f"",
            f"[Attributes]",
            f"Age: {profile.age} | Gender: {profile.gender} | MBTI: {profile.mbti}",
            f"Profession: {profile.profession} | Country: {profile.country}",
            f"Interests: {topics_str}",
            separator
        ]

        output = "\n".join(output_lines)

        # Console only. The logger deliberately does not repeat the full text.
        print(output)

    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """Write profiles in the format the target platform requires.

        OASIS reads Twitter profiles from CSV and Reddit profiles from JSON.

        Args:
            profiles: The profiles to write.
            file_path: Destination path.
            platform: Either "reddit" or "twitter".
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)

    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """Write Twitter profiles as the CSV OASIS expects.

        OASIS requires these columns:
        - user_id: the row index, starting at 0
        - name: the agent's real name
        - username: the handle used in the system
        - user_char: the full persona, injected into the agent's system prompt
        - description: the short public bio shown on the profile page

        user_char drives how the agent thinks and acts; description is only
        what other agents see.
        """
        import csv

        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)

            for idx, profile in enumerate(profiles):
                # user_char is the bio and persona together, and it is what OASIS
                # injects into the agent's system prompt -- so it carries the
                # language directive too. See OasisAgentProfile.oasis_persona.
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.oasis_persona()}"
                else:
                    user_char = f"{profile.bio}\n\n{get_language_instruction()}"
                # Newlines would break the CSV row.
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')

                description = profile.bio.replace('\n', ' ').replace('\r', ' ')

                row = [
                    idx,
                    profile.name,
                    profile.user_name,
                    user_char,
                    description
                ]
                writer.writerow(row)

        logger.info(f"Saved {len(profiles)} Twitter profiles to {file_path} as OASIS CSV")

    def _normalize_gender(self, gender: Optional[str]) -> str:
        """Normalize the gender field to the values OASIS accepts.

        OASIS accepts male, female and other. Both persona prompts mandate
        exactly those three strings, so anything else is a model deviation and
        falls back to "other".
        """
        if not gender:
            return "other"

        gender_lower = gender.lower().strip()

        gender_map = {
            "male": "male",
            "female": "female",
            "other": "other",
        }

        return gender_map.get(gender_lower, "other")

    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """Write Reddit profiles as the JSON OASIS expects.

        The shape matches to_reddit_format(). user_id is mandatory: it is what
        OASIS agent_graph.get_agent() matches on, and what initial_posts refer
        to through poster_agent_id.

        Required fields: user_id, username, name, bio, persona, age (integer),
        gender ("male", "female" or "other"), mbti and country.
        """
        data = []
        for idx, profile in enumerate(profiles):
            item = {
                # user_id is what OASIS matches agents on; never omit it.
                "user_id": profile.user_id if profile.user_id is not None else idx,
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150],
                "persona": profile.oasis_persona(),
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # OASIS requires these, so every one carries a default.
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else "China",
            }

            if profile.profession:
                item["profession"] = profile.profession
            if profile.interested_topics:
                item["interested_topics"] = profile.interested_topics

            data.append(item)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(profiles)} Reddit profiles to {file_path} as JSON, with user_id")

    # Retained as an alias for backward compatibility.
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """Deprecated. Use save_profiles() instead."""
        logger.warning("save_profiles_to_json is deprecated; use save_profiles instead")
        self.save_profiles(profiles, file_path, platform)
