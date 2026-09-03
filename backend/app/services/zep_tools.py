"""
Zep retrieval tools.

Wraps graph search, node reads and edge queries for the Report Agent.

Core retrieval tools:
1. InsightForge (deep insight retrieval) - the strongest hybrid search; it
   decomposes the question into sub-questions and searches several dimensions
2. PanoramaSearch (broad search) - the full picture, expired content included
3. QuickSearch (simple search) - a fast single-pass lookup
"""

import json
import re
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from zep_cloud import NotFoundError

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.locale import t
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep import (
    call_zep_read_with_retry,
    get_zep_client,
    normalize_zep_search_limit,
    normalize_zep_search_query,
)

logger = get_logger('sosim.zep_tools')


# --- English sentence splitting and key-quote ranking -----------------------
# Used by the interview pipeline to turn an agent's free-text answer into a
# handful of quotable sentences.

# Stand-in for a period that must not be read as a sentence terminator. NUL
# cannot occur in model output, so masking and unmasking round-trips exactly.
_PERIOD_MASK = '\x00'

# Abbreviations and initialisms whose period is followed by a space and so
# would otherwise look like a sentence end: "The U.S. market" must stay one
# sentence, not three. The first branch covers dotted initialisms (U.S., e.g.,
# i.e., a.m., J. R.); the second covers common single-token abbreviations.
_ABBREVIATION_RE = re.compile(
    r'\b(?:'
    r'[A-Za-z]\.(?:\s?[A-Za-z]\.)+'
    r'|(?:Mr|Mrs|Ms|Dr|Prof|Rev|Sr|Jr|St|Mt|Gov|Sen|Rep|Gen|Capt'
    r'|Inc|Ltd|Co|Corp|Dept|Univ|Est|Fig|No|Vol|Jan|Feb|Mar|Apr|Jun'
    r'|Jul|Aug|Sep|Sept|Oct|Nov|Dec|vs|etc|approx|al|cf)\.'
    r')'
)

# A run of terminators counts as a sentence end only when whitespace or the
# end of the text follows, which keeps decimals ("a 3.5% lift") intact. The
# terminator is captured so the sentence can be rebuilt with it.
_SENTENCE_END_RE = re.compile(r'([.!?]+)(?:\s+|$)')

# The "Question N:" answer prefix the interview prompt mandates. Anchored to
# the start of a line so a mid-sentence reference ("I covered that in
# Question 3. The next point ...") survives, and colon-only because a period
# there is ordinary sentence punctuation, not a separator.
_QUESTION_PREFIX_RE = re.compile(r'^[ \t]*Question\s*\d+\s*:[ \t]*', re.MULTILINE)

# Key-quote length bounds, in words. The pre-rewrite bounds were 20-150 CJK
# characters, where a character is roughly a word; applying those numbers to
# English characters admitted four-word filler such as "I agree completely
# here". Ten words is about the shortest sentence that can carry a claim;
# fifty is about where a quote stops being quotable.
_MIN_QUOTE_WORDS = 10
_MAX_QUOTE_WORDS = 50
_IDEAL_QUOTE_WORDS = 22

# Signals that a sentence asserts something concrete rather than just agreeing.
_SUBSTANCE_RE = re.compile(
    r'\d|%|\$|\b(?:because|since|therefore|however|although|instead|unless|'
    r'means|risk|cost|impact|expect|prefer|avoid|need|should|would)\b',
    re.IGNORECASE,
)

# Openers that mark a sentence as backchannel rather than substance.
_FILLER_OPENER_RE = re.compile(
    r'^(?:yes|no|sure|exactly|absolutely|totally|agreed|same here|'
    r'i agree|i disagree|good point|well said|that\'s right)\b',
    re.IGNORECASE,
)


def _split_sentences(text: str) -> List[str]:
    """
    Split English prose into sentences, each keeping its terminator.

    Two rules keep fragments out. A terminator ends a sentence only when
    whitespace or the end of the text follows it, so decimals stay intact.
    That is not sufficient in English, because an abbreviation's period IS
    followed by a space, so abbreviations are masked before the split and
    restored after it.
    """
    masked = _ABBREVIATION_RE.sub(
        lambda m: m.group(0).replace('.', _PERIOD_MASK), text
    )
    # re.split with one capturing group yields [body, terminator, body, ...],
    # ending on a body (empty when the text ends on a terminator).
    pieces = _SENTENCE_END_RE.split(masked)
    sentences = []
    for i in range(0, len(pieces), 2):
        terminator = pieces[i + 1] if i + 1 < len(pieces) else ''
        sentence = (pieces[i] + terminator).replace(_PERIOD_MASK, '.').strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def _key_quote_score(sentence: str) -> float:
    """
    Rank a candidate key quote by substance rather than by raw length.

    Sorting on length alone promoted whichever sentence rambled longest. This
    prefers a quote near the ideal length, rewards concrete claims, penalises
    bare agreement, and rewards varied wording over repetition.
    """
    words = sentence.split()
    if not words:
        return 0.0
    distance = abs(len(words) - _IDEAL_QUOTE_WORDS) / _IDEAL_QUOTE_WORDS
    score = 1.0 - min(distance, 1.0)
    if _SUBSTANCE_RE.search(sentence):
        score += 0.5
    if _FILLER_OPENER_RE.match(sentence):
        score -= 1.0
    score += 0.5 * (len({w.lower() for w in words}) / len(words))
    return score


@dataclass
class SearchResult:
    """One graph search and the facts, edges and nodes it returned."""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count
        }
    
    def to_text(self) -> str:
        """Render the result as the markdown the report agent reads."""
        text_parts = [f"Search Query: {self.query}", f"Found {self.total_count} results"]

        if self.facts:
            text_parts.append("\n### Related Facts:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """One graph node."""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }
    
    def to_text(self) -> str:
        """Render the node as markdown."""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "Unknown")
        return f"Entity: {self.name} (type: {entity_type})\nSummary: {self.summary}"


@dataclass
class EdgeInfo:
    """One graph edge, with the interval over which its fact held."""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # Temporal validity
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }
    
    def to_text(self, include_temporal: bool = False) -> str:
        """Render the edge as markdown."""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"Relation: {source} --[{self.name}]--> {target}\nFact: {self.fact}"

        if include_temporal:
            valid_at = self.valid_at or "Unknown"
            invalid_at = self.invalid_at or "Present"
            base_text += f"\nValid: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (expired: {self.expired_at})"

        return base_text

    @property
    def is_expired(self) -> bool:
        """Whether the edge has expired."""
        return self.expired_at is not None

    @property
    def is_invalid(self) -> bool:
        """Whether the edge has been invalidated."""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    An InsightForge run: the sub-question results plus the combined analysis.
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]

    # Results per dimension
    semantic_facts: List[str] = field(default_factory=list)  # semantic search
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # entities
    relationship_chains: List[str] = field(default_factory=list)  # relation chains

    # Counters
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }
    
    def to_text(self) -> str:
        """Render the run as the markdown the report agent reads."""
        text_parts = [
            f"## Deep Prediction Analysis",
            f"Analysis Question: {self.query}",
            f"Prediction Scenario: {self.simulation_requirement}",
            f"\n### Prediction Data Statistics",
            f"- Related Prediction Facts: {self.total_facts}",
            f"- Involved Entities: {self.total_entities}",
            f"- Relation Chains: {self.total_relationships}"
        ]

        # Sub-questions
        if self.sub_queries:
            text_parts.append(f"\n### Analyzed Sub-Questions")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")

        # Semantic search results
        if self.semantic_facts:
            text_parts.append(f"\n### [Key Facts] (quote these verbatim in the report)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")

        # Entity insights
        if self.entity_insights:
            text_parts.append(f"\n### [Core Entities]")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', 'Unknown')}** ({entity.get('type', 'Entity')})")
                if entity.get('summary'):
                    text_parts.append(f"  Summary: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  Related Facts: {len(entity.get('related_facts', []))}")

        # Relation chains
        if self.relationship_chains:
            text_parts.append(f"\n### [Relation Chains]")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")

        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    A PanoramaSearch run: everything relevant, expired content included.
    """
    query: str

    # Every node
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # Every edge, expired ones included
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # Facts that still hold
    active_facts: List[str] = field(default_factory=list)
    # Facts that have expired or been invalidated
    historical_facts: List[str] = field(default_factory=list)

    # Counters
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }
    
    def to_text(self) -> str:
        """Render the run as markdown, in full and without truncation."""
        text_parts = [
            f"## Panorama Search Results (Future Overview)",
            f"Query: {self.query}",
            f"\n### Statistics",
            f"- Total Nodes: {self.total_nodes}",
            f"- Total Edges: {self.total_edges}",
            f"- Currently Valid Facts: {self.active_count}",
            f"- Historical / Expired Facts: {self.historical_count}"
        ]

        # Facts that still hold, in full
        if self.active_facts:
            text_parts.append(f"\n### [Currently Valid Facts] (verbatim simulation output)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")

        # Facts that have expired, in full
        if self.historical_facts:
            text_parts.append(f"\n### [Historical / Expired Facts] (evolution record)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")

        # Entities involved, in full
        if self.all_nodes:
            text_parts.append(f"\n### [Involved Entities]")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                text_parts.append(f"- **{node.name}** ({entity_type})")

        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """One simulated agent's interview answers."""
    agent_name: str
    agent_role: str  # role, for example student, teacher or journalist
    agent_bio: str  # short biography
    question: str  # the questions put to the agent
    response: str  # the agent's answers
    key_quotes: List[str] = field(default_factory=list)  # pull quotes
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }
    
    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # The biography is shown in full; the caller has already capped it.
        text += f"_Bio: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**Key Quotes:**\n"
            for quote in self.key_quotes:
                # Drop straight and typographic quotation marks; the quote is
                # re-quoted below.
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.strip()
                # Trim leading punctuation left behind by the split.
                while clean_quote and clean_quote[0] in ' \t\n\r,;:.!?':
                    clean_quote = clean_quote[1:]
                # Drop fragments that are really the answer-prefix marker the
                # interview prompt mandates, not a quotable sentence.
                skip = False
                for d in '123456789':
                    if f'Question {d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # Cut a long quote at a sentence boundary rather than mid-word.
                if len(clean_quote) > 150:
                    boundary = re.search(r'[.!?](?=\s|$)', clean_quote[80:])
                    if boundary:
                        clean_quote = clean_quote[:80 + boundary.end()]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    One interview round across several simulated agents.
    """
    interview_topic: str  # what the interview is about
    interview_questions: List[str]  # the questions put to every interviewee

    # The agents chosen for the interview
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # Their answers
    interviews: List[AgentInterview] = field(default_factory=list)

    # Why those agents were chosen
    selection_reasoning: str = ""
    # The combined summary of the round
    summary: str = ""

    # Counters
    total_agents: int = 0
    interviewed_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }
    
    def to_text(self) -> str:
        """Render the round as the markdown the report agent reads."""
        text_parts = [
            "## Deep Interview Report",
            f"**Interview Topic:** {self.interview_topic}",
            f"**Interviewees:** {self.interviewed_count} / {self.total_agents} simulated agents",
            "\n### Interviewee Selection Rationale",
            self.selection_reasoning or "(Selected automatically)",
            "\n---",
            "\n### Interview Transcript",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### Interview #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("(No interviews recorded)\n\n---")

        text_parts.append("\n### Interview Summary and Key Views")
        text_parts.append(self.summary or "(No summary)")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Zep retrieval tools for the Report Agent.

    Core retrieval tools:
    1. insight_forge - deep insight retrieval; decomposes the question into
       sub-questions and searches several dimensions
    2. panorama_search - broad search; the full picture, expired content included
    3. quick_search - a fast single-pass lookup
    4. interview_agents - deep interview; asks the simulated agents directly

    Building blocks:
    - search_graph - semantic graph search
    - get_all_nodes - every node in the graph
    - get_all_edges - every edge in the graph, with its temporal validity
    - get_node_detail - one node in full
    - get_node_edges - the edges attached to one node
    - get_entities_by_type - every entity of one type
    - get_entity_summary - one entity and the relations around it
    """

    # Retry policy
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured.")
        
        self.client = get_zep_client(self.api_key)
        # The LLM client generates InsightForge sub-questions.
        self._llm_client = llm_client
        logger.info(t("console.zepToolsInitialized"))
    
    @property
    def llm(self) -> LLMClient:
        """Create the LLM client on first use."""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Retry one safe read using typed Zep/HTTPX error classification."""

        return call_zep_read_with_retry(
            func,
            operation_name=operation_name,
            max_attempts=max_retries or self.MAX_RETRIES,
            initial_delay=self.RETRY_DELAY,
        )
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """Search the graph semantically.

        Runs Zep's hybrid search, semantic plus BM25, over the graph.

        Args:
            graph_id: Graph ID of the standalone graph
            query: Search query
            limit: How many results to return
            scope: Search scope, "edges" or "nodes"

        Returns:
            SearchResult: The matching facts, edges and nodes
        """
        logger.info(t("console.graphSearch", graphId=graph_id, query=query[:50]))
        
        zep_query = normalize_zep_search_query(query)
        zep_limit = normalize_zep_search_limit(limit)

        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=zep_query,
                    limit=zep_limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=t("console.graphSearchOp", graphId=graph_id)
            )
            
            facts = []
            edges = []
            nodes = []
            
            # Edge hits
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })
            
            # Node hits
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # A node summary counts as a fact for the report.
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.searchComplete", count=len(facts)))
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            # Authentication, invalid input, missing graphs, and exhausted
            # transient failures must remain visible to the report workflow.
            logger.error(t("console.zepSearchApiFallback", error=str(e)))
            raise
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """Match keywords locally, as a fallback for the Zep search API.

        Reads every edge or node and scores it against the query in process.

        Args:
            graph_id: Graph ID
            query: Search query
            limit: How many results to return
            scope: Search scope

        Returns:
            SearchResult: The matching facts, edges and nodes
        """
        logger.info(t("console.usingLocalSearch", query=query[:30]))
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # Split the query into keywords on whitespace and commas.
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').split() if len(w.strip()) > 1]

        def match_score(text: str) -> int:
            """Score one piece of text against the query."""
            if not text:
                return 0
            text_lower = text.lower()
            # Whole-query match
            if query_lower in text_lower:
                return 100
            # Keyword match
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # Score every edge.
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # Highest score first.
                scored_edges.sort(key=lambda x: x[0], reverse=True)
                
                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })
            
            if scope in ["nodes", "both"]:
                # Score every node.
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))
                
                scored_nodes.sort(key=lambda x: x[0], reverse=True)
                
                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(t("console.localSearchComplete", count=len(facts)))
            
        except Exception as e:
            logger.error(t("console.localSearchFailed", error=str(e)))
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """Fetch every node in a graph, following the pagination cursor.

        Args:
            graph_id: Graph ID

        Returns:
            The graph's nodes
        """
        logger.info(t("console.fetchingAllNodes", graphId=graph_id))

        nodes = fetch_all_nodes(self.client, graph_id)

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(t("console.fetchedNodes", count=len(result)))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """Fetch every edge in a graph, following the pagination cursor.

        Args:
            graph_id: Graph ID
            include_temporal: Whether to carry the validity interval across

        Returns:
            The graph's edges, with created_at, valid_at, invalid_at and
            expired_at when include_temporal is set
        """
        logger.info(t("console.fetchingAllEdges", graphId=graph_id))

        edges = fetch_all_edges(self.client, graph_id)

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            # Carry the validity interval across.
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(t("console.fetchedEdges", count=len(result)))
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """Fetch one node in full.

        Args:
            node_uuid: Node UUID

        Returns:
            The node, or None when it does not exist
        """
        logger.info(t("console.fetchingNodeDetail", uuid=node_uuid[:8]))
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=t("console.fetchNodeDetailOp", uuid=node_uuid[:8])
            )
            
            if not node:
                return None
            
            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except NotFoundError:
            return None
        except Exception as e:
            logger.error(t("console.fetchNodeDetailFailed", error=str(e)))
            raise
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """Fetch every edge attached to one node.

        Reads the whole graph and keeps the edges touching the node, so both
        incoming and outgoing relations are returned.

        Args:
            graph_id: Graph ID
            node_uuid: Node UUID

        Returns:
            The edges attached to the node
        """
        logger.info(t("console.fetchingNodeEdges", uuid=node_uuid[:8]))
        
        try:
            all_edges = self.get_all_edges(graph_id)

            result = []
            for edge in all_edges:
                # Keep the edge when the node is either end of it.
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(t("console.foundNodeEdges", count=len(result)))
            return result
            
        except Exception as e:
            logger.error(t("console.fetchNodeEdgesFailed", error=str(e)))
            raise
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """Fetch every entity of one type.

        Args:
            graph_id: Graph ID
            entity_type: Entity type, for example Student or PublicFigure

        Returns:
            The entities carrying that type
        """
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # Keep the node when it carries the requested label.
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(t("console.foundEntitiesByType", count=len(filtered), type=entity_type))
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """Summarise one entity and the relations around it.

        Args:
            graph_id: Graph ID
            entity_name: Entity name

        Returns:
            The entity, the facts mentioning it and its edges
        """
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        
        # Search for anything mentioning the entity first.
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # Then locate the entity node itself.
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # graph_id is required so both edge directions are returned.
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """Count the nodes, edges and type distributions in a graph.

        Args:
            graph_id: Graph ID

        Returns:
            The graph's counters and type distributions
        """
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # Entity type distribution
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # Relation type distribution
        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }
    
    def get_simulation_context(
        self, 
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30
    ) -> Dict[str, Any]:
        """Gather the graph context relevant to a simulation requirement.

        Args:
            graph_id: Graph ID
            simulation_requirement: The simulation requirement to search for
            limit: Maximum number of items per category

        Returns:
            The facts, statistics and entities relevant to the requirement
        """
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        
        # Search for anything matching the requirement.
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # Graph-wide counters
        stats = self.get_graph_statistics(graph_id)
        
        # Every node in the graph
        all_nodes = self.get_all_nodes(graph_id)
        
        # Keep only nodes carrying a real type, not bare Entity nodes.
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })
        
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],
            "total_entities": len(entities)
        }
    
    # ========== Core retrieval tools ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """Run the deep insight retrieval pass.

        The strongest hybrid search available to the report agent:
        1. Ask the LLM to break the question into sub-questions
        2. Search the graph semantically for each sub-question
        3. Pull the entities those results touch and read them in full
        4. Trace the relation chains between them
        5. Combine everything into one insight payload

        Args:
            graph_id: Graph ID
            query: The question to answer
            simulation_requirement: The simulation requirement for context
            report_context: Report context, used to sharpen the sub-questions
            max_sub_queries: Maximum number of sub-questions

        Returns:
            InsightForgeResult: The combined retrieval result
        """
        logger.info(t("console.insightForgeStart", query=query[:50]))
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )
        
        # Step 1: ask the LLM for sub-questions
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(t("console.generatedSubQueries", count=len(sub_queries)))
        
        # Step 2: search the graph for each sub-question
        all_facts = []
        all_edges = []
        seen_facts = set()
        
        for sub_query in sub_queries:
            search_result = self.search_graph(
                graph_id=graph_id,
                query=sub_query,
                limit=15,
                scope="edges"
            )
            
            for fact in search_result.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            
            all_edges.extend(search_result.edges)
        
        # Search for the original question as well.
        main_search = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=20,
            scope="edges"
        )
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)
        
        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)
        
        # Step 3: read only the entities the matched edges touch
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        entity_insights = []
        node_map = {}  # reused when the relation chains are built below

        for uuid in list(entity_uuids):
            if not uuid:
                continue
            try:
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")

                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts
                    })
            except Exception as e:
                logger.debug(f"Failed to fetch node {uuid}: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Step 4: build every relation chain
        relationship_chains = []
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')
                
                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]
                
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)
        
        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        
        logger.info(t("console.insightForgeComplete", facts=result.total_facts, entities=result.total_entities, relationships=result.total_relationships))
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """Break a complex question into independently searchable sub-questions."""
        system_prompt = """You are an expert question analyst. Break a complex question into several sub-questions, each of which can be observed on its own inside the simulated world.

Requirements:
1. Make each sub-question concrete enough to match agent behaviour or events in the simulated world
2. Cover different dimensions of the original question: who, what, why, how, when and where
3. Keep every sub-question relevant to the simulation scenario
4. Return JSON: {"sub_queries": ["first sub-question", "second sub-question", ...]}"""

        user_prompt = f"""Simulation requirement:
{simulation_requirement}

{f"Report context: {report_context[:500]}" if report_context else ""}

Break the following question into {max_queries} sub-questions:
{query}

Return the sub-questions as JSON."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # Coerce to a list of strings, whatever the model returned.
            return [str(sq) for sq in sub_queries[:max_queries]]

        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
            # Fall back to plain variations on the original question.
            return [
                query,
                f"Who is involved in {query}",
                f"What caused {query} and what did it lead to",
                f"How {query} developed over time"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """Run the broad search pass.

        Returns the whole picture, historical and expired content included:
        1. Read every node
        2. Read every edge, expired and invalidated ones included
        3. Split the facts into the ones that still hold and the ones that do not

        Use it to understand how an event unfolded, not just where it landed.

        Args:
            graph_id: Graph ID
            query: Search query, used to rank the results
            include_expired: Whether to return expired facts as well
            limit: Maximum number of facts per category

        Returns:
            PanoramaResult: The broad search result
        """
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        
        result = PanoramaResult(query=query)
        
        # Every node
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # Every edge, with its validity interval
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # Split the facts by whether they still hold.
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # Resolve the endpoint names for the fact text.
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # Expired or invalidated facts are historical.
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                valid_at = edge.valid_at or "Unknown"
                invalid_at = edge.invalid_at or edge.expired_at or "Unknown"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                active_facts.append(edge.fact)

        # Rank both lists against the query.
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # Rank, then cap each list.
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(t("console.panoramaSearchComplete", active=result.active_count, historical=result.historical_count))
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """Run a fast, single-pass semantic search.

        Args:
            graph_id: Graph ID
            query: Search query
            limit: How many results to return

        Returns:
            SearchResult: The matching facts, edges and nodes
        """
        logger.info(t("console.quickSearchStart", query=query[:50]))

        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(t("console.quickSearchComplete", count=result.total_count))
        return result
    
    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None
    ) -> InterviewResult:
        """Interview the agents of a running simulation through the OASIS API.

        1. Read the agent profiles to see who is in the simulation
        2. Ask the LLM which of them best fits the interview requirement
        3. Ask the LLM for the interview questions
        4. Call /api/simulation/interview/batch, on both platforms at once
        5. Combine the answers into one interview report

        The simulation environment must still be running: these are the
        agents' own answers, not an LLM impersonating them.

        Args:
            simulation_id: Simulation ID, used to locate the profiles and to
                call the interview API
            interview_requirement: What the interview should find out, in
                free text, for example "how students see the incident"
            simulation_requirement: The simulation requirement, for context
            max_agents: Maximum number of agents to interview
            custom_questions: Questions to ask; generated when omitted

        Returns:
            InterviewResult: The interview round
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Step 1: read the agent profiles
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(t("console.profilesNotFound", simId=simulation_id))
            result.summary = "No agent profiles were found for this simulation."
            return result
        
        result.total_agents = len(profiles)
        logger.info(t("console.loadedProfiles", count=len(profiles)))
        
        # Step 2: ask the LLM which agents to interview
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(t("console.selectedAgentsForInterview", count=len(selected_agents), indices=selected_indices))
        
        # Step 3: generate the questions when the caller supplied none
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(t("console.generatedInterviewQuestions", count=len(result.interview_questions)))
        
        # Every interviewee gets the same numbered question list.
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # Rule 4 is a closed loop with the quote parser below: it mandates the
        # "Question N:" answer prefix that the parser strips. Change the
        # prompt, the marker and the parser together or key_quotes goes empty.
        #
        # The opening two lines must stay byte-identical to
        # INTERVIEW_PROMPT_PREFIX in app/api/simulation.py, trailing space
        # included. They are a duplicated literal, not a shared constant, so
        # that services does not import from the api layer; the endpoint
        # prepends its own copy unless the prompt already startswith() it, so
        # any drift here makes it prepend the prefix a second time.
        INTERVIEW_PROMPT_PREFIX = (
            "Answer me directly in text, drawing on your persona and all of your past "
            "memories and actions. Do not call any tools. "
            "Answer format:\n"
            "1. Reply in plain natural language\n"
            "2. Do not return JSON or a tool-call payload\n"
            "3. Do not use Markdown headings such as #, ## or ###\n"
            "4. Answer the questions in order, and start each answer with "
            "\"Question N:\", where N is the question number\n"
            "5. Separate consecutive answers with a blank line\n"
            "6. Give substantive answers: at least two or three sentences each\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"

        # Step 4: call the interview API; omitting platform interviews both
        try:
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt
                    # No platform, so the API interviews on twitter and reddit.
                })
            
            logger.info(t("console.callingBatchInterviewApi", count=len(interviews_request)))
            
            # Interview on both platforms, which needs a longer timeout.
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,
                timeout=180.0
            )
            
            logger.info(t("console.interviewApiReturned", count=api_result.get('interviews_count', 0), success=api_result.get('success')))
            
            # Surface an API-level failure as the interview summary.
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "Unknown error")
                logger.warning(t("console.interviewApiReturnedFailure", error=error_msg))
                result.summary = (
                    f"Failed to call the interview API: {error_msg}. "
                    "Check that the OASIS simulation environment is running."
                )
                return result

            # Step 5: turn the API response into AgentInterview objects.
            # Dual-platform responses are keyed "twitter_0", "reddit_0", and so on.
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "Unknown")
                agent_bio = agent.get("bio", "")

                # Both platforms answered the same prompt.
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # Unwrap a tool-call JSON envelope if the agent emitted one.
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # Both platform labels are always emitted, so the report UI can
                # split the answer even when one platform stayed silent.
                twitter_text = twitter_response if twitter_response else "(No response from this platform)"
                reddit_text = reddit_response if reddit_response else "(No response from this platform)"
                response_text = f"[Twitter Response]\n{twitter_text}\n\n[Reddit Response]\n{reddit_text}"

                # Pull the key quotes out of both platforms' answers.
                combined_responses = f"{twitter_response} {reddit_response}"

                # Strip headings, tool-call envelopes, Markdown rules, the
                # "Question N:" answer prefix the prompt mandates, and the
                # platform labels.
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = _QUESTION_PREFIX_RE.sub('', clean_text)
                clean_text = re.sub(r'\[(?:Twitter|Reddit) Response\]\s*', '', clean_text)

                # Strategy 1: keep whole sentences with something in them.
                # Bounds are in words, not characters - see _MIN_QUOTE_WORDS.
                sentences = _split_sentences(clean_text)
                meaningful = [
                    s for s in sentences
                    if _MIN_QUOTE_WORDS <= len(s.split()) <= _MAX_QUOTE_WORDS
                    and not re.match(r'^[\s\W]+', s)
                    and not s.startswith(('{', 'Question'))
                ]
                # Stable sort, so equally scored quotes keep answer order.
                meaningful.sort(key=_key_quote_score, reverse=True)
                key_quotes = [
                    s if s.endswith(('.', '!', '?')) else s + "."
                    for s in meaningful[:3]
                ]

                # Strategy 2: fall back to correctly paired quotation marks.
                if not key_quotes:
                    paired = re.findall(r'"([^"\n]{15,100})"', clean_text)
                    paired += re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[\s,;:.]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # The simulation environment is not running.
            logger.warning(t("console.interviewApiCallFailed", error=e))
            result.summary = (
                f"The interview failed: {str(e)}. The simulation environment "
                "may have shut down; make sure OASIS is still running."
            )
            return result
        except Exception as e:
            logger.error(t("console.interviewApiCallException", error=e))
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"The interview failed: {str(e)}"
            return result

        # Step 6: summarise the round
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """Unwrap an agent reply that arrived inside a tool-call JSON envelope."""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """Load the agent profiles written for one simulation."""
        import os
        import csv

        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # Prefer the Reddit JSON profiles.
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        
        # Fall back to the Twitter CSV profiles.
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Normalise the CSV row onto the profile shape.
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "Unknown"
                        })
                logger.info(t("console.loadedTwitterProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readTwitterProfilesFailed", error=e))
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """Ask the LLM which agents to interview.

        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: the chosen profiles in full
                - selected_indices: their indices, as the interview API wants
                - reasoning: why the LLM chose them
        """

        # The LLM sees a trimmed summary of each profile, not the whole file.
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "Unknown"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """You are an expert interview producer. Given an interview requirement, pick the agents worth interviewing from the list of simulated agents.

Selection criteria:
1. The agent\'s identity or profession is relevant to the interview topic
2. The agent is likely to hold a distinctive or valuable view
3. The selection covers a range of perspectives: supportive, opposed, neutral and expert
4. Agents directly involved in the event come first

Return JSON:
{
    "selected_indices": [indices of the chosen agents],
    "reasoning": "why these agents were chosen"
}"""

        user_prompt = f"""Interview requirement:
{interview_requirement}

Simulation background:
{simulation_requirement if simulation_requirement else "Not provided"}

Available agents ({len(agent_summaries)} in total):
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

Choose at most {max_agents} agents to interview and explain the choice."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "Selected automatically by relevance")

            # Resolve the indices back to full profiles, dropping bad ones.
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            # Fall back to the first N profiles.
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "Selected with the default strategy"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """Ask the LLM for the interview questions."""

        agent_roles = [a.get("profession", "Unknown") for a in selected_agents]

        system_prompt = """You are an experienced journalist. Given an interview requirement, write three to five probing interview questions.

Requirements:
1. Ask open questions that invite a detailed answer
2. Write questions different roles would answer differently
3. Cover facts, opinions and feelings
4. Keep the wording natural, as in a real interview
5. Keep each question under 30 words and to the point
6. Ask the question directly, with no background or prefix

Return JSON: {"questions": ["first question", "second question", ...]}"""

        user_prompt = f"""Interview requirement: {interview_requirement}

Simulation background: {simulation_requirement if simulation_requirement else "Not provided"}

Roles being interviewed: {', '.join(agent_roles)}

Write three to five interview questions."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get(
                "questions",
                [f"What is your view on {interview_requirement}?"]
            )

        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return [
                f"What is your view on {interview_requirement}?",
                "How does this affect you, or the group you speak for?",
                "What do you think should be done about it?"
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """Ask the LLM to summarise the interview round."""

        if not interviews:
            return "No interviews were completed."

        interview_texts = []
        for interview in interviews:
            interview_texts.append(
                f"[{interview.agent_name} ({interview.agent_role})]\n{interview.response[:500]}"
            )

        system_prompt = """You are an experienced news editor. Write a summary of what the interviewees said.

Requirements:
1. Draw out the main view each side holds
2. Name the points they agree on and the points they do not
3. Highlight the quotes worth keeping
4. Stay objective; do not take a side
5. Keep the summary under 600 words

Formatting rules, which must be followed:
- Write plain-text paragraphs separated by blank lines
- Do not use Markdown headings such as #, ## or ###
- Do not use horizontal rules such as --- or ***
- Use quotation marks "" when quoting interviewees
- **Bold** may be used for key terms; no other Markdown"""

        user_prompt = f"""Interview topic: {interview_requirement}

Interview transcript:
{"".join(interview_texts)}

Write the interview summary."""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary
            
        except Exception as e:
            logger.warning(t("console.generateInterviewSummaryFailed", error=e))
            # Fall back to naming the interviewees.
            return (
                f"{len(interviews)} interviewees took part: "
                + ", ".join([i.agent_name for i in interviews])
            )
