"""
ZepZep Retrieval Tool Service
Encapsulates graph search,, node reading,, edge query, and other tools, for use by the Report Agent

Core retrieval tools ((optimized):): 
1. InsightForge (InsightForge (deep insight retrieval) -)- the most powerful hybrid retrieval,, automatically generates sub-questions and performs multi-dimensional retrieval
2. PanoramaSearch (Broad search)- get the full picture,, including expired content
3. QuickSearch (Simple search)- quick retrieval
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

try:
    from zep_cloud.client import Zep  # noqa: F811
except ImportError:
    class Zep:  # type: ignore[no-redef]
        def __init__(self, *a, **kw): pass
        class graph:
            def search(self, **kw): raise NotImplementedError("zep-cloud not installed; use graphiti_service")
            class node:
                def get(self, **kw): raise NotImplementedError("zep-cloud not installed; use graphiti_service")

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.locale import get_locale, t
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges

logger = get_logger('mirofish.zep_tools')


@dataclass
class SearchResult:
    """Search result"""
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
        """Convert to text format, for LLM understanding"""
        text_parts = [f"Search query: {self.query}", f"Found {self.total_count} related items of information"]
        
        if self.facts:
            text_parts.append("\n### Related facts:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """Node information"""
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
        """Convert to text format"""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "Unknown type")
        return f"Entity: {self.name} (Type: {entity_type})\nSummary: {self.summary}"


@dataclass
class EdgeInfo:
    """Edge information"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # Temporal information
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
        """Convert to text format"""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"Relation: {source} --[{self.name}]--> {target}\nfact: {self.fact}"
        
        if include_temporal:
            valid_at = self.valid_at or "unknown"
            invalid_at = self.invalid_at or "present"
            base_text += f"\nValidity: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (expired: {self.expired_at})"
        
        return base_text
    
    @property
    def is_expired(self) -> bool:
        """Whether expired"""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """Whether invalidated"""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    Deep insight retrieval result (InsightForge) (InsightForge)
    Contains results from multiple sub-questions,, plus a comprehensive analysis
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # Per-dimension retrieval results
    semantic_facts: List[str] = field(default_factory=list)  # semantic search results
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # entity insights
    relationship_chains: List[str] = field(default_factory=list)  # relationship chains
    
    # Statistics
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
        """Convert to detailed text format, for LLM understanding"""
        text_parts = [
            f"## Deep analysis of future prediction",
            f"Analysis question: {self.query}",
            f"Prediction scenario: {self.simulation_requirement}",
            f"\n### Prediction data statistics",
            f"- Related prediction facts: {self.total_facts}items",
            f"- Involved entities: {self.total_entities}",
            f"- relationship chains: {self.total_relationships}items"
        ]
        
        # sub-question
        if self.sub_queries:
            text_parts.append(f"\n### Analyzed sub-questions")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        
        # semantic search results
        if self.semantic_facts:
            text_parts.append(f"\n### [Key facts](Please quote the original text in the report)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # entity insights
        if self.entity_insights:
            text_parts.append(f"\n### [Core entities]")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', 'unknown')}** ({entity.get('type', 'Entity')})")
                if entity.get('summary'):
                    text_parts.append(f"  Summary: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  Related facts: {len(entity.get('related_facts', []))}items")
        
        # relationship chains
        if self.relationship_chains:
            text_parts.append(f"\n### [relationship chains]")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    Broad search result (Panorama)
    Contains all related information,, including expired content
    """
    query: str
    
    # All nodes
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # All edges (including expired ones)
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # Current valid facts
    active_facts: List[str] = field(default_factory=list)
    # expired/invalidated facts (history records)
    historical_facts: List[str] = field(default_factory=list)
    
    # Statistics
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
        """Convert to text format (complete version,, not truncated)"""
        text_parts = [
            f"## Broad search result (future panoramic view)",
            f"Query: {self.query}",
            f"\n### Statistics",
            f"- Total nodes: {self.total_nodes}",
            f"- Total edges: {self.total_edges}",
            f"- Current valid facts: {self.active_count}items",
            f"- History/expired facts: {self.historical_count}items"
        ]
        
        # Current valid facts (Complete output,, not truncated)
        if self.active_facts:
            text_parts.append(f"\n### [Current valid facts](original simulation result text)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # History/expired facts (Complete output,, not truncated)
        if self.historical_facts:
            text_parts.append(f"\n### [History/expired facts](evolution process record)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Key entities (Complete output,, not truncated)
        if self.all_nodes:
            text_parts.append(f"\n### [Involved entities]")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """Single Agent interview result"""
    agent_name: str
    agent_role: str  # Role type (e.g., Student, Teacher, Media, etc.)
    agent_bio: str  # Bio
    question: str  # Interview question
    response: str  # Interview answer
    key_quotes: List[str] = field(default_factory=list)  # Key quotes
    
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
        # Display the complete agent_bio,, not truncated
        text += f"_Bio: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**Key quotes:**\n"
            for quote in self.key_quotes:
                # Clean various quotation marks
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # Remove leading punctuation
                while clean_quote and clean_quote[0] in ', ,; ;: :, . !?\n\r\t ':
                    clean_quote = clean_quote[1:]
                # Filter junk content containing question numbers (question 1-9)
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # Truncate overly long content (truncate by sentence period, not by hard truncation)
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    Interview result (Interview) (Interview)
    Contains interview answers from multiple simulated Agents
    """
    interview_topic: str  # Interview topic
    interview_questions: List[str]  # Interview question list
    
    # Selected Agents for interview
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # Interview answers from each Agent
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # Reasoning for selecting Agents
    selection_reasoning: str = ""
    # Integrated interview summary
    summary: str = ""
    
    # Statistics
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
        """Convert to detailed text format, for LLM understanding and report reference"""
        text_parts = [
            "## In-depth interview report",
            f"**Interview topic:** {self.interview_topic}",
            f"**Number of interviewees:** {self.interviewed_count} / {self.total_agents} simulated Agents",
            "\n### Reasoning for interviewee selection",
            self.selection_reasoning or " ((automatic selection))",
            "\n---",
            "\n### Interview transcript",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### Interview #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append(" ((no interview records))\n\n---")

        text_parts.append("\n### Interview summary and core viewpoints")
        text_parts.append(self.summary or " ((no summary))")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    ZepZep Retrieval Tool Service
    
    [Core retrieval tools - (optimized):]
    1. insight_forge - InsightForge (deep insight retrieval) - (most powerful, automatically generates sub-questions, multi-dimensional retrieval)
    2. panorama_search - Broad search (get the full picture,, including expired content)
    3. quick_search - Simple search (quick retrieval)
    4. interview_agents - In-depth interview (interview simulated Agents, get multi-perspective views)
    
    [Basic tools]
    - search_graph - Graph semantic search
    - get_all_nodes - get all graph nodes
    - get_all_edges - get all graph edges (including temporal information)
    - get_node_detail - Get node detailed information
    - get_node_edges - Get edges related to the node
    - get_entities_by_type - Get entities by type
    - get_entity_summary - get entity's relationship summary
    """
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key  # kept for signature compat; no longer required
        from .graphiti_service import get_graphiti_adapter
        self.client = get_graphiti_adapter()
        # LLMClient used forInsightForgegenerating sub-questions
        self._llm_client = llm_client
        logger.info(t("console.zepToolsInitialized"))
    
    @property
    def llm(self) -> LLMClient:
        """Lazily initializeLLMclient"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """API call with retry mechanismAPIcall"""
        max_retries = max_retries or self.MAX_RETRIES
        last_exception = None
        delay = self.RETRY_DELAY
        
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logger.warning(
                        t("console.zepRetryAttempt", operation=operation_name, attempt=attempt + 1, error=str(e)[:100], delay=f"{delay:.1f}")
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(t("console.zepAllRetriesFailed", operation=operation_name, retries=max_retries, error=str(e)))
        
        raise last_exception
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Graph semantic search
        
        Use hybrid search (semantic+BM25)search related information in the graph.
        If the Zep Cloud search API is unavailable, fall back to local keyword matching.
        
        Args:
            graph_id: Graph ID (Standalone Graph)
            query: Search query
            limit: Number of returned results
            scope: Search scope, "edges"  or  "nodes"
            
        Returns:
            SearchResult: Search result
        """
        logger.info(t("console.graphSearch", graphId=graph_id, query=query[:50]))
        
        # Try to use Graphiti search
        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                ),
                operation_name=t("console.graphSearchOp", graphId=graph_id)
            )
            
            facts = []
            edges = []
            nodes = []
            
            # Parse edge search results
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
            
            # Parse node search results
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # Node summaries also count as facts
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
            logger.warning(t("console.zepSearchApiFallback", error=str(e)))
            # Fallback: use local keyword matching search
            return self._local_search(graph_id, query, limit, scope)
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Local keyword matching search (as a fallback for the Zep Search API)
        
        Get all edges/nodes, then perform keyword matching locally
        
        Args:
            graph_id: Graph ID
            query: Search query
            limit: Number of returned results
            scope: Search scope
            
        Returns:
            SearchResult: Search result
        """
        logger.info(t("console.usingLocalSearch", query=query[:30]))
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # Extract query keywords (simple tokenization)
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace(', ', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """Calculate the match score between text and query"""
            if not text:
                return 0
            text_lower = text.lower()
            # Exact match of query
            if query_lower in text_lower:
                return 100
            # keyword matching
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # Get all edges and match
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # Sort by score
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
                # Get all nodes and match
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
        """
        Get all nodes of the graph (retrieved with pagination)

        Args:
            graph_id: Graph ID

        Returns:
            Node list
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
        """
        Get all edges of the graph (retrieved with pagination, include temporal information)

        Args:
            graph_id: Graph ID
            include_temporal: Whether to include temporal information (default True)

        Returns:
            Edge list (containing created_at, valid_at, invalid_at, expired_at)
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

            # Add temporal information
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(t("console.fetchedEdges", count=len(result)))
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        Get detailed information of a single node
        
        Args:
            node_uuid: Node UUID
            
        Returns:
            Node information or None
        """
        logger.info(t("console.fetchingNodeDetail", uuid=node_uuid[:8]))
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.get_node(node_uuid=node_uuid),
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
        except Exception as e:
            logger.error(t("console.fetchNodeDetailFailed", error=str(e)))
            return None
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        Get all edges related to a node
        
        By getting all edges of the graph,, then filtering out edges related to the specified node
        
        Args:
            graph_id: Graph ID
            node_uuid: Node UUID
            
        Returns:
            Edge list
        """
        logger.info(t("console.fetchingNodeEdges", uuid=node_uuid[:8]))
        
        try:
            # Get all graph edges, then filter
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                # Check if an edge is related to the specified node (as source or target)
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(t("console.foundNodeEdges", count=len(result)))
            return result
            
        except Exception as e:
            logger.warning(t("console.fetchNodeEdgesFailed", error=str(e)))
            return []
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        Get entities by type
        
        Args:
            graph_id: Graph ID
            entity_type: Entity type (e.g., Student, PublicFigure, etc.)
            
        Returns:
            List of entities matching the type
        """
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # Check whether labels contain the specified type
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(t("console.foundEntitiesByType", count=len(filtered), type=entity_type))
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Get the relationship summary of the specified entity
        
        Search all information related to the entity,, and generate a summary
        
        Args:
            graph_id: Graph ID
            entity_name: Entity name
            
        Returns:
            Entity summary information
        """
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        
        # First search for information related to the entity
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # Try to find the entity among all nodes
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # Pass in graph_id parameter
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)
        
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }
    
    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        Get statistics of the graph
        
        Args:
            graph_id: Graph ID
            
        Returns:
            Statistics
        """
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # Count entity type distribution
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # Count relationship type distribution
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
        """
        Get context information related to the simulation
        
        Comprehensively search all information related to the simulation requirement
        
        Args:
            graph_id: Graph ID
            simulation_requirement: Simulation requirement description
            limit: Quantity limit per type of information
            
        Returns:
            Simulation context information
        """
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        
        # Search for information related to the simulation requirement
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # Get graph statistics
        stats = self.get_graph_statistics(graph_id)
        
        # Get all entity nodes
        all_nodes = self.get_all_nodes(graph_id)
        
        # Filter entities with actual types (non-pure Entity nodes)
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
            "entities": entities[:limit],  # limit quantity
            "total_entities": len(entities)
        }
    
    # ========== Core retrieval tools ((optimized):) ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
        [InsightForge - InsightForge (deep insight retrieval) -]
        
        The most powerful hybrid retrieval function,, automatically decomposes questions and performs multi-dimensional retrieval:: 
        1. useLLMdecompose the question into multiple sub-questions
        2. perform semantic search for each sub-question
        3. extract related entities and get their detailed information
        4. trace relationship chains
        5. integrate all results,, generate deep insights
        
        Args:
            graph_id: Graph ID
            query: user question
            simulation_requirement: Simulation requirement description
            report_context: report context (optional, used for more accurate sub-question generation)
            max_sub_queries: Maximum number of sub-questions
            
        Returns:
            InsightForgeResult: Deep insight retrieval result (InsightForge)
        """
        logger.info(t("console.insightForgeStart", query=query[:50]))
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )
        
        # Step 1: useLLMgenerating sub-questions
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(t("console.generatedSubQueries", count=len(sub_queries)))
        
        # Step 2: perform semantic search for each sub-question
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
        
        # Also search for the original question
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
        
        # Step 3: Extract related entities from edgesUUID, only get information for these entities (do not get all nodes)
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        # Get details of all related entities (no quantity limit,, Complete output,)
        entity_insights = []
        node_map = {}  # Used for subsequent relationship chain construction
        
        for uuid in list(entity_uuids):  # Process all entities,, not truncated
            if not uuid:
                continue
            try:
                # Get information for each related node individually
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                    
                    # Get all facts related to the entity (not truncated)
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # Complete output,, not truncated
                    })
            except Exception as e:
                logger.debug(f"Getting node {uuid} failed: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Step 4: Build all relationship chains (no quantity limit,)
        relationship_chains = []
        for edge_data in all_edges:  # Process all edges,, not truncated
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
        """
        useLLMgenerating sub-questions
        
        Decompose complex questions into multiple sub-questions that can be retrieved independently
        """
        system_prompt = """You are a professional question analysis expert.. Your task is to decompose a complex question into multiple sub-questions that can be independently observed in the simulation world.

Requirements: 
1. Each sub-question should be specific enough, so that related Agent behaviors or events can be found in the simulation world
2. Sub-questions should cover different dimensions of the original question (e.g., who, what, why, how, when, where)
3. Sub-questions should be related to the simulation scenario
4. Return in JSON format: {"sub_queries": ["sub-question 1", "sub-question 2", ...]}"""

        user_prompt = f"""Simulation requirement context: 
{simulation_requirement}

{f"report context: {report_context[:500]}" if report_context else ""}

Please decompose the following question into{max_queries}sub-questions: 
{query}

Return in JSON format sub-question list. """

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # Ensure it is a list of strings
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
            # Fallback: return variants based on the original question
            return [
                query,
                f"{query} 's main participants",
                f"{query} 's causes and impact",
                f"{query} 's development process"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """
        [PanoramaSearch - Broad search]
        
        Get a panoramic view,, including all related content and history/expired information: 
        1. Get all related nodes
        2. Get all edges (including expired/invalidated)
        3. Classify and organize current valid and historical information
        
        This tool is suitable for scenarios that need to understand the full picture of an event,, trace the evolution process. 
        
        Args:
            graph_id: Graph ID
            query: Search query (used for relevance ranking)
            include_expired: Whether to include expired content (default True)
            limit: Limit on number of returned results
            
        Returns:
            PanoramaResult: Broad search result
        """
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        
        result = PanoramaResult(query=query)
        
        # Get all nodes
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # Get all edges (include temporal information)
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # Classify facts
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # Add entity names to facts
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # Determine if expired/invalid
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # History/expired facts, add time marker
                valid_at = edge.valid_at or "unknown"
                invalid_at = edge.invalid_at or edge.expired_at or "unknown"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # Current valid facts
                active_facts.append(edge.fact)
        
        # Perform relevance sorting based on query
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace(', ', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # Sort and limit quantity
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
        """
        [QuickSearch - Simple search]
        
        Quick,, lightweight retrieval tool:: 
        1. Directly call Zep semantic search
        2. return the most relevant results
        3. Suitable for simple,, direct retrieval needs
        
        Args:
            graph_id: Graph ID
            query: Search query
            limit: Number of returned results
            
        Returns:
            SearchResult: Search result
        """
        logger.info(t("console.quickSearchStart", query=query[:50]))
        
        # Directly call the existingsearch_graphmethod
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
        """
        [InterviewAgents - In-depth interview]
        
        Call the real OASIS interview API,, interview running Agents in the simulation:: 
        1. Automatically read persona files,, understand all simulated Agents
        2. Use LLM to analyze interview requirements,, intelligently select the most relevant Agents
        3. Use LLM to generate interview questions
        4. Call the /api/simulation/interview/batch interface for real interviews ((both platforms simultaneously))
        5. Integrate all interview results,, generate interview report
        
        [Important]this feature requires the simulation environment to be running ((OASIS environment not closed))
        
        [Use cases]
        - Need to understand event views from different role perspectives
        - Need to collect opinions and views from multiple parties
        - Need to get real answers from simulated Agents ((not LLM simulation))
        
        Args:
            simulation_id: Simulation ID (used to locate persona files and call the interview API)
            interview_requirement: Interview requirement description (unstructured, e.g. "understand students' views on the event")
            simulation_requirement: Simulation requirement context (optional)
            max_agents: Maximum number of Agents to interview
            custom_questions: Custom interview questions (optional, if not provided, auto-generate)
            
        Returns:
            InterviewResult: Interview result (Interview)
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Step 1: Read persona file
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(t("console.profilesNotFound", simId=simulation_id))
            result.summary = "No interviewable Agent persona files found"
            return result
        
        result.total_agents = len(profiles)
        logger.info(t("console.loadedProfiles", count=len(profiles)))
        
        # Step 2: Use LLM to select Agents to interview (return agent_id list)
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(t("console.selectedAgentsForInterview", count=len(selected_agents), indices=selected_indices))
        
        # Step 3: Generate interview questions (if not provided)
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(t("console.generatedInterviewQuestions", count=len(result.interview_questions)))
        
        # merge questions into one interview prompt
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # Add optimization prefix, constrain Agent reply format
        INTERVIEW_PROMPT_PREFIX = (
            "You are being interviewed. Please combine your persona, all past memories and actions, "
            "and directly answer the following questions in plain text.\n"
            "Reply requirements:\n"
            "1. Directly answer in natural language, do not call any tools\n"
            "2. do not return JSON format or tool call format\n"
            "3. do not use Markdown headings (e.g. #, ##, ###)\n"
            "4. Answer each question in order by question number, each answer starts with 'Question X:' (X is the question number)\n"
            "5. Separate answers for each question with a blank line\n"
            "6. Answers must have substantial content, each question should be answered with at least 2-3 sentences\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Step 4: Call the real interview API (do not specify platform, default: both platforms simultaneously)
        try:
            # Build the batch interview list (do not specify platform, both-platform interview)
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # use the optimized prompt
                    # do not specify platform, the API will interview on both twitter and reddit
                })
            
            logger.info(t("console.callingBatchInterviewApi", count=len(interviews_request)))
            
            # Call the SimulationRunner batch interview method (do not pass platform, both-platform interview)
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # do not specify platform, both-platform interview
                timeout=180.0   # both platforms need a longer timeout
            )
            
            logger.info(t("console.interviewApiReturned", count=api_result.get('interviews_count', 0), success=api_result.get('success')))
            
            # Check whether the API call succeeded
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "Unknown error")
                logger.warning(t("console.interviewApiReturnedFailure", error=error_msg))
                result.summary = f"Interview API call failed: {error_msg}. Please check the OASIS simulation environment status. "
                return result
            
            # Step 5: Parse API return result,, build AgentInterview object
            # Both-platform mode return format: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "unknown")
                agent_bio = agent.get("bio", "")
                
                # get the Agent's interview results on both platforms
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # Clean possible tool call JSON wrappers
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # Always output both-platform markers
                twitter_text = twitter_response if twitter_response else " (No reply from this platform)"
                reddit_text = reddit_response if reddit_response else " (No reply from this platform)"
                response_text = f"[Twitterplatform reply]\n{twitter_text}\n\n[Redditplatform reply]\n{reddit_text}"

                # Extract key quotes (from the replies of both platforms)
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # Clean response text: remove markers, numbers, Markdown, and other interference
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'Question\s*\d+\s*[: ：]\s*', '', clean_text)
                clean_text = re.sub(r'[[^]]+]', '', clean_text)

                # Strategy 1 (main): Extract complete sentences with substantial content
                sentences = re.split(r'[. !?]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W, ,; ;: :, ]+', s.strip())
                    and not s.strip().startswith(('{', 'Question'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + ". " for s in meaningful[:3]]

                # Strategy 2 (supplementary): correctly paired Chinese quotation marks "" wrapping long text
                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[, ,; ;: :, ]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # expand bio length limit
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # Simulation environment is not running
            logger.warning(t("console.interviewApiCallFailed", error=e))
            result.summary = f"Interview failed: {str(e)}. simulation environment may have been closed, Please ensure the OASIS environment is running. "
            return result
        except Exception as e:
            logger.error(t("console.interviewApiCallException", error=e))
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"Error occurred during interview process: {str(e)}"
            return result
        
        # Step 6: Generate interview summary
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """Clean JSON tool call wrappers in Agent replies,, extract actual content"""
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
        """Load the simulation Agent persona file"""
        import os
        import csv
        
        # Build persona file path
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # Prefer to read Reddit JSON format
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        
        # Try to read Twitter CSV format
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert CSV format to unified format
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "unknown"
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
        """
        Use LLM to select Agents to interview
        
        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: complete information list of selected Agents
                - selected_indices: index list of selected Agents (used for API calls)
                - reasoning: Selection reasoning
        """
        
        # Build Agent summary list
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "unknown"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)
        
        system_prompt = """You are a professional interview planning expert.. Your task is to select the most suitable interview subjects, from the simulation Agent list based on interview requirements.

Selection criteria: 
1. Agent identity/profession is related to the interview topic
2. Agent may hold unique or valuable viewpoints
3. Select diverse perspectives (e.g., supporters, opponents, neutrals, professionals, etc.)
4. Prefer roles directly related to the event

Return in JSON format: 
{
    "selected_indices": [index list of selected Agents],
    "reasoning": "Selection reasoning explanation"
}"""

        user_prompt = f"""Interview requirement: 
{interview_requirement}

Simulation context: 
{simulation_requirement if simulation_requirement else "not provided"}

Selectable Agent list (total{len(agent_summaries)}): 
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

Please select at most{max_agents}most suitable Agents to interview, and explain the selection reasoning. """

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "Automatically selected based on relevance")
            
            # Get complete information of selected Agents
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            # Fallback: select the first N
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "Use default selection strategy"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """Use LLM to generate interview questions"""
        
        agent_roles = [a.get("profession", "unknown") for a in selected_agents]
        
        system_prompt = """You are a professional journalist/interviewer.. Based on interview requirements,, generate 3-5 in-depth interview questions.

Question requirements: 
1. open-ended questions,, encourage detailed answers
2. different roles may have different answers
3. cover multiple dimensions such as facts, opinions, feelings
4. Natural language,, like a real interview
5. each question within 50 words,, concise and clear
6. ask directly,, do not include background explanation or prefix

Return in JSON format: {"questions": ["question 1", "question 2", ...]}"""

        user_prompt = f"""Interview requirement: {interview_requirement}

Simulation context: {simulation_requirement if simulation_requirement else "not provided"}

Interviewee roles: {', '.join(agent_roles)}

Please generate 3-5 interview questions. """

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get("questions", [f"Regarding{interview_requirement}, what are your views?"])
            
        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return [
                f"Regarding{interview_requirement}, what is your opinion?",
                "What impact does this matter have on you or the group you represent?",
                "What do you think should be done to resolve or improve this issue?"
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """Generate interview summary"""
        
        if not interviews:
            return "No interviews completed"
        
        # Collect all interview content
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"[{interview.agent_name} ({interview.agent_role})]\n{interview.response[:500]}")
        
        quote_instruction = "use Chinese quotation marks "" when quoting interviewees" if get_locale() == 'zh' else 'Use quotation marks "" when quoting interviewees'
        system_prompt = f"""You are a professional news editor.. Please generate an interview summary, based on the answers from multiple interviewees.

Summary requirements: 
1. Extract the main viewpoints of each party
2. Point out consensus and divergence of viewpoints
3. Highlight valuable quotes
4. Objective and neutral,, do not favor any party
5. limit to 1000 words

Format constraints ((must follow)): 
- use plain text paragraphs,, separate different sections with blank lines
- do not use Markdown headings (e.g. #, ##, ###)
- do not use dividers (e.g. ---, ***)
- {quote_instruction}
- may use**bold**to mark keywords,, but do not use other Markdown syntax"""

        user_prompt = f"""Interview topic: {interview_requirement}

Interview content: 
{"".join(interview_texts)}

Please generate interview summary. """

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
            # Fallback: simple concatenation
            return f"Interviewed a total of{len(interviews)}interviewees,, including: " + ", ".join([i.agent_name for i in interviews])
