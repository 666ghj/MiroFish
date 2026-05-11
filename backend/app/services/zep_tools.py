"""
Dịch vụ cung cấp các công cụ tìm kiếm trên nền tảng Zep Cloud.
Đóng gói các công cụ tìm kiếm đồ thị (graph search), đọc thông tin node, truy vấn cạnh (edge), v.v., để Report Agent sử dụng.

Các công cụ tìm kiếm cốt lõi (sau khi tối ưu hóa):
1. InsightForge (Tìm kiếm chiều sâu) - Công cụ tìm kiếm kết hợp mạnh mẽ nhất, tự động tạo các câu hỏi phụ và tìm kiếm đa chiều.
2. PanoramaSearch (Tìm kiếm theo chiều rộng) - Lấy toàn cảnh thông tin, bao gồm cả nội dung đã hết hạn (expired).
3. QuickSearch (Tìm kiếm cơ bản) - Tìm kiếm nhanh chóng với truy vấn đơn giản.
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from zep_cloud.client import Zep

from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges

logger = get_logger('mirofish.zep_tools')


@dataclass
class SearchResult:
    """Kết quả tìm kiếm cơ bản."""
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
        """Chuyển đổi kết quả sang định dạng văn bản (text) để cho LLM dễ dàng hiểu và xử lý."""
        text_parts = [f"Search query: {self.query}", f"Found {self.total_count} related info items"]
        
        if self.facts:
            text_parts.append("\n### Related facts:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """Thông tin chi tiết về một Node (Thực thể) trong đồ thị tri thức."""
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
        """Chuyển đổi thông tin Node sang định dạng văn bản để hiển thị hoặc đưa cho LLM."""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "Unknown type")
        return f"Entity: {self.name} (Type: {entity_type})\nSummary: {self.summary}"


@dataclass
class EdgeInfo:
    """Thông tin chi tiết về một Cạnh (mối quan hệ/edge) nối giữa hai Node trong đồ thị."""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # Thông tin thời gian của sự kiện, tính hợp lệ theo thời gian
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
        """Chuyển đổi thông tin mối quan hệ (Cạnh/Edge) sang dạng văn bản.
        Nếu include_temporal=True, sẽ bao gồm thông tin về dòng thời gian của mối quan hệ."""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"Relationship: {source} --[{self.name}]--> {target}\nFact: {self.fact}"
        
        if include_temporal:
            valid_at = self.valid_at or "Unknown start"
            invalid_at = self.invalid_at or "Until now"
            base_text += f"\nTime validity: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (Expired at: {self.expired_at})"
        
        return base_text
    
    @property
    def is_expired(self) -> bool:
        """Kiểm tra mối quan hệ này đã hết hạn (không còn chính xác theo thực tế hiện tại) hay chưa."""
        return self.expired_at is not None
    
    @property
    def is_invalid(self) -> bool:
        """Kiểm tra mối quan hệ này đã bắt đầu bị vô hiệu hóa hay chưa."""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    Kết quả của truy vấn InsightForge (Tìm kiếm chiều sâu).
    Bao gồm kết quả từ nhiều câu hỏi phụ (sub_queries) và các phân tích tổng hợp.
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    
    # Kết quả tìm kiếm từ nhiều góc nhìn khác nhau (đa chiều)
    semantic_facts: List[str] = field(default_factory=list)  # Kết quả tìm kiếm theo ngữ nghĩa (semantic search)
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # Phân tích sâu về các thực thể (insight)
    relationship_chains: List[str] = field(default_factory=list)  # Chuỗi mối quan hệ nối tiếp nhau (relationship chains)
    
    # Thông kê kết quả
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
        """Chuyển đổi sang định dạng văn bản chi tiết để cung cấp ngữ cảnh cho LLM"""
        text_parts = [
            f"## Deep Analysis for Future Simulation",
            f"Analysis query: {self.query}",
            f"Simulation scenario: {self.simulation_requirement}",
            f"\n### Simulation Data Statistics",
            f"- Related simulation facts: {self.total_facts} items",
            f"- Entities involved: {self.total_entities}",
            f"- Relationship chains: {self.total_relationships}"
        ]
        
        # Các câu hỏi phụ (sub queries) được sinh ra để truy vấn sâu hơn
        if self.sub_queries:
            text_parts.append(f"\n### Analyzed sub-queries")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        
        # Kết quả tìm kiếm theo ngữ nghĩa
        if self.semantic_facts:
            text_parts.append(f"\n### 【Key Facts】(Please cite these original texts in the report)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Thông tin sâu sắc về thực thể
        if self.entity_insights:
            text_parts.append(f"\n### 【Core Entities】")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', 'Unknown')}** ({entity.get('type', 'Entity')})")
                if entity.get('summary'):
                    text_parts.append(f"  Summary: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  Related facts: {len(entity.get('related_facts', []))} items")
        
        # Chuỗi mối quan hệ (graph paths)
        if self.relationship_chains:
            text_parts.append(f"\n### 【Relationship Chains】")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    Kết quả tìm kiếm theo chiều rộng (Panorama search).
    Chứa toàn bộ thông tin liên quan từ đồ thị, bao gồm cả những sự kiện/relatioships đã hết hạn (expired).
    """
    query: str
    
    # Toàn bộ Node tìm được
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # Toàn bộ Edge tìm được (kể cả đã hết hạn)
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # Các sự kiện/thực trạng đang hoạt động hợp lệ hiện tại
    active_facts: List[str] = field(default_factory=list)
    # Các sự kiện thực trạng đã hết hạn/không còn hiệu lực (Dữ liệu lịch sử)
    historical_facts: List[str] = field(default_factory=list)
    
    # Thống kê
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
        """Chuyển đổi sang định dạng văn bản (phiên bản đầy đủ, không bị cắt bớt)"""
        text_parts = [
            f"## Panorama Search Results (Future Panorama View)",
            f"Query: {self.query}",
            f"\n### Statistics",
            f"- Total nodes: {self.total_nodes}",
            f"- Total edges: {self.total_edges}",
            f"- Currently valid facts: {self.active_count} items",
            f"- Historical/expired facts: {self.historical_count} items"
        ]
        
        # Các sự kiện hợp lệ hiện tại (xuất ra đầy đủ, không cắt bớt)
        if self.active_facts:
            text_parts.append(f"\n### 【Currently Valid Facts】(Simulated Result Text)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Sự kiện lịch sử/đã hết hạn (xuất ra đầy đủ, không cắt bớt)
        if self.historical_facts:
            text_parts.append(f"\n### 【Historical/Expired Facts】(Evolution Records)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")
        
        # Các thực thể cốt lõi (xuất ra đầy đủ, không cắt bớt)
        if self.all_nodes:
            text_parts.append(f"\n### 【Involved Entities】")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """Kết quả phỏng vấn của một Agent cá nhân"""
    agent_name: str
    agent_role: str  # Loại vai trò (ví dụ: Học sinh, Giáo viên, Truyền thông, v.v.)
    agent_bio: str  # Tiểu sử ngắn gọn
    question: str  # Câu hỏi phỏng vấn
    response: str  # Câu trả lời phỏng vấn
    key_quotes: List[str] = field(default_factory=list)  # Các câu trích dẫn quan trọng
    
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
        # Hiển thị bio đầy đủ, không cắt bớt
        text += f"_Bio: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**Key Quotes:**\n"
            for quote in self.key_quotes:
                # Làm sạch các loại dấu ngoặc kép
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # Bỏ các dấu chấm câu ở đầu chuỗi
                while clean_quote and clean_quote[0] in '，,；;：:、。！？\n\r\t ':
                    clean_quote = clean_quote[1:]
                # Bỏ qua nội dung rác chứa số câu hỏi (ví dụ: Câu hỏi 1-9)
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # Cắt bớt phần nội dung quá dài (Dựa vào dấu chấm câu chứ không cắt ngang chữ)
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
    Kết quả phỏng vấn các Agent giả lập.
    Chứa danh sách các câu trả lời phỏng vấn từ các tác nhân AI.
    """
    interview_topic: str  # Chủ đề phỏng vấn
    interview_questions: List[str]  # Danh sách các câu hỏi phỏng vấn
    
    # Danh sách các Agent được chọn để phỏng vấn
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # Bảng lưu kết quả trả lời của các Agent
    interviews: List[AgentInterview] = field(default_factory=list)
    
    # Nêu lý do chọn các Agent này
    selection_reasoning: str = ""
    # Bản tóm tắt lại nội dung sau cuộc phỏng vấn
    summary: str = ""
    
    # Thống kê
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
        """Chuyển đổi thành định dạng văn bản chi tiết để cung cấp cho LLM hoặc Report."""
        text_parts = [
            "## Deep Interview Report",
            f"**Interview Topic:** {self.interview_topic}",
            f"**Interview Count:** {self.interviewed_count} / {self.total_agents} simulated agents",
            "\n### Reasoning behind agent selection",
            self.selection_reasoning or "(Auto selection)",
            "\n---",
            "\n### Interview Transcripts",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### Interview #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("(No interview records)\n\n---")

        text_parts.append("\n### Interview Summary & Core Insights")
        text_parts.append(self.summary or "(No summary)")

        return "\n".join(text_parts)


class ZepToolsService:
    """
    Dịch vụ công cụ tìm kiếm Zep
    
    【Các công cụ tìm kiếm cốt lõi - Đã tối ưu hóa】
    1. insight_forge - Tìm kiếm chiều sâu (Mạnh nhất, tự động tạo câu hỏi phụ và tìm kiếm đa chiều)
    2. panorama_search - Tìm kiếm chiều rộng (Lấy toàn cảnh, bao gồm cả nội dung hết hạn)
    3. quick_search - Tìm kiếm cơ bản (Tìm kiếm nhanh với từ khóa)
    4. interview_agents - Phỏng vấn sâu (Phỏng vấn các Agent giả lập, thu thập góc nhìn đa chiều)
    
    【Các công cụ cơ bản】
    - search_graph - Tìm kiếm ngữ nghĩa trong graph
    - get_all_nodes - Lấy tất cả các nodes (thực thể) trong graph
    - get_all_edges - Lấy tất cả các edges (mối quan hệ) trong graph (bao gồm thông tin thời gian)
    - get_node_detail - Lấy chi tiết một node (thực thể)
    - get_node_edges - Lấy các mối quan hệ (edges) liên quan đến một node
    - get_entities_by_type - Phân loại và lấy các thực thể theo type
    - get_entity_summary - Lấy tóm tắt về các mối quan hệ của một thực thể
    """
    
    # Cấu hình retry khi gọi API lỗi
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    
    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")
        
        self.client = Zep(api_key=self.api_key)
        # LLM client được sử dụng bởi InsightForge để sinh ra các sub-queries
        self._llm_client = llm_client
        logger.info("ZepToolsService initialized successfully")
    
    @property
    def llm(self) -> LLMClient:
        """Khởi tạo muộn (lazy init) cho LLM client"""
        if self._llm_client is None:
            self._llm_client = LLMClient(
                component="zep_tools",
                metadata={
                    "phase": "zep_tools",
                },
            )
        return self._llm_client
    
    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """Cơ chế gọi hàm an toàn, tự động thử lại (retry) khi gặp lỗi."""
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
                        f"Zep {operation_name} attempt {attempt + 1} failed: {str(e)[:100]}, "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    logger.error(f"Zep {operation_name} failed after {max_retries} attempts: {str(e)}")
        
        raise last_exception
    
    def search_graph(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Tìm kiếm ngữ nghĩa trên Graph (Đồ thị tri thức)
        
        Sử dụng tìm kiếm lai (hybrid search: ngữ nghĩa + BM25) để tìm kiếm thông tin liên quan trong đồ thị.
        Nếu API search của Zep Cloud không khả dụng, sẽ fallback (hạ cấp) xuống tìm kiếm khớp từ khóa cục bộ.
        
        Args:
            graph_id: ID của đồ thị (Standalone Graph)
            query: Truy vấn tìm kiếm (Text)
            limit: Số lượng kết quả tối đa trả về
            scope: Phạm vi tìm kiếm, có thể là "edges" (cạnh/fact) hoặc "nodes" (thực thể)
            
        Returns:
            SearchResult: Đối tượng chứa kết quả tìm kiếm đã phân tích
        """
        logger.info(f"Graph search: graph_id={graph_id}, query={query[:50]}...")
        
        # Thử sử dụng API Zep Cloud Search
        try:
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(
                    graph_id=graph_id,
                    query=query,
                    limit=limit,
                    scope=scope,
                    reranker="cross_encoder"
                ),
                operation_name=f"Graph Search(graph={graph_id})"
            )
            
            facts = []
            edges = []
            nodes = []
            
            # Phân tích kết quả tìm kiếm cạnh (edges/relationships)
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
            
            # Phân tích kết quả tìm kiếm thực thể (nodes)
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # Phần tóm tắt (summary) của node cũng được coi là một fact
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
            
            logger.info(f"Search completed: Found {len(facts)} related facts")
            
            return SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            
        except Exception as e:
            logger.warning(f"Zep Search API failed, gracefully degrading to local search: {str(e)}")
            # Hạ cấp: Sử dụng tìm kiếm theo từ khóa cục bộ
            return self._local_search(graph_id, query, limit, scope)
    
    def _local_search(
        self, 
        graph_id: str, 
        query: str, 
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        Tìm kiếm khớp từ khóa cục bộ (Local keyword matching), một fallback strategy nếu API Zep Search lỗi.
        
        Sẽ lấy tất cả các cạnh/thực thể, sau đó so khớp từ khóa locally.
        
        Args:
            graph_id: ID của đồ thị
            query: Từ khóa truy vấn
            limit: Số lượng kết quả cực đại
            scope: Phạm vi tính toán tìm kiếm (nodes/edges/both)
            
        Returns:
            SearchResult: Kết quả của tìm kiếm mô phỏng cục bộ
        """
        logger.info(f"Using local search: query={query[:30]}...")
        
        facts = []
        edges_result = []
        nodes_result = []
        
        # Tách từ khóa khỏi truy vấn (chiến lược đơn giản)
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def match_score(text: str) -> int:
            """Hàm tiện ích tính điểm số chuẩn khớp (match score) của từng văn bản"""
            if not text:
                return 0
            text_lower = text.lower()
            # Nếu khớp nguyên câu hoàn toàn (exact match)
            if query_lower in text_lower:
                return 100
            # Nếu khớp một vài từ khóa (keyword match)
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score
        
        try:
            if scope in ["edges", "both"]:
                # Lấy toàn bộ edges để so khớp
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))
                
                # Sắp xếp các cạnh dựa trên điểm số khớp từ khóa
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
                # Tương tự như với cạnh, chúng ta lấy tất cả thực thể và so khớp
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
            
            logger.info(f"Local search completed: Found {len(facts)} related facts")
            
        except Exception as e:
            logger.error(f"Local search failed: {str(e)}")
        
        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )
    
    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        Lấy tất cả các nodes (thực thể) của một đồ thị sử dụng việc phân trang hợp lý.

        Args:
            graph_id: ID của đồ thị (Graph ID)

        Returns:
            List[NodeInfo]: Danh sách các thực thể (nodes)
        """
        logger.info(f"Fetching all nodes for graph {graph_id}...")

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

        logger.info(f"Fetched {len(result)} nodes")
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        Lấy tất cả các edges (mối quan hệ) trong đồ thị bằng cách lấy nhiều trang dữ liệu

        Args:
            graph_id: ID của đồ thị (Graph ID)
            include_temporal: Có lấy cả các field chứa temporal data (created_at, valid_at, v.v) hay không

        Returns:
            List[EdgeInfo]: Danh sách các cảnh (bao gồm thông tin lịch sử thời gian)
        """
        logger.info(f"Fetching all edges for graph {graph_id}...")

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

            # Bổ sung thông tin thời gian hợp lệ (temporal info)
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(f"Fetched {len(result)} edges")
        return result
    
    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        Lấy thông tin chi tiết của một Node (Thực thể) cá biệt
        
        Args:
            node_uuid: UUID của node cần lấy
            
        Returns:
            Được đóng gói thành NodeInfo hoặc None nếu lỗi/không tìm thấy
        """
        logger.info(f"Fetching node detail: {node_uuid[:8]}...")
        
        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=f"Fetching node detail (uuid={node_uuid[:8]}...)"
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
            logger.error(f"Failed to fetch node detail: {str(e)}")
            return None
    
    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        Lấy tất cả các edges (mối quan hệ) liên quan trực tiếp đến một node.
        
        Bằng cách cách kéo xuống tất cả edges và lọc qua node_uuid (ở hai đầu source hoặc target).
        
        Args:
            graph_id: ID của đồ thị (Graph ID)
            node_uuid: UUID của node
            
        Returns:
            Danh sách các EdgeInfo
        """
        logger.info(f"Fetching edges related to node {node_uuid[:8]}...")
        
        try:
            # Lấy tất cả các edges rồi dùng filter (lọc)
            all_edges = self.get_all_edges(graph_id)
            
            result = []
            for edge in all_edges:
                # Kiểm tra xem edge có dính dáng đến node này ở bất kỳ đầu nào không (source hay target)
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)
            
            logger.info(f"Found {len(result)} edges related to node")
            return result
            
        except Exception as e:
            logger.warning(f"Failed to fetch node edges: {str(e)}")
            return []
    
    def get_entities_by_type(
        self, 
        graph_id: str, 
        entity_type: str
    ) -> List[NodeInfo]:
        """
        Lấy dánh sách các thực thể (nodes) phân theo loại (type/label)
        
        Args:
            graph_id: ID của đồ thị (Graph ID)
            entity_type: Loại thực thể (ví dụ: Student, PublicFigure, v.v)
            
        Returns:
            Danh sách các NodeInfo thuộc type được yêu cầu
        """
        logger.info(f"Fetching entities of type {entity_type}...")
        
        all_nodes = self.get_all_nodes(graph_id)
        
        filtered = []
        for node in all_nodes:
            # Kiểm tra xem mảng labels của node này có chứa type yêu cầu không
            if entity_type in node.labels:
                filtered.append(node)
        
        logger.info(f"Found {len(filtered)} entities of type {entity_type}")
        return filtered
    
    def get_entity_summary(
        self, 
        graph_id: str, 
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Lấy tóm tắt về một thực thể cụ thể và các mối quan hệ (edges) của nó.
        
        Sẽ tìm kiếm mọi thông tin có liên quan đến thực thể này và tổng hợp thành bản tóm tắt.
        
        Args:
            graph_id: ID của đồ thị
            entity_name: Tên của thực thể
            
        Returns:
            Dict chứa tóm tắt thông tin của thực thể
        """
        logger.info(f"Fetching relationship summary for entity {entity_name}...")
        
        # Đầu tiên, tìm kiếm thông tin liên quan đến tên thực thể
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )
        
        # Tiếp theo, cố gắng dò tìm node đại diện cho thực thể này trong toàn bộ nodes
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break
        
        related_edges = []
        if entity_node:
            # Lấy tất cả các edges có dính dáng đến node này
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
        Lấy thống kê tổng quan của một đồ thị tri thức
        
        Args:
            graph_id: ID của đồ thị
            
        Returns:
            Dict chứa số liệu thống kê
        """
        logger.info(f"Fetching statistics for graph {graph_id}...")
        
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        
        # Thống kê phân bổ loại thực thể (entity types / labels)
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        
        # Thống kê phân bổ tên mối quan hệ (relation types / edge names)
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
        Lấy thông tin ngữ cảnh liên quan đến mô phỏng (simulation)
        
        Tìm kiếm tổng hợp mọi thông tin có liên quan đến yêu cầu mô phỏng.
        
        Args:
            graph_id: ID của đồ thị (Graph ID)
            simulation_requirement: Mô tả của yêu cầu mô phỏng
            limit: Giới hạn số lượng thông tin mỗi loại
            
        Returns:
            Dict chứa ngữ cảnh (context) cần thiết cho mô phỏng
        """
        logger.info(f"Fetching simulation context: {simulation_requirement[:50]}...")
        
        # Tìm kiếm các thông tin trong graph liên quan chặt chẽ đến yêu cầu mô phỏng
        search_result = self.search_graph(
            graph_id=graph_id,
            query=simulation_requirement,
            limit=limit
        )
        
        # Lấy thông số thống kê của đồ thị
        stats = self.get_graph_statistics(graph_id)
        
        # Lấy tất cả node
        all_nodes = self.get_all_nodes(graph_id)
        
        # Lọc ra các thực thể có mang type thật (Loại bỏ các node chỉ có label chung chung như 'Entity' / 'Node')
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
            "entities": entities[:limit],  # Giới hạn số lượng thực thể
            "total_entities": len(entities)
        }
    
    # ========== Các công cụ tìm kiếm lõi (Đã tối ưu) ==========
    
    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5
    ) -> InsightForgeResult:
        """
        【InsightForge - Tìm kiếm chiều sâu / Deep Insight Search】
        
        Hàm tìm kiếm lai (hybrid retrieval) mạnh mẽ nhất, tự động phân rã câu hỏi và tìm kiếm đa chiều:
        1. Sử dụng LLM phân rã yêu cầu thành các sub-queries (câu hỏi phụ).
        2. Chạy semantic search cho từng câu hỏi phụ.
        3. Rút trích các thực thể liên quan và nội dung chi tiết của chúng.
        4. Truy vết chuỗi quan hệ (relationship chains).
        5. Tổng hợp toàn bộ tạo thành insight báo cáo chi tiết.
        
        Args:
            graph_id: ID của đồ thị (Graph ID)
            query: Câu hỏi / Yêu cầu của người dùng
            simulation_requirement: Yêu cầu mô phỏng
            report_context: Ngữ cảnh bản báo cáo (không bắt buộc, dùng để sinh sub-query chính xác hơn)
            max_sub_queries: Số lượng câu hỏi phụ lớn nhất tạo ra
            
        Returns:
            InsightForgeResult: Kết quả dạng tìm kiếm đa chiều
        """
        logger.info(f"InsightForge deep search: {query[:50]}...")
        
        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )
        
        # Bước 1: Dùng LLM sinh các câu hỏi phụ
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(f"Generated {len(sub_queries)} sub-queries")
        
        # Bước 2: Thực thi semantic search cho mỗi câu hỏi phụ
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
        
        # Thực hiện tìm kiếm cho riêng câu hỏi gốc nữa
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
        
        # Bước 3: Lấy các ID của thực thể từ chuỗi cạnh tương ứng (edges)
        # Chỉ lấy chi tiết của các thực thể này thay vì tải toàn bộ nodes
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)
        
        # Truy xuất chi tiết tất cả thực thể liên quan (Sẽ xuất đầy đủ, không cắt bớt)
        entity_insights = []
        node_map = {}  # Lưu trữ map node cho bước dựng chain tiếp theo
        
        for uuid in list(entity_uuids):  # Xử lý tất cả các thực thể, không cắt bớt (truncate)
            if not uuid:
                continue
            try:
                # Gọi API riêng biệt lấy chi tiết từng node
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "Entity")
                    
                    # Lấy tất cả thông tin fact liên quan đến (các) thực thể này
                    related_facts = [
                        f for f in all_facts 
                        if node.name.lower() in f.lower()
                    ]
                    
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # Trả về toàn bộ danh sách, không cắt bớt
                    })
            except Exception as e:
                logger.debug(f"Failed to fetch node {uuid}: {e}")
                continue
        
        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)
        
        # Bước 4: Khôi phục tất cả các chuỗi quan hệ (không giới hạn số lượng)
        relationship_chains = []
        for edge_data in all_edges:  # Xử lý toàn bộ các edges
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
        
        logger.info(f"InsightForge completed: {result.total_facts} facts, {result.total_entities} entities, {result.total_relationships} relationships")
        return result
    
    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        Dùng LLM sinh các câu hỏi phụ.
        
        Giúp phân rã một câu hỏi lớn / phức tạp thành nhiều câu hỏi nhỏ lẻ 
        có thể query độc lập trên cơ sở dữ liệu.
        """
#         system_prompt = """You are a professional problem analysis expert. Your task is to decompose a complex problem into multiple sub-questions that can be independently observed within a simulated world.

# Requirements:
# 1. Each sub-question should be specific enough to identify relevant Agent behaviors or events within the simulation.
# 2. Sub-questions should cover different dimensions of the original problem (e.g., Who, What, Why, How, When, Where).
# 3. Sub-questions must be relevant to the simulation scenario.
# 4. Return in JSON format: {"sub_queries": ["Sub-question 1", "Sub-question 2", ...]}"""

#         user_prompt = f"""Simulation Requirement Background:
# {simulation_requirement}

# {f"Report context: {report_context[:500]}" if report_context else ""}

# Please decompose the following question into {max_queries} sub-questions:
# {query}

# Return the list of sub-questions in JSON format."""

        system_prompt = """Bạn là một chuyên gia phân tích vấn đề chuyên nghiệp. Nhiệm vụ của bạn là chia nhỏ một vấn đề phức tạp thành nhiều câu hỏi phụ có thể quan sát độc lập trong thế giới mô phỏng.

Yêu cầu:
1. Mỗi câu hỏi phụ phải đủ cụ thể để có thể tìm thấy các hành vi của Agent hoặc các sự kiện liên quan trong thế giới mô phỏng.
2. Các câu hỏi phụ nên bao quát các khía cạnh khác nhau của vấn đề gốc (Ví dụ: Ai, Cái gì, Tại sao, Như thế nào, Khi nào, Ở đâu).
3. Các câu hỏi phụ phải liên quan đến kịch bản mô phỏng.
4. Trả về định dạng JSON: {"sub_queries": ["Câu hỏi phụ 1", "Câu hỏi phụ 2", ...]}"""

        user_prompt = f"""Bối cảnh yêu cầu mô phỏng:
{simulation_requirement}

{f"Ngữ cảnh báo cáo: {report_context[:500]}" if report_context else ""}

Hãy chia nhỏ vấn đề sau đây thành {max_queries} các câu hỏi phụ:
{query}

Trả về danh sách các câu hỏi phụ dưới định dạng JSON."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            sub_queries = response.get("sub_queries", [])
            # Ép kiểu để chắc chắn danh sách toàn kiểu string
            return [str(sq) for sq in sub_queries[:max_queries]]
            
        except Exception as e:
            logger.warning(f"Failed to generate sub-queries: {str(e)}, using default sub-queries")
            # Hạ cấp (fallback): Trả về các biến thể chung chung của câu hỏi ban đầu
            return [
                query,
                f"Main participants of {query}",
                f"Causes and impacts of {query}",
                f"Development process of {query}"
            ][:max_queries]
    
    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50
    ) -> PanoramaResult:
        """
        【PanoramaSearch - Tìm kiếm theo chiều rộng / Panorama Search】
        
        Lấy góc nhìn toàn cảnh, bao gồm tất cả các nội dung liên quan kể cả lịch sử/hết hạn:
        1. Lấy tất cả nodes (thực thể).
        2. Lấy tất cả edges (mối quan hệ), bao gồm cả những sự kiện đã lỗi thời (expired).
        3. Phân loại và phân nhóm các loại thông tin thời gian thực / lịch sử.
        
        Công cụ này phù hợp khi cần một cái nhìn tổng thể về một sự kiện và diễn biến theo thời gian của nó.
        
        Args:
            graph_id: ID đồ thị
            query: Truy vấn tìm kiếm (để sắp xếp theo độ phù hợp)
            include_expired: Cờ bao gồm cả sự kiện hết hạn (mặc định là True)
            limit: Số lượng items giới hạn lúc trả về
            
        Returns:
            PanoramaResult: Kết quả dạng toàn cảnh
        """
        logger.info(f"PanoramaSearch broad search: {query[:50]}...")
        
        result = PanoramaResult(query=query)
        
        # Lấy toàn bộ thực thể
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)
        
        # Lấy toàn bộ mối quan hệ (Cần lấy theo temporal)
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)
        
        # Phân loại facts (sự thật/cạnh)
        active_facts = []
        historical_facts = []
        
        for edge in all_edges:
            if not edge.fact:
                continue
            
            # Khôi phục tên thực thể từ ID để hiển thị đẹp hơn
            source_name = node_map.get(edge.source_node_uuid, NodeInfo('', '', [], '', {})).name or edge.source_node_uuid[:8]
            target_name = node_map.get(edge.target_node_uuid, NodeInfo('', '', [], '', {})).name or edge.target_node_uuid[:8]
            
            # Nhận biết dữ liệu bị hết hạn / lịch sử dựa vào cờ thời gian ZepCloud cung cấp
            is_historical = edge.is_expired or edge.is_invalid
            
            if is_historical:
                # Dữ liệu lịch sử, cần chú thích lại mốc thời gian rõ ràng khi in ra
                valid_at = edge.valid_at or "Unknown"
                invalid_at = edge.invalid_at or edge.expired_at or "Unknown"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # Dữ liệu hiện đang hiệu lực trong bối cảnh snapshot mới nhất
                active_facts.append(edge.fact)
        
        # Phân rã query thành từ khóa
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        
        def relevance_score(fact: str) -> int:
            """Hàm tính điểm mức độ phù hợp để xếp hạng các sự kiện/thực thể vừa trích xuất"""
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score
        
        # Sắp xếp dựa theo điểm từ cao đến thấp và lọc theo limit
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        
        logger.info(f"PanoramaSearch completed: {result.active_count} active facts, {result.historical_count} historical facts")
        return result
    
    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        【QuickSearch - Tìm kiếm cơ bản】
        
        Công cụ tìm kiếm nhỏ gọn:
        1. Gọi trực tiếp Zep Semantic Search
        2. Trả về kết quả phù hợp nhất nguyên bản
        3. Phù hợp cho những nhu cầu tìm kiếm đơn giản, trực tiếp
        
        Args:
            graph_id: ID đồ thị
            query: Từ khóa truy vấn
            limit: Số lượng kết quả
            
        Returns:
            SearchResult: Kết quả của tìm kiếm cơ bản
        """
        logger.info(f"QuickSearch basic search: {query[:50]}...")
        
        # Gọi trực tiếp method search_graph hiện tại
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )
        
        logger.info(f"QuickSearch completed: {result.total_count} results")
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
        【InterviewAgents - Phỏng vấn Sâu / Interview Agents】
        
        Gọi API phỏng vấn OASIS thực thụ để phỏng vấn các Agents đang chạy trong mô phỏng:
        1. Tự động đọc file thiết lập character (profile), nắm bắt tất cả Agents.
        2. Dùng LLM phân tích yêu cầu phỏng vấn, chọn lọc Agent phù hợp một cách thông minh.
        3. Dùng LLM sinh ra các bộ câu hỏi phỏng vấn.
        4. Gọi API /api/simulation/interview/batch tiến hành phỏng vấn thực tế (phỏng vấn đồng thời trên 2 nền tảng nếu có).
        5. Tổng hợp lại mọi câu trả lời và báo cáo.
        
        【QUAN TRỌNG】 Chức năng này yêu cầu Môi trường Mô phỏng đang chạy (OASIS environment chưa bị đóng).
        
        【Use cases - Trường hợp dùng】
        - Muốn xem nhận định từ các góc nhìn khác nhau (ví dụ: góc nhìn từ học sinh/giáo viên).
        - Thu thập ý kiến, quan điểm đa chiều.
        - Chờ lấy câu trả lời THỰC TẾ từ sim Agents (chứ không phải cho LLM giả lập câu trả lời).
        
        Args:
            simulation_id: ID mô phỏng (dùng để định vị file profiles và call target API).
            interview_requirement: Mục đích phỏng vấn phi cấu trúc (ví dụ: "Muốn biết học sinh nghĩ thế nào về vụ này").
            simulation_requirement: Yêu cầu của hệ thống ban đầu (không bắt buộc).
            max_agents: Số điện lượng Agents tối đa muốn phỏng vấn.
            custom_questions: Các câu hỏi điền tay (nếu không cung cấp thì sẽ tự tạo).
            
        Returns:
            InterviewResult: Kẻt quả phỏng vấn tổng hợp
        """
        from .simulation_runner import SimulationRunner
        
        logger.info(f"InterviewAgents Deep Interview (Real API): {interview_requirement[:50]}...")
        
        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )
        
        # Bước 1: Load file cấu hình agent profiles
        profiles = self._load_agent_profiles(simulation_id)
        
        if not profiles:
            logger.warning(f"Did not find agent profiles for simulation {simulation_id}")
            result.summary = "Agent profiles not found for interview"
            return result
        
        result.total_agents = len(profiles)
        logger.info(f"Loaded {len(profiles)} agent profiles")
        
        # Bước 2: Nhờ LLM lựa chọn Agent để phỏng vấn (sẽ trả về mảng agent_id)
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )
        
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(f"Selected {len(selected_agents)} agents for interview: {selected_indices}")
        
        # Bước 3: Sinh câu hỏi phỏng vấn (nếu user không đưa sẵn)
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(f"Generated {len(result.interview_questions)} interview questions")
        
        # Gộp các câu hỏi lại tạo thành 1 chuỗi prompt phỏng vấn hoàn chỉnh
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        
        # Thêm các prefix tối ưu hoá, ràng buộc format câu trả lời của Agent
        # INTERVIEW_PROMPT_PREFIX = (
        #     "You are currently being interviewed. Please combine your persona, "
        #     "all past memories, and actions to answer the following questions directly in plain text.\n"
        #     "Response Requirements:\n"
        #     "1. Answer directly using natural language; do not call any tools.\n"
        #     "2. Do not return JSON format or tool-call formats.\n"
        #     "3. Do not use Markdown headers (e.g., #, ##, ###).\n"
        #     "4. Answer questions one by one according to their numbers. Each answer must start with 'Question X:' (where X is the question number).\n"
        #     "5. Use a blank line to separate the answers for each question.\n"
        #     "6. Answers must have substantive content; provide at least 2-3 sentences for each question.\n\n"
        # )

        INTERVIEW_PROMPT_PREFIX = (
            "Bạn đang tham gia một buổi phỏng vấn. Hãy kết hợp nhân vật (persona), "
            "tất cả ký ức và hành động trong quá khứ của bạn để trả lời trực tiếp các câu hỏi dưới đây bằng văn bản thuần túy.\n"
            "Yêu cầu phản hồi:\n"
            "1. Trả lời trực tiếp bằng ngôn ngữ tự nhiên, không gọi bất kỳ công cụ nào.\n"
            "2. Không trả về định dạng JSON hoặc định dạng gọi công cụ.\n"
            "3. Không sử dụng tiêu đề Markdown (như #, ##, ###).\n"
            "4. Trả lời từng câu một theo số thứ tự, mỗi câu trả lời bắt đầu bằng 'Câu hỏi X:' (X là số thứ tự câu hỏi).\n"
            "5. Sử dụng một dòng trống để phân tách giữa các câu trả lời.\n"
            "6. Câu trả lời phải có nội dung thực tế, mỗi câu hỏi cần trả lời ít nhất 2-3 câu văn.\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"
        
        # Bước 4: Gọi trực tiếp API Phỏng vấn (Mặc định không chỉ định platform để chạy trên cả 2 nền tảng)
        try:
            # Dựng cấu trúc payload của batch request (không truyền param platform sẽ ngầm hiểu bằng trên cả 2 nền tảng)
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # Dùng prompt đã bọc prefix tối ưu
                    # Bỏ trống platform -> API sẽ call tới Agent của trên Twitter và Reddit list
                })
            
            logger.info(f"Calling batch interview API (dual platforms): {len(interviews_request)} agents")
            
            # Khởi động calling via class SimulationRunner method (thời gian timeout phải cao do chọc 2 nền tảng song song)
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # Không định dạng nền tảng -> Dual platform call
                timeout= 800 # Tăng timeout do phải chờ API trên 2 platforms xử lý
            )
            
            logger.info(f"Interview API returned: {api_result.get('interviews_count', 0)} results, success={api_result.get('success')}")
            
            # Xác nhận API có success không hay failure
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "Unknown error")
                logger.warning(f"Interview API failed: {error_msg}")
                result.summary = f"Interview API call failed: {error_msg}. Please check OASIS simulation status."
                return result
            
            # Bước 5: Bóc tách data từ JSON output của API, biên dịch sang Object `AgentInterview`
            # Cấu trúc của dual platform output: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}
            
            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "Unknown")
                agent_bio = agent.get("bio", "")
                
                # Fetch cả response text trên hai sàn
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})
                
                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # Thao tác dọn dẹp (phòng trường hợp API xuất bừa JSON của function tools)
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # Format lại khi xuất log hoặc hiển thị (chỉ rõ câu trả lời nào từ nền tảng nào)
                twitter_text = twitter_response if twitter_response else "(No reply received on this platform)"
                reddit_text = reddit_response if reddit_response else "(No reply received on this platform)"
                response_text = f"【Twitter Platform】\n{twitter_text}\n\n【Reddit Platform】\n{reddit_text}"

                # Gộp chung nội dung phục vụ tìm các câu trích dẫn tiêu biểu (quotes)
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # Lược bỏ các keyword nhiễu (Markdown format, số thứ tự, config name tool, prefix, ...)
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'Question\s*\d+[：:]\s*', '', clean_text)
                clean_text = re.sub(r'【[^】]+】', '', clean_text)

                # Luồng số 1 : Mổ câu theo dấu kết thúc cầu (. ? !). Chọn các câu đủ độ dài (không quá ngắn ko quá dài)
                sentences = re.split(r'[.!?。！？]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W，,；;：:、]+', s.strip())
                    and not s.strip().startswith(('{', 'Question'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "." for s in meaningful[:3]]

                # Luồng số 2 : Trích xuất từ dấu ngoặc kéo nếu như regex 1 thất bại
                if not key_quotes:
                    paired = re.findall(r'["\u201c]([^\u201c\u201d"]{15,100})["\u201d]', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[，,；;：:、]', q)][:3]
                
                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # Tăng giới hạn độ dài của bio
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)
            
            result.interviewed_count = len(result.interviews)
            
        except ValueError as e:
            # Nếu Môi trường chưa được khởi động
            logger.warning(f"Interview API failed (environment not running?): {e}")
            result.summary = f"Interview failed: {str(e)}. Simulation environment might be closed, please ensure OASIS environment is running."
            return result
        except Exception as e:
            logger.error(f"Interview API exception: {e}")
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"Error during interview: {str(e)}"
            return result
        
        # Bước 6: Tổng hợp lại thành Summary hoàn chỉnh
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )
        
        logger.info(f"InterviewAgents completed: Interviewed {result.interviewed_count} agents (dual platform)")
        return result
    
    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """Dọn dẹp chuỗi JSON của tool call trong câu trả lời từ Agent, và xuất ra content thật sự (nếu có)"""
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
        """Tải file chứa danh sách profile của các Agents trong kịch bản mô phỏng"""
        import os
        import csv
        
        # Đường dẫn cấu trúc tới thư mục mô phỏng
        sim_dir = os.path.join(
            os.path.dirname(__file__), 
            f'../../uploads/simulations/{simulation_id}'
        )
        
        profiles = []
        
        # Cố gắng ưu tiên tải định dạng JSON của Reddit
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(f"Loaded {len(profiles)} profiles from reddit_profiles.json")
                return profiles
            except Exception as e:
                logger.warning(f"Failed to read reddit_profiles.json: {e}")
        
        # Nếu không có hoặc lỗi, thử tải định dạng CSV của Twitter
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Chuẩn hóa về format chung
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "Unknown"
                        })
                logger.info(f"Loaded {len(profiles)} profiles from twitter_profiles.csv")
                return profiles
            except Exception as e:
                logger.warning(f"Failed to read twitter_profiles.csv: {e}")
        
        return profiles
    
    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """
        Sử dụng LLM phân tích profile và lựa chọn các Agent phù hợp nhất cho phỏng vấn.
        
        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: Danh sách info hoàn chỉnh của các Agent được chọn
                - selected_indices: Danh sách số index (phục vụ gọi API phỏng vấn sau này)
                - reasoning: Mô tả vì sao chọn các role/agent này
        """
        
        # Lược trích ngắn lại các profile đem cho LLM đọc để tiết kiệm token
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "Unknown"),
                "bio": profile.get("bio", "")[:200],  # Cắt ngắn bio
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)

            system_prompt = """Bạn là một chuyên gia lập kế hoạch phỏng vấn chuyên nghiệp. Nhiệm vụ của bạn là dựa trên yêu cầu phỏng vấn để chọn ra những đối tượng phù hợp nhất từ danh sách các Agent mô phỏng.

Tiêu chí lựa chọn:
1. Danh tính/Nghề nghiệp của Agent phải liên quan đến chủ đề phỏng vấn.
2. Agent có khả năng nắm giữ những quan điểm độc đáo hoặc có giá trị.
3. Lựa chọn các góc nhìn đa dạng (Ví dụ: bên ủng hộ, bên phản đối, bên trung lập, chuyên gia, v.v.).
4. Ưu tiên các nhân vật có liên quan trực tiếp đến sự kiện.

Trả về định dạng JSON:
{
    "selected_indices": [Danh sách chỉ mục của các Agent được chọn],
    "reasoning": "Giải thích lý do lựa chọn"
}"""

        user_prompt = f"""Yêu cầu phỏng vấn:
{interview_requirement}

Bối cảnh mô phỏng:
{simulation_requirement if simulation_requirement else "Not provided"}

Danh sách các Agent có thể chọn (Tổng cộng {len(agent_summaries)}):
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

Hãy chọn tối đa {max_agents} Agent phù hợp nhất để phỏng vấn và giải thích lý do lựa chọn của bạn."""
        
#         system_prompt = """You are a professional interview planning expert. Your task is to select the most suitable subjects for an interview from a list of simulated Agents based on the interview requirements.

# Selection Criteria:
# 1. The Agent's identity/profession must be relevant to the interview topic.
# 2. The Agent is likely to hold a unique or valuable perspective.
# 3. Select diverse perspectives (e.g., supporters, opponents, neutral parties, professionals, etc.).
# 4. Prioritize characters directly related to the event.

# Return in JSON format:
# {
#     "selected_indices": [List of indices of selected Agents],
#     "reasoning": "Explanation for the selection"
# }"""

#         user_prompt = f"""Interview Requirements:
# {interview_requirement}

# Simulation Background:
# {simulation_requirement if simulation_requirement else "Not provided"}

# List of selectable Agents (Total {len(agent_summaries)}):
# {json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

# Please select a maximum of {max_agents} most suitable Agents for the interview and explain the reasons for your selection."""

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "Auto selected based on relevance")
            
            # Map index vào lại danh sách profile chuẩn
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            
            return selected_agents, valid_indices, reasoning
            
        except Exception as e:
            logger.warning(f"LLM failed to select agents, falling back to default: {e}")
            # Hạ cấp (fallback): Chọn N Agent đầu tiên trong danh sách
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "Using default selection strategy"
    
    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """Sử dụng LLM để sinh ra các câu chất vấn hợp với tính chất sự việc"""
        
        agent_roles = [a.get("profession", "Unknown") for a in selected_agents]

#         system_prompt = """You are a professional journalist/interviewer. Based on the interview requirements, generate 3-5 in-depth interview questions.

# Question Requirements:
# 1. Open-ended questions that encourage detailed answers.
# 2. Questions that may elicit different answers from different roles.
# 3. Cover multiple dimensions such as facts, opinions, and feelings.
# 4. Use natural language, sounding like a real-life interview.
# 5. Keep each question under 50 words, concise and clear.
# 6. Ask the questions directly; do not include background explanations or prefixes.

# Return in JSON format: {"questions": ["Question 1", "Question 2", ...]}"""

#         user_prompt = f"""Interview Requirements: {interview_requirement}

# Simulation Background: {simulation_requirement if simulation_requirement else "Not provided"}

# Interviewee Roles: {', '.join(agent_roles)}

# Please generate 3-5 interview questions."""
        
        system_prompt = """Bạn là một nhà báo/người phỏng vấn chuyên nghiệp. Dựa trên yêu cầu phỏng vấn, hãy tạo từ 3-5 câu hỏi phỏng vấn chuyên sâu.

Yêu cầu đối với câu hỏi:
1. Câu hỏi mở, khuyến khích câu trả lời chi tiết.
2. Các câu hỏi có thể nhận được những câu trả lời khác nhau tùy theo từng vai trò.
3. Bao quát nhiều khía cạnh như sự thật, quan điểm và cảm xúc.
4. Ngôn ngữ tự nhiên, giống như một buổi phỏng vấn thực tế.
5. Mỗi câu hỏi khống chế dưới 50 chữ, ngắn gọn và súc tích.
6. Đặt câu hỏi trực tiếp, không bao gồm giải thích bối cảnh hoặc tiền tố.

Trả về định dạng JSON: {"questions": ["Câu hỏi 1", "Câu hỏi 2", ...]}"""

        user_prompt = f"""Yêu cầu phỏng vấn: {interview_requirement}

Bối cảnh mô phỏng: {simulation_requirement if simulation_requirement else "Not provided"}

Vai trò của đối tượng phỏng vấ: {', '.join(agent_roles)}

Hãy tạo từ 3-5 câu hỏi phỏng vấn."""
        
        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5
            )
            
            return response.get("questions", [f"What is your opinion on {interview_requirement}?"])
            
        except Exception as e:
            logger.warning(f"Failed to generate interview questions: {e}")
            return [
                f"What is your perspective on {interview_requirement}?",
                "How does this event impact you or the group you represent?",
                "How do you think this issue should be resolved or improved?"
            ]
    
    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """Tạo bản tóm tắt nội dung sau khi phỏng vấn"""
        
        if not interviews:
            return "No interviews completed"
        
        # Gom các trả lời phỏng vấn lại cho LLM tóm tắt
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"【{interview.agent_name}（{interview.agent_role}）】\n{interview.response[:500]}")

#         system_prompt = """You are a professional news editor. Please generate an interview summary based on the responses from multiple interviewees.

# Summary Requirements:
# 1. Synthesize the main viewpoints from all parties.
# 2. Identify areas of consensus and divergence among the viewpoints.
# 3. Highlight valuable quotes.
# 4. Maintain objectivity and neutrality, without favoring any side.
# 5. Limit the summary to 1000 words.

# Formatting Constraints (MUST be followed):
# - Use plain text paragraphs, separated by blank lines.
# - Do not use Markdown headers (e.g., #, ##, ###).
# - Do not use horizontal rules (e.g., ---, ***).
# - Use Vietnamese quotation marks 「」 when quoting the interviewees' original words.
# - You may use **bold** to highlight keywords, but do not use any other Markdown syntax."""

#         user_prompt = f"""Interview Topic: {interview_requirement}

# Interview Content:
# {"\n\n".join(interview_texts)}

# Please generate the interview summary."""
        
        system_prompt = """Bạn là một biên tập viên tin tức chuyên nghiệp. Hãy tạo một bản tóm tắt phỏng vấn dựa trên câu trả lời từ nhiều đối tượng được phỏng vấn.

Yêu cầu tóm tắt:
1. Đúc kết các quan điểm chính của các bên.
2. Chỉ ra những điểm đồng thuận và khác biệt trong các quan điểm.
3. Làm nổi bật các câu trích dẫn có giá trị.
4. Đảm bảo tính khách quan và trung lập, không thiên vị bất kỳ bên nào.
5. Giới hạn trong khoảng 1000 chữ.

Ràng buộc định dạng (BẮT BUỘC tuân thủ):
- Sử dụng các đoạn văn bản thuần túy, phân tách các phần bằng dòng trống.
- Không sử dụng tiêu đề Markdown (như #, ##, ###).
- Không sử dụng đường kẻ phân cách (như ---, ***).
- Sử dụng dấu ngoặc kép kiểu Việt Nam 「」 khi trích dẫn nguyên văn lời của người được phỏng vấn.
- Có thể sử dụng dấu **in đậm** cho các từ khóa, nhưng không sử dụng bất kỳ cú pháp Markdown nào khác."""

        user_prompt = f"""Chủ đề phỏng vấn: {interview_requirement}

Nội dung phỏng vấn:
{"\n\n".join(interview_texts)}

Hãy tạo bản tóm tắt phỏng vấn."""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=4096
            )
            return summary
            
        except Exception as e:
            logger.warning(f"Failed to generate interview summary: {e}")
            # Hạ cấp (fallback): Nối chuỗi cơ bản kèm theo tên những người được phỏng vấn
            return f"Interviewed {len(interviews)} people in total, including: " + ", ".join([i.agent_name for i in interviews])
