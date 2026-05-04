"""
OASIS Agent Profile Generator
Converts entities from the Zep knowledge graph into Agent Profile format
required by the OASIS simulation platform.

Improvements:
1. Calls Zep retrieval to enrich node information
2. Optimised prompts to generate very detailed personas
3. Distinguishes between individual entities and abstract group entities
"""

import json
import random
import re
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, get_locale, set_locale, t
from ..utils.llm_client import parse_azure_url
from .zep_entity_reader import EntityNode, ZepEntityReader

logger = get_logger('mirofish.oasis_profile')


def _normalize_topics(value) -> List[str]:
    """Ensure interested_topics is always List[str], even if the LLM returns a delimited string or a list with a single packed element."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.extend(part.strip() for part in re.split(r'[,;|\n]+', item) if part.strip())
    return result


@dataclass
class OasisAgentProfile:
    """OASIS Agent Profile data structure"""
    # Common fields
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str

    # Optional fields - Reddit style
    karma: int = 1000

    # Optional fields - Twitter style
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500

    # Additional persona information
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)

    # Source entity information
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    def to_reddit_format(self) -> Dict[str, Any]:
        """Convert to Reddit platform format"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS library requires field name 'username' (no underscore)
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }

        # Add additional persona information (if present)
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
        if self.source_entity_uuid:
            profile["source_entity_uuid"] = self.source_entity_uuid
        if self.source_entity_type:
            profile["source_entity_type"] = self.source_entity_type

        return profile

    def to_twitter_format(self) -> Dict[str, Any]:
        """Convert to Twitter platform format"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS library requires field name 'username' (no underscore)
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }

        # Add additional persona information
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
        """Convert to full dictionary format"""
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
    """
    OASIS Profile Generator

    Converts entities from the Zep knowledge graph into Agent Profiles
    required for OASIS simulations.

    Key features:
    1. Calls Zep graph retrieval to obtain richer context
    2. Generates very detailed personas (basic info, career history, personality traits,
       social media behaviour, etc.)
    3. Distinguishes between individual entities and abstract group entities
    """

    # MBTI type list
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    
    # Common country list
    COUNTRIES = [
        "China", "US", "UK", "Japan", "Germany", "France", 
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]
    
    # Individual entity types (require a concrete persona)
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure", 
        "expert", "faculty", "official", "journalist", "activist"
    ]
    
    # Group/institution entity types (require a representative account persona)
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
        raw_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY is not configured")

        self.base_url, _default_query = parse_azure_url(raw_url)
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_query=_default_query if _default_query else None
        )

        # Graph retrieval client — only initialise Zep when it is the active backend
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id
        self._use_graphiti = (Config.GRAPH_BACKEND == "graphiti")

        if not self._use_graphiti and self.zep_api_key:
            try:
                self.zep_client = Zep(api_key=self.zep_api_key)
            except Exception as e:
                logger.warning(f"Zep client initialisation failed: {e}")
    
    def generate_profile_from_entity(
        self,
        entity: EntityNode,
        extra_instructions: Optional[str] = None,
    ) -> OasisAgentProfile:
        """
        Generate an OASIS Agent Profile from a Zep entity (public API).

        The returned profile has user_id=0 as a placeholder; callers must
        reassign user_id after insertion into the profiles list.

        Args:
            entity: Zep entity node
            extra_instructions: Optional extra instructions for the LLM persona

        Returns:
            OasisAgentProfile
        """
        return self._generate_single_profile(entity, user_id=0,
                                             extra_instructions=extra_instructions)

    def _generate_single_profile(
        self,
        entity: EntityNode,
        user_id: int,
        extra_instructions: Optional[str] = None,
        use_llm: bool = True
    ) -> OasisAgentProfile:
        """
        Internal: generate an OASIS Agent Profile for a single entity.

        Args:
            entity: Zep entity node
            user_id: User ID (for OASIS)
            extra_instructions: Optional extra instructions injected into the LLM prompt
            use_llm: Whether to use an LLM to generate a detailed persona

        Returns:
            OasisAgentProfile
        """
        entity_type = entity.get_entity_type() or "Entity"

        # Basic information
        name = entity.name
        user_name = self._generate_username(name)

        # Build context information
        context = self._build_entity_context(entity)

        if use_llm:
            # Use LLM to generate a detailed persona
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context
            )
        else:
            # Use rule-based generation for a basic persona
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
            interested_topics=_normalize_topics(profile_data.get("interested_topics", [])),
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )
    
    def _generate_username(self, name: str) -> str:
        """Generate a username"""
        # Remove special characters and convert to lowercase
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')

        # Add a random suffix to avoid duplicates
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"
    
    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """Retrieve rich context for an entity via graph hybrid search.

        Dispatches to Graphiti (Neo4j) or Zep Cloud depending on the active backend.
        """
        results = {"facts": [], "node_summaries": [], "context": ""}

        if not self.graph_id:
            logger.debug("Skipping graph retrieval: graph_id not set")
            return results

        entity_name = entity.name

        if self._use_graphiti:
            return self._search_graphiti_for_entity(entity_name, results)
        else:
            return self._search_zep_cloud_for_entity(entity_name, results)

    def _search_graphiti_for_entity(self, entity_name: str, results: Dict[str, Any]) -> Dict[str, Any]:
        """Use the Graphiti backend's search() to retrieve context for an entity."""
        import traceback
        from ..graph.factory import get_graph_backend

        max_retries = 3
        delay = 2.0
        last_exc = None

        for attempt in range(max_retries):
            try:
                backend = get_graph_backend()
                query = t('progress.zepSearchQuery', name=entity_name)
                search_result = backend.search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=30,
                    scope="edges"
                )
                all_facts = set()
                for edge in search_result.get("edges", []):
                    fact = edge.get("fact", "")
                    if fact:
                        all_facts.add(fact)
                results["facts"] = list(all_facts)

                context_parts = []
                if results["facts"]:
                    context_parts.append("Facts:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
                results["context"] = "\n\n".join(context_parts)

                logger.info(f"Graphiti retrieval complete: {entity_name}, fetched {len(results['facts'])} facts")
                return results
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    logger.debug(
                        f"Graphiti retrieval attempt {attempt + 1} failed ({entity_name}): "
                        f"{type(e).__name__}: {e} — retrying in {delay}s"
                    )
                    time.sleep(delay)
                    delay *= 2

        logger.warning(
            f"Graphiti retrieval failed after {max_retries} attempts ({entity_name}): "
            f"{type(last_exc).__name__}: {last_exc}\n{traceback.format_exc()}"
        )
        return results

    def _search_zep_cloud_for_entity(self, entity_name: str, results: Dict[str, Any]) -> Dict[str, Any]:
        """Use the Zep Cloud graph.search() to retrieve context for an entity."""
        import concurrent.futures

        if not self.zep_client:
            return results

        comprehensive_query = t('progress.zepSearchQuery', name=entity_name)

        def search_edges():
            max_retries = 3
            delay = 2.0
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                    )
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep edge search attempt {attempt + 1} failed: {str(e)[:80]}, retrying...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep edge search failed after {max_retries} attempts: {e}")
            return None

        def search_nodes():
            max_retries = 3
            delay = 2.0
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                    )
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep node search attempt {attempt + 1} failed: {str(e)[:80]}, retrying...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep node search failed after {max_retries} attempts: {e}")
            return None

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)
                edge_result = edge_future.result(timeout=30)
                node_result = node_future.result(timeout=30)

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

            logger.info(f"Zep hybrid retrieval complete: {entity_name}, fetched {len(results['facts'])} facts, {len(results['node_summaries'])} related nodes")

        except concurrent.futures.TimeoutError:
            logger.warning(f"Zep retrieval timed out ({entity_name})")
        except Exception as e:
            logger.warning(f"Zep retrieval failed ({entity_name}): {e}")

        return results
    
    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        Build the complete context information for an entity.

        Includes:
        1. Edge information (facts) from the entity itself
        2. Detailed information from related nodes
        3. Rich information retrieved via Zep hybrid search
        """
        context_parts = []

        # 1. Add entity attribute information
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### Entity Attributes\n" + "\n".join(attrs))

        # 2. Add related edge information (facts/relationships)
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:  # no quantity limit
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
                context_parts.append("### Related Facts and Relationships\n" + "\n".join(relationships))

        # 3. Add detailed information from related nodes
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:  # no quantity limit
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")

                # Filter out default labels
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""

                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")

            if related_info:
                context_parts.append("### Related Entity Information\n" + "\n".join(related_info))

        # 4. Use Zep hybrid search to obtain richer information
        zep_results = self._search_zep_for_entity(entity)

        if zep_results.get("facts"):
            # Deduplicate: exclude already-present facts
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Facts Retrieved from Zep\n" + "\n".join(f"- {f}" for f in new_facts[:15]))

        if zep_results.get("node_summaries"):
            context_parts.append("### Related Nodes Retrieved from Zep\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))
        
        return "\n\n".join(context_parts)
    
    def _is_individual_entity(self, entity_type: str) -> bool:
        """Check whether the entity type is an individual"""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES

    def _is_group_entity(self, entity_type: str) -> bool:
        """Check whether the entity type is a group or institution"""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES
    
    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> Dict[str, Any]:
        """
        Use an LLM to generate a very detailed persona.

        Distinguishes by entity type:
        - Individual entities: generate a concrete character profile
        - Group/institution entities: generate a representative account profile
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

        # Attempt multiple times until successful or max retries reached
        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": self._get_system_prompt(is_individual)},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1)  # lower temperature on each retry
                    # max_tokens not set — let the LLM respond freely
                )

                content = response.choices[0].message.content

                # Check for truncation (finish_reason is not 'stop')
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"LLM output truncated (attempt {attempt+1}), attempting repair...")
                    content = self._fix_truncated_json(content)

                # Try to parse JSON
                try:
                    result = json.loads(content)

                    # Validate required fields
                    if "bio" not in result or not result["bio"]:
                        result["bio"] = entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}"
                    if "persona" not in result or not result["persona"]:
                        result["persona"] = entity_summary or f"{entity_name} is a {entity_type}."

                    return result

                except json.JSONDecodeError as je:
                    logger.warning(f"JSON parse failed (attempt {attempt+1}): {str(je)[:80]}")

                    # Attempt to repair JSON
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        return result

                    last_error = je

            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(1 * (attempt + 1))  # exponential back-off

        logger.warning(f"LLM persona generation failed after {max_attempts} attempts: {last_error}, falling back to rule-based generation")
        return self._generate_profile_rule_based(
            entity_name, entity_type, entity_summary, entity_attributes
        )
    
    def _fix_truncated_json(self, content: str) -> str:
        """Repair JSON that was truncated by a max_tokens limit"""
        import re

        # If the JSON was truncated, attempt to close it
        content = content.strip()

        # Count unclosed braces
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # Check for unclosed strings
        # Simple check: if the last character is not a comma or closing bracket,
        # the string may have been cut off
        if content and content[-1] not in '",}]':
            # Attempt to close the string
            content += '"'

        # Close brackets
        content += ']' * open_brackets
        content += '}' * open_braces

        return content
    
    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """Attempt to repair damaged JSON"""
        import re

        # 1. First try to fix truncation
        content = self._fix_truncated_json(content)

        # 2. Attempt to extract the JSON portion
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()

            # 3. Fix newlines inside string values
            def fix_string_newlines(match):
                s = match.group(0)
                # Replace actual newlines inside strings with spaces
                s = s.replace('\n', ' ').replace('\r', ' ')
                # Collapse multiple spaces
                s = re.sub(r'\s+', ' ', s)
                return s

            # Match JSON string values
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)

            # 4. Try to parse
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # 5. Still failing — try a more aggressive repair
                try:
                    # Remove all control characters
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    # Collapse all consecutive whitespace
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass

        # 6. Attempt to extract partial information from the content
        bio_match = re.search(r'"bio"\s*:\s*"([^"]*)"', content)
        persona_match = re.search(r'"persona"\s*:\s*"([^"]*)', content)  # may be truncated

        bio = bio_match.group(1) if bio_match else (entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}")
        persona = persona_match.group(1) if persona_match else (entity_summary or f"{entity_name} is a {entity_type}.")

        # If we extracted meaningful content, mark as fixed
        if bio_match or persona_match:
            logger.info(f"Extracted partial information from damaged JSON")
            return {
                "bio": bio,
                "persona": persona,
                "_fixed": True
            }

        # 7. Complete failure — return a minimal structure
        logger.warning(f"JSON repair failed, returning minimal structure")
        return {
            "bio": entity_summary[:200] if entity_summary else f"{entity_type}: {entity_name}",
            "persona": entity_summary or f"{entity_name} is a {entity_type}."
        }
    
    def _get_system_prompt(self, is_individual: bool) -> str:
        """Get the system prompt"""
        base_prompt = "You are an expert in generating social media user profiles. Generate detailed, realistic personas for public opinion simulations, reproducing existing real-world situations as faithfully as possible. You must return valid JSON. All string values must not contain unescaped newline characters."
        return f"{base_prompt}\n\n{get_language_instruction()}"
    
    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build a detailed persona prompt for an individual entity"""

        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "none"
        context_str = context[:3000] if context else "no additional context"

        return f"""Generate a detailed social media user persona for the entity below, reproducing existing real-world situations as faithfully as possible.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context information:
{context_str}

Generate JSON with the following fields:

1. bio: social media profile, ~200 words
2. persona: detailed persona description (~2000 words of plain text), covering:
   - Basic information (age, occupation, educational background, location)
   - Background (important experiences, connection to events, social relationships)
   - Personality traits (MBTI type, core character, emotional expression style)
   - Social media behaviour (posting frequency, content preferences, interaction style, language characteristics)
   - Stance and opinions (attitude towards topics, content that might provoke or move them)
   - Distinctive features (catchphrases, unique experiences, personal hobbies)
   - Personal memory (important part of the persona: describe this individual's connection to the event and their existing actions and reactions within it)
3. age: numeric age (must be an integer)
4. gender: must be English: "male" or "female"
5. mbti: MBTI type (e.g. INTJ, ENFP)
6. country: country name (e.g. "China")
7. profession: occupation
8. interested_topics: array of topics of interest

Important:
- All field values must be strings or numbers; do not use newline characters
- persona must be a single continuous block of text
- {get_language_instruction()} (the gender field must use English: male/female)
- Content must be consistent with the entity information
- age must be a valid integer; gender must be "male" or "female"
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str
    ) -> str:
        """Build a detailed persona prompt for a group/institution entity"""

        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "none"
        context_str = context[:3000] if context else "no additional context"

        return f"""Generate detailed social media account settings for an institution/group entity, reproducing existing real-world situations as faithfully as possible.

Entity name: {entity_name}
Entity type: {entity_type}
Entity summary: {entity_summary}
Entity attributes: {attrs_str}

Context information:
{context_str}

Generate JSON with the following fields:

1. bio: official account profile, ~200 words, professional and appropriate in tone
2. persona: detailed account description (~2000 words of plain text), covering:
   - Institutional basics (official name, nature of the institution, founding background, main functions)
   - Account positioning (account type, target audience, core purpose)
   - Communication style (language characteristics, common expressions, taboo topics)
   - Content characteristics (content types, posting frequency, active time periods)
   - Stance and attitude (official position on key topics, approach to handling controversies)
   - Special notes (audience profile represented, operational habits)
   - Institutional memory (important part of the persona: describe this institution's connection to the event and its existing actions and reactions within it)
3. age: fixed value 30 (virtual age for institutional accounts)
4. gender: fixed value "other" (institutional accounts use "other" to denote non-individual)
5. mbti: MBTI type describing the account's style, e.g. ISTJ for rigorous and conservative
6. country: country name (e.g. "China")
7. profession: description of the institution's function
8. interested_topics: array of focus areas

Important:
- All field values must be strings or numbers; null values are not allowed
- persona must be a single continuous block of text; do not use newline characters
- {get_language_instruction()} (gender field must use the English string "other")
- age must be the integer 30; gender must be the string "other"
- Institutional account speech must be consistent with its identity and positioning"""
    
    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate a basic persona using rules"""

        # Generate different personas according to entity type
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
                "age": 30,  # virtual age for institutional accounts
                "gender": "other",  # institutions use "other"
                "mbti": "ISTJ",  # institutional style: rigorous and conservative
                "country": "China",
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }

        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters.",
                "age": 30,  # virtual age for institutional accounts
                "gender": "other",  # institutions use "other"
                "mbti": "ISTJ",  # institutional style: rigorous and conservative
                "country": "China",
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }

        else:
            # Default persona
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
        """Set the graph ID for Zep retrieval"""
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
        """
        Bulk-generate Agent Profiles from entities (supports parallel generation).

        Args:
            entities: List of entity nodes
            use_llm: Whether to use an LLM to generate detailed personas
            progress_callback: Progress callback function (current, total, message)
            graph_id: Graph ID used for Zep retrieval to obtain richer context
            parallel_count: Number of parallel workers, default 5
            realtime_output_path: File path for real-time writing (if provided, written after each profile is generated)
            output_platform: Output platform format ("reddit" or "twitter")

        Returns:
            List of Agent Profiles
        """
        import concurrent.futures
        from threading import Lock
        
        # Set graph_id for Zep retrieval
        if graph_id:
            self.graph_id = graph_id

        total = len(entities)
        profiles = [None] * total  # pre-allocate list to preserve order
        completed_count = [0]  # use list so it can be mutated inside a closure
        lock = Lock()

        # Helper for real-time file writing
        def save_profiles_realtime():
            """Save already-generated profiles to disk in real time"""
            if not realtime_output_path:
                return

            with lock:
                # Filter out profiles that have been generated
                existing_profiles = [p for p in profiles if p is not None]
                if not existing_profiles:
                    return

                try:
                    if output_platform == "reddit":
                        # Reddit JSON format
                        profiles_data = [p.to_reddit_format() for p in existing_profiles]
                        with open(realtime_output_path, 'w', encoding='utf-8') as f:
                            json.dump(profiles_data, f, ensure_ascii=False, indent=2)
                    else:
                        # Twitter CSV format
                        import csv
                        profiles_data = [p.to_twitter_format() for p in existing_profiles]
                        if profiles_data:
                            fieldnames = list(profiles_data[0].keys())
                            with open(realtime_output_path, 'w', encoding='utf-8', newline='') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writeheader()
                                writer.writerows(profiles_data)
                except Exception as e:
                    logger.warning(f"Real-time profile save failed: {e}")
        
        # Capture locale before spawning thread pool workers
        current_locale = get_locale()

        def generate_single_profile(idx: int, entity: EntityNode) -> tuple:
            """Worker function to generate a single profile"""
            set_locale(current_locale)
            entity_type = entity.get_entity_type() or "Entity"

            try:
                profile = self._generate_single_profile(
                    entity=entity,
                    user_id=idx,
                    use_llm=use_llm
                )

                # Print the generated persona to console and logs in real time
                self._print_generated_profile(entity.name, entity_type, profile)

                return idx, profile, None

            except Exception as e:
                logger.error(f"Failed to generate persona for entity {entity.name}: {str(e)}")
                # Create a fallback profile
                fallback_profile = OasisAgentProfile(
                    user_id=idx,
                    user_name=self._generate_username(entity.name),
                    name=entity.name,
                    bio=f"{entity_type}: {entity.name}",
                    persona=entity.summary or f"A participant in social discussions.",
                    source_entity_uuid=entity.uuid,
                    source_entity_type=entity_type,
                )
                return idx, fallback_profile, str(e)
        
        logger.info(f"Starting parallel persona generation for {total} agents (parallel workers: {parallel_count})...")
        print(f"\n{'='*60}")
        print(f"Starting Agent persona generation - {total} entities total, parallel workers: {parallel_count}")
        print(f"{'='*60}\n")
        
        # Execute in parallel using a thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
            # Submit all tasks
            future_to_entity = {
                executor.submit(generate_single_profile, idx, entity): (idx, entity)
                for idx, entity in enumerate(entities)
            }

            # Collect results
            for future in concurrent.futures.as_completed(future_to_entity):
                idx, entity = future_to_entity[future]
                entity_type = entity.get_entity_type() or "Entity"
                
                try:
                    result_idx, profile, error = future.result()
                    profiles[result_idx] = profile
                    
                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]
                    
                    # Write to file in real time
                    save_profiles_realtime()
                    
                    if progress_callback:
                        progress_callback(
                            current,
                            total,
                            f"Completed {current}/{total}: {entity.name} ({entity_type})"
                        )

                    if error:
                        logger.warning(f"[{current}/{total}] {entity.name} using fallback persona: {error}")
                    else:
                        logger.info(f"[{current}/{total}] Successfully generated persona: {entity.name} ({entity_type})")

                except Exception as e:
                    logger.error(f"Exception while processing entity {entity.name}: {str(e)}")
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
                    # Write to file in real time (even for fallback personas)
                    save_profiles_realtime()

        print(f"\n{'='*60}")
        print(f"Persona generation complete! Generated {len([p for p in profiles if p])} agents")
        print(f"{'='*60}\n")
        
        return profiles
    
    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """Print the generated persona to console in real time (full content, no truncation)"""
        separator = "-" * 70

        # Build the full output content (no truncation)
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else 'none'

        output_lines = [
            f"\n{separator}",
            t('progress.profileGenerated', name=entity_name, type=entity_type),
            f"{separator}",
            f"Username: {profile.user_name}",
            f"",
            f"[Bio]",
            f"{profile.bio}",
            f"",
            f"[Detailed Persona]",
            f"{profile.persona}",
            f"",
            f"[Basic Attributes]",
            f"Age: {profile.age} | Gender: {profile.gender} | MBTI: {profile.mbti}",
            f"Profession: {profile.profession} | Country: {profile.country}",
            f"Topics of Interest: {topics_str}",
            separator
        ]

        output = "\n".join(output_lines)

        # Output to console only (avoid duplication — logger no longer prints full content)
        print(output)
    
    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        Save profiles to a file in the correct format for the platform.

        OASIS platform format requirements:
        - Twitter: CSV format
        - Reddit: JSON format

        Args:
            profiles: List of profiles
            file_path: File path
            platform: Platform type ("reddit" or "twitter")
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)
    
    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Save Twitter Profiles in CSV format (compliant with OASIS official requirements).

        CSV fields required by OASIS Twitter:
        - user_id: User ID (sequential from 0 based on CSV order)
        - name: User's real name
        - username: Username in the system
        - user_char: Detailed persona description (injected into the LLM system prompt to guide Agent behaviour)
        - description: Short public profile (displayed on the user profile page)

        user_char vs description:
        - user_char: Internal use; LLM system prompt that determines how the Agent thinks and acts
        - description: External display; the profile visible to other users
        """
        import csv

        # Ensure the file extension is .csv
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Write the OASIS-required header
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)

            # Write data rows
            for idx, profile in enumerate(profiles):
                # user_char: full persona (bio + persona), used in the LLM system prompt
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # Replace newlines with spaces in CSV
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')

                # description: short profile for external display
                description = profile.bio.replace('\n', ' ').replace('\r', ' ')

                row = [
                    idx,                    # user_id: sequential ID starting from 0
                    profile.name,           # name: real name
                    profile.user_name,      # username: username
                    user_char,              # user_char: full persona (internal LLM use)
                    description             # description: short profile (external display)
                ]
                writer.writerow(row)

        logger.info(f"Saved {len(profiles)} Twitter profiles to {file_path} (OASIS CSV format)")
    
    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        Normalise the gender field to the English format required by OASIS.

        OASIS accepts: male, female, other
        """
        if not gender:
            return "other"

        gender_lower = gender.lower().strip()

        # Chinese-to-English mapping
        gender_map = {
            "男": "male",
            "女": "female",
            "机构": "other",
            "其他": "other",
            # English values passed through as-is
            "male": "male",
            "female": "female",
            "other": "other",
        }
        
        return gender_map.get(gender_lower, "other")
    
    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        Save Reddit Profiles in JSON format.

        Uses the same format as to_reddit_format() to ensure OASIS can read it correctly.
        The user_id field is mandatory — it is the key used by OASIS agent_graph.get_agent()
        to match profiles!

        Required fields:
        - user_id: User ID (integer, used to match poster_agent_id in initial_posts)
        - username: Username
        - name: Display name
        - bio: Profile bio
        - persona: Detailed persona
        - age: Age (integer)
        - gender: "male", "female", or "other"
        - mbti: MBTI type
        - country: Country
        """
        data = []
        for idx, profile in enumerate(profiles):
            # Use the same format as to_reddit_format()
            item = {
                "user_id": profile.user_id if profile.user_id is not None else idx,  # critical: user_id must be present
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150] if profile.bio else f"{profile.name}",
                "persona": profile.persona or f"{profile.name} is a participant in social discussions.",
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # OASIS required fields - ensure all have default values
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else "China",
            }

            # Optional fields
            if profile.profession:
                item["profession"] = profile.profession
            if profile.interested_topics:
                item["interested_topics"] = profile.interested_topics

            data.append(item)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(profiles)} Reddit profiles to {file_path} (JSON format, includes user_id field)")
    
    # Keep old method name as an alias for backwards compatibility
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[Deprecated] Please use save_profiles() instead"""
        logger.warning("save_profiles_to_json is deprecated; please use save_profiles instead")
        self.save_profiles(profiles, file_path, platform)

