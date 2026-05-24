"""
Dịch vụ Report Agent
Sử dụng LangChain + Zep để thực hiện tạo báo cáo mô phỏng theo mô hình ReACT

Chức năng:
1. Dựa trên yêu cầu mô phỏng và thông tin đồ thị Zep để tạo ra báo cáo
2. Lên kế hoạch cho cấu trúc mục lục trước, sau đó tạo từng đoạn
3. Mỗi đoạn áp dụng mô hình ReACT để suy nghĩ đa vòng và phản xạ
4. Hỗ trợ hội thoại với người dùng, tự động gọi công cụ tìm kiếm trong hội thoại
"""

import os
import json
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .zep_tools import (
    ZepToolsService, 
)

from ..prompts.report_agent import (
    PLAN_SYSTEM_PROMPT,
    PLAN_USER_PROMPT_TEMPLATE,
    SECTION_SYSTEM_PROMPT_TEMPLATE,
    TOOL_DESC_INSIGHT_FORGE,
    TOOL_DESC_PANORAMA_SEARCH,
    TOOL_DESC_QUICK_SEARCH,
    TOOL_DESC_INTERVIEW_AGENTS,
    SECTION_USER_PROMPT_TEMPLATE,
    REACT_OBSERVATION_TEMPLATE,
    REACT_INSUFFICIENT_TOOLS_MSG,
    REACT_INSUFFICIENT_TOOLS_MSG_ALT,
    REACT_TOOL_LIMIT_MSG,
    REACT_UNUSED_TOOLS_HINT,
    REACT_FORCE_FINAL_MSG,
    CHAT_SYSTEM_PROMPT_TEMPLATE,
    CHAT_OBSERVATION_SUFFIX
)

logger = get_logger('mirofish.report_agent')


class ReportLogger:
    """
    Trình ghi chi tiết log của Report Agent
    
    Tạo file agent_log.jsonl trong thư mục báo cáo, ghi lại chi tiết từng bước.
    Mỗi dòng là một đối tượng JSON hoàn chỉnh, bao gồm timestamp, loại hành động, nội dung chi tiết...
    """
    
    def __init__(self, report_id: str):
        """
        Khởi tạo trình ghi log
        
        Args:
            report_id: ID của báo cáo, dùng để quyết định đường dẫn file log
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """Đảm bảo thư mục chứa file log đã tồn tại"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """Lấy thời gian tiêu tốn từ lúc bắt đầu tới hiện tại (giây)"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        Ghi lại một dòng log
        
        Args:
            action: Loại hành động, ví dụ 'start', 'tool_call', 'llm_response', 'section_complete' v.v..
            stage: Giai đoạn hiện tại, ví dụ 'planning', 'generating', 'completed'
            details: Dictionary chứa nội dung chi tiết
            section_title: Tiêu đề chương hiện tại (tùy chọn)
            section_index: Index của chương hiện tại (tùy chọn)
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # Ghi nối tiếp vào file JSONL
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """Ghi log báo cáo bắt đầu tạo"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "Report generation task started"
            }
        )
    
    def log_planning_start(self):
        """Ghi log kế hoạch dàn ý bắt đầu"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "Start planning report outline"}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """Ghi log thông tin context lấy được khi lên kế hoạch"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "Fetch simulation context info",
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """Ghi log kế hoạch dàn ý hoàn thành"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "Outline planning completed",
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """Ghi log tiến trình bắt đầu tạo chương"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"Start generating section: {section_title}"}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """Ghi log quá trình suy nghĩ ReACT"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReACT thought iteration {iteration}"
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """Ghi log thao tác gọi công cụ"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"Calling tool: {tool_name}"
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """Ghi log kết quả gọi công cụ (Toàn bộ nội dung)"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # Kết quả đầy đủ, không cắt ngắn
                "result_length": len(result),
                "message": f"Tool {tool_name} returned result"
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """Ghi nhận phản hồi LLM (nội dung đầy đủ, không cắt ngắn)"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # Phản hồi đầy đủ, không cắt ngắn
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"LLM response (Tool call: {has_tool_calls}, Final answer: {has_final_answer})"
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """Ghi nhận nội dung chương đã tạo (chỉ ghi nhận nội dung, không có nghĩa là toàn bộ chương đã hoàn thành)"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # Nội dung đầy đủ, không cắt ngắn
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"Section {section_title} content generation completed"
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str
    ):
        """
        Ghi nhận chương đã hoàn thành

        Frontend nên lắng nghe nhật ký này để xác định chương đó có thực sự hoàn thành hay không, và lấy nội dung đầy đủ
        """
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": full_content,
                "content_length": len(full_content),
                "message": f"Section {section_title} generation completed"
            }
        )
    
    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        """Ghi nhận việc tạo báo cáo hoàn tất"""
        self.log(
            action="report_complete",
            stage="completed",
            details={
                "total_sections": total_sections,
                "total_time_seconds": round(total_time_seconds, 2),
                "message": "Report generation completed"
            }
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """Ghi nhận lỗi"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"An error occurred: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Trình ghi Log qua console của Report Agent
    
    Ghi nhật ký kiểu console (INFO, WARNING, v.v.) vào tệp console_log.txt trong mục lưu báo cáo.
    Khác với agent_log.jsonl, những nhật ký này ở định dạng văn bản thuần túy.
    """
    
    def __init__(self, report_id: str):
        """
        Khởi tạo trình ghi log console
        
        Args:
            report_id: ID báo cáo, dùng để tự xác định đường dẫn file log
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """Đảm bảo thư mục lưu file log tồn tại"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """Cấu hình trình xử lý tệp (FileHandler) để ghi nhật ký vào tệp"""
        import logging
        
        # Tạo file handler
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        
        # Cấu trúc log đơn giản tương tự như phiên làm việc console
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        
        # Thêm file hander vào logger của report_agent
        loggers_to_attach = [
            'mirofish.report_agent',
            'mirofish.zep_tools',
        ]
        
        for logger_name in loggers_to_attach:
            target_logger = logging.getLogger(logger_name)
            # Tránh thêm lại handler trùng lặp
            if self._file_handler not in target_logger.handlers:
                target_logger.addHandler(self._file_handler)
    
    def close(self):
        """Đóng file handler và gỡ nó khỏi cấu hình logger"""
        import logging
        
        if self._file_handler:
            loggers_to_detach = [
                'mirofish.report_agent',
                'mirofish.zep_tools',
            ]
            
            for logger_name in loggers_to_detach:
                target_logger = logging.getLogger(logger_name)
                if self._file_handler in target_logger.handlers:
                    target_logger.removeHandler(self._file_handler)
            
            self._file_handler.close()
            self._file_handler = None
    
    def __del__(self):
        """Đảm bảo đóng file handler khi hàm hủy (destructor) gọi"""
        self.close()


class ReportStatus(str, Enum):
    """Trạng thái báo cáo"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """Chương báo cáo"""
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content
        }

    def to_markdown(self, level: int = 2) -> str:
        """Chuyển đổi sang định dạng Markdown"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """Dàn ý báo cáo"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """Chuyển đổi sang định dạng Markdown"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """Báo cáo đầy đủ"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error
        }


# ═══════════════════════════════════════════════════════════════
# Class chính: ReportAgent
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - Tác nhân tạo báo cáo mô phỏng

    Sử dụng chế độ ReACT (Reasoning + Acting):
    1. Giai đoạn lập kế hoạch (Planning): Phân tích yêu cầu mô phỏng, hoạch định cấu trúc thư mục báo cáo
    2. Giai đoạn tạo văn bản (Generating): Tạo nội dung theo từng cấu trúc, mỗi cấu trúc có thể gọi công cụ nhiều lần để lấy thông tin
    3. Giai đoạn xem xét (Reflecting): Kiểm tra tính toàn vẹn và độ chính xác của nội dung
    """
    
    # Số lần gọi công cụ tối đa (mỗi chương)
    MAX_TOOL_CALLS_PER_SECTION = 5
    
    # Số vòng xem xét tối đa
    MAX_REFLECTION_ROUNDS = 3
    
    # Số lần gọi công cụ tối đa trong quá trình trò chuyện
    MAX_TOOL_CALLS_PER_CHAT = 2
    
    def __init__(
        self, 
        graph_id: str,
        simulation_id: str,
        project_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None
    ):
        """
        Khởi tạo Report Agent
        
        Args:
            graph_id: ID Đồ thị
            simulation_id: ID mô phỏng
            simulation_requirement: Mô tả yêu cầu mô phỏng
            llm_client: Client của LLM (không bắt buộc)
            zep_tools: Dịch vụ công cụ Zep (không bắt buộc)
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.project_id = project_id
        self.simulation_requirement = simulation_requirement
        
        self.llm = llm_client or LLMClient(
            component="report_agent",
            metadata={
                "simulation_id": simulation_id,
                "project_id": project_id,
                "phase": "report_generation",
            },
        )
        self.zep_tools = zep_tools or ZepToolsService(
            llm_client=LLMClient(
                component="zep_tools",
                metadata={
                    "simulation_id": simulation_id,
                    "project_id": project_id,
                    "phase": "zep_tools",
                },
            )
        )
        
        # Định nghĩa các công cụ
        self.tools = self._define_tools()
        
        # Trình ghi log báo cáo (được khởi tạo trong generate_report)
        self.report_logger: Optional[ReportLogger] = None
        # Trình ghi log console (được khởi tạo trong generate_report)
        self.console_logger: Optional[ReportConsoleLogger] = None
        
        logger.info(
            f"ReportAgent initialized: graph_id={graph_id}, simulation_id={simulation_id}, project_id={project_id}"
        )
    
    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """Định nghĩa các công cụ khả dụng"""
        return {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "The question or topic you want to deeply analyze",
                    "report_context": "The context of the current report section (optional, helps generate more precise sub-questions)"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "Search query used for relevance ranking",
                    "include_expired": "Whether to include expired/historical content (default True)"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "Search query string",
                    "limit": "Number of returned results (optional, default 10)"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "Interview topic or requirement description (e.g.: 'Understand students opinions on dorm formaldehyde issue')",
                    "max_agents": "Maximum number of agents to interview (optional, default 5, maximum 10)"
                }
            }
        }
    
    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        Thực thi lệnh gọi công cụ
        
        Args:
            tool_name: Tên công cụ
            parameters: Các tham số cho công cụ
            report_context: Ngữ cảnh của đoạn báo cáo (dành cho InsightForge)
            
        Returns:
            Kết quả của công cụ trả về (định dạng text)
        """
        logger.info(f"Executing tool: {tool_name}, Parameters: {parameters}")
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # Tìm kiếm diện rộng - Lấy toàn cảnh kết quả
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # Tìm kiếm đơn giản - Lấy dữ liệu nhanh
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # Phỏng vấn chuyên sâu - Gọi API phỏng vấn OASIS thật để lấy ý kiến của các Agent đang chạy (đa nền tảng)
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                max_agents = min(max_agents, 10)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents
                )
                return result.to_text()
            
            # ========== Công cụ cũ giữ lại để tương thích (chuyển hướng sang công cụ mới) ==========
            
            elif tool_name == "search_graph":
                # Lái qua quick_search
                logger.info("search_graph redirected to quick_search")
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # Lái qua insight_forge do nó xịn hơn
                logger.info("get_simulation_context redirected to insight_forge")
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                return f"Unknown tool: {tool_name}. Please use one of: insight_forge, panorama_search, quick_search"
                
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}, Error: {str(e)}")
            return f"Tool execution failed: {str(e)}"
    
    # Tập hợp các tool khả dụng, để kiểm tra tính hợp lệ khi quét JSON
    VALID_TOOL_NAMES = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        Phân tích kết quả trả về từ LLM để lấy thông tin gọi công cụ

        Định dạng hỗ trợ (theo mức độ ưu tiên):
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. JSON trần (Toàn bộ chuỗi response hoặc từng dòng là một JSON trực tiếp cho công cụ)
        """
        tool_calls = []

        # Định dạng 1: Phong cách XML (Định dạng tiêu chuẩn)
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # Định dạng 2: Dự phòng phòng hờ LLM trả về chuỗi JSON trần không có tag <tool_call>
        # Chỉ chạy logic này khi không thấy định dạng 1, tránh dính JSON vô ý trong văn bản chính
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # Reply có thể chứa cả nội dung suy nghĩ (Thought) + JSON trần, thử móc ra object JSON cuối cùng
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """Kiểm tra JSON giải mã được có phải là lời gọi công cụ hợp lệ hay không"""
        # Hỗ trợ cả 2 định dạng {"name": ..., "parameters": ...} và {"tool": ..., "params": ...}
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            # Đồng nhất key về chuẩn name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """Tạo đoạn văn mô tả công cụ"""
        desc_parts = ["Available tools:"]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  Parameters: {params_desc}")
        return "\n".join(desc_parts)
    
    def plan_outline(
        self, 
        progress_callback: Optional[Callable] = None
    ) -> ReportOutline:
        """
        Hoạch định dàn ý báo cáo
        
        Sử dụng LLM để phân tích yêu cầu mô phỏng, hoạch định cấu trúc thư mục của báo cáo
        
        Args:
            progress_callback: Hàm callback tiến trình
            
        Returns:
            ReportOutline: Dàn ý báo cáo
        """
        logger.info("Start planning report outline...")
        
        if progress_callback:
            progress_callback("planning", 0, "Analyzing simulation requirements...")
        
        # Đầu tiên cần lấy ngữ cảnh mô phỏng
        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement
        )
        
        if progress_callback:
            progress_callback("planning", 30, "Generating report outline...")
        
        system_prompt = PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, "Parsing outline structure...")
            
            # Phân tích cú pháp lấy dàn ý
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content=""
                ))
            
            outline = ReportOutline(
                title=response.get("title", "Simulation Analysis Report"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, "Outline planning completed")
            
            logger.info(f"Outline planning completed: {len(sections)} chapters")
            return outline
            
        except Exception as e:
            logger.error(f"Outline planning failed: {str(e)}")
            # Trả về dàn ý mặc định (3 chương, đóng vai trò bản dự phòng)
            return ReportOutline(
                title="Future Prediction Report",
                summary="Future trends and risk analysis based on simulation prediction",
                sections=[
                    ReportSection(title="Prediction Scenarios and Core Findings"),
                    ReportSection(title="Population Behavior Prediction Analysis"),
                    ReportSection(title="Trend Outlook and Risk Warning")
                ]
            )
    
    def _generate_section_react(
        self, 
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        Sử dụng chế độ ReACT để tạo nội dung cho từng chương
        
        Vòng lặp ReACT:
        1. Thought (Suy nghĩ) - Phân tích xem cần thông tin gì
        2. Action (Hành động) - Gọi công cụ để lấy thông tin
        3. Observation (Quan sát) - Phân tích kết quả công cụ trả về
        4. Lặp lại quá trình tới khi đủ thông tin hoặc chạy hết số lượt cho phép
        5. Final Answer (Câu trả lời cuối cùng) - Sinh nội dung chương
        
        Args:
            section: Chương cần sinh
            outline: Dàn ý đầy đủ
            previous_sections: Nội dung các chương trước (dành cho việc duy trì tính gắn kết logic)
            progress_callback: Callback theo dõi tiến trình
            section_index: Chỉ mục của chương hiện tại (dùng để log)
            
        Returns:
            Nội dung chương (Định dạng Markdown)
        """
        logger.info(f"ReACT generating chapter: {section.title}")
        
        # Ghi nhận log khởi tạo chương
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )

        # Xây dựng prompt cho user - mỗi chương trước đó sẽ truyền vào tối đa 4000 ký tự
        if previous_sections:
            previous_parts = []
            for sec in previous_sections:
                # Mỗi chương tối đa 4000 ký tự
                truncated = sec[:4000] + "..." if len(sec) > 4000 else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "(This is the first chapter)"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Vòng lặp ReACT
        tool_calls_count = 0
        max_iterations = 5  # Số vòng lặp tối đa
        min_tool_calls = 3  # Số lần gọi công cụ tối thiểu
        conflict_retries = 0  # Số lần gọi công cụ và trả về Final Answer bị xung đột liên tiếp
        used_tools = set()  # Lưu lại tên các công cụ đã được gọi
        all_tools = {"insight_forge", "panorama_search", "quick_search", "interview_agents"}

        # Ngữ cảnh báo cáo, dùng để tự sinh câu hỏi thứ cấp trong InsightForge
        report_context = f"Chapter Title: {section.title}\nSimulation Requirement: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    f"Deep retrieval and writing in progress ({tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )
            
            # Gọi LLM
            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                # max_tokens=4096
            )

            # Kiểm tra xem phản hồi có rỗng/chưa có (None) không (do API lỗi hoặc content null)
            if response is None:
                logger.warning(f"Chapter {section.title} iteration {iteration + 1}: LLM returned None")
                # Nếu còn lượt thử, thêm message tiếp
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "(Empty response)"})
                    messages.append({"role": "user", "content": "Please continue generating content."})
                    continue
                # Còn nếu nó về None lần cuối thì nhảy thoát vòng lặp kết thúc
                break

            logger.debug(f"LLM response: {response[:200]}...")

            # Parse dữ liệu một lần để tiết kiệm
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── Giải quyết xung đột: LLM cùng lúc nhả cả tool gọi lẫn output Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"Chapter {section.title} iteration {iteration+1}: "
                    f"LLM output tool call and Final Answer simultaneously (Conflict #{conflict_retries})"
                )

                if conflict_retries <= 2:
                    # Trong 2 lần đầu: Vứt phản hồi này, bắt LLM tạo lại
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "[Format Error] You included both tool call and Final Answer in a single reply, which is not allowed.\n"
                            "Each reply can only do one of two things:\n"
                            "- Call a tool (output a <tool_call> block, do not write Final Answer)\n"
                            "- Output final content (starting with 'Final Answer:', do not include <tool_call>)\n"
                            "Please reply again, doing only one of these things."
                        ),
                    })
                    continue
                else:
                    # Lần 3: Hạ cấp xử lý, ngắt cứng đến lệnh gọi công cụ đầu tiên và tiếp tục bám theo
                    logger.warning(
                        f"Chapter {section.title}: {conflict_retries} consecutive conflicts, "
                        "degrading to truncated execution of the first tool call"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # Ghi lại log phản hồi của LLM
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── Trường hợp 1: LLM đã xuất ra Final Answer ──
            if has_final_answer:
                # Nếu số lần gọi công cụ chưa đủ, từ chối và yêu cầu tiếp tục gọi
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"(These tools are unused, suggest using them: {', '.join(unused_tools)})" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # Kết thúc bình thường
                final_answer = response.split("Final Answer:")[-1].strip()
                logger.info(f"Chapter {section.title} generation completed (Tool calls: {tool_calls_count})")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── Trường hợp 2: LLM cố gắng gọi công cụ ──
            if has_tool_calls:
                # Đã hết hạn mức gọi công cụ → Thông báo rõ ràng, yêu cầu xuất Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # Chỉ thực thi lệnh gọi đầu tiên
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM attempted to call {len(tool_calls)} tools, only executing the first one: {call['name']}")

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                # Tạo gợi ý cho các công cụ chưa dùng
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── Trường hợp 3: Không có gọi công cụ, cũng không có Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # Gọi công cụ chưa đủ, gợi ý các công cụ khác
                unused_tools = all_tools - used_tools
                unused_hint = f"(These tools are unused, suggest using them: {', '.join(unused_tools)})" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # Đã đủ số lần gọi công cụ, LLM sinh nội dung nhưng quên mất tiền tố "Final Answer:"
            # Cứ lấy thẳng nội dung này làm kết quả luôn cho khỏi vòng vo
            logger.info(f"Chapter {section.title} 'Final Answer:' prefix not detected, directly adopting LLM output as final content (Tool calls: {tool_calls_count})")
            final_answer = response.strip()

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # Hết số vòng lặp tối đa, bắt buộc bắt đầu tự sản xuất
        logger.warning(f"Chapter {section.title} reached max iterations, forcing generation")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})
        
        response = self.llm.chat(
            messages=messages,
            temperature=0.5,
            # max_tokens=4096
        )

        # Kiểm tra nếu ép buộc kết thúc mà LLM vẫn nhả None
        if response is None:
            logger.error(f"Chapter {section.title} LLM returned None during forced completion, using default error prompt")
            final_answer = f"(This chapter generation failed: LLM returned empty response, please try again later)"
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response
        
        # Ghi log quá trình tạo nội dung chương hoàn tất
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def generate_report(
        self, 
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        Tạo báo cáo hoàn chỉnh (Xuất theo thời gian thực từng chương)
        
        Mỗi chương sau khi hoàn thành sẽ được lưu ngay vào mục, không cần đợi cả báo cáo xong.
        Cấu trúc thư mục:
        reports/{report_id}/
            meta.json       - Thông tin meta
            outline.json    - Dàn ý
            progress.json   - Tiến độ
            section_01.md   - Chương 1
            section_02.md   - Chương 2
            ...
            full_report.md  - Báo cáo tổng
        
        Args:
            progress_callback: Callback tiến độ (stage, progress, message)
            report_id: ID báo cáo (Có thể rỗng để tự phát sinh)
            
        Returns:
            Report: Báo cáo đầy đủ
        """
        import uuid
        
        # Tạo report_id mới tự động nếu chưa có truyền vào
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()

        # Đồng bộ metadata chi phí LLM theo report hiện tại
        # Mục tiêu: mọi call trong giai đoạn generate report đều mang report_id.
        self.llm.default_metadata["report_id"] = report_id
        self.llm.default_metadata["project_id"] = self.project_id
        self.llm.default_metadata["simulation_id"] = self.simulation_id
        self.llm.default_metadata["phase"] = "report_generation"

        zep_llm = self.zep_tools.llm
        zep_llm.default_metadata["report_id"] = report_id
        zep_llm.default_metadata["project_id"] = self.project_id
        zep_llm.default_metadata["simulation_id"] = self.simulation_id
        zep_llm.default_metadata["phase"] = "zep_tools"
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # Cập nhật mảng những tiêu đề chương xong (Để tính tiến độ)
        completed_section_titles = []
        
        try:
            # Khởi tạo: Tạo thư mục lưu và ghi nhận trạng thái
            ReportManager._ensure_report_folder(report_id)
            
            # Khởi tạo bộ ghi log (Log có cấu trúc ghi ra file agent_log.jsonl)
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # Khởi tạo logger để lưu thêm console (console_log.txt)
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, "Initializing report...",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # Bước 1: Lên dàn ý
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "Start planning report outline...",
                completed_sections=[]
            )
            
            # Ghi log bắt đầu giai đoạn lên dàn ý
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, "Start planning report outline...")
            
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg: 
                    progress_callback(stage, prog // 5, msg) if progress_callback else None
            )
            report.outline = outline
            
            # Ghi log hoàn thành dàn ý
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # Lưu file dàn ý
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"Outline planning completed, total {len(outline.sections)} chapters",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(f"Outline saved to file: {report_id}/outline.json")
            
            # Giai đoạn 2: Tạo từng chương (lưu theo từng chương)
            report.status = ReportStatus.GENERATING
            
            total_sections = len(outline.sections)
            generated_sections = []  # Lưu nội dung lại cho ngữ cảnh những lần sau
            
            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # Cập nhật tiến độ
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"Generating chapter: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )
                
                if progress_callback:
                    progress_callback(
                        "generating", 
                        base_progress, 
                        f"Generating chapter: {section.title} ({section_num}/{total_sections})"
                    )
                
                # Tạo nội dung chương
                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(
                            stage, 
                            base_progress + int(prog * 0.7 / total_sections),
                            msg
                        ) if progress_callback else None,
                    section_index=section_num
                )
                
                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # Lưu chương
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # Ghi lại kết quả khi chương ra lò
                full_section_content = f"## {section.title}\n\n{section_content}"

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip()
                    )

                logger.info(f"Chapter saved: {report_id}/section_{section_num:02d}.md")
                
                # Cập nhật thanh tiến độ
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    f"Chapter {section.title} completed",
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # Giai đoạn 3: Ghép lại toàn bộ báo cáo
            if progress_callback:
                progress_callback("generating", 95, "Assembling full report...")
            
            ReportManager.update_progress(
                report_id, "generating", 95, "Assembling full report...",
                completed_sections=completed_section_titles
            )
            
            # Dùng ReportManager để ráp báo cáo
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            
            # Tính toán thời gian
            total_time_seconds = (datetime.now() - start_time).total_seconds()
            
            # Ghi nhận log khi tạo thành công
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds
                )
            
            # Lưu kết quả cuối cùng
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "Report generation completed",
                completed_sections=completed_section_titles
            )
            
            if progress_callback:
                progress_callback("completed", 100, "Report generation completed")
            
            logger.info(f"Report generation completed: {report_id}")
            
            # Tắt ghi log console
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
            
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            report.status = ReportStatus.FAILED
            report.error = str(e)
            
            # Ghi lại log lỗi
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # Lưu lại trạng thái failed
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"Report generation failed: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # Lờ đi nếu bị lỗi trong khi lưu
            
            # Tắt console log
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None
            
            return report
    
    def chat(
        self, 
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Trò chuyện cùng Report Agent
        
        Trong quá trình chat, Agent có khả năng tự gọi công cụ tìm kiếm để trả lời
        
        Args:
            message: Tin nhắn mới của người dùng
            chat_history: Lịch sử đàm thoại
            
        Returns:
            {
                "response": "Nội dung trả lời của Agent",
                "tool_calls": [Danh sách các công cụ đã sử dụng],
                "sources": [Nguồn thông tin]
            }
        """
        logger.info(f"Report Agent chat: {message[:50]}...")
        
        chat_history = chat_history or []
        
        # Nhúng nội dung báo cáo cũ vào
        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                # Cắt bớt độ dài vì tránh nghẽn bộ nhớ
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [Report content truncated] ..."
        except Exception as e:
            logger.warning(f"Failed to get report content: {e}")
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "(No report available)",
            tools_description=self._get_tools_description(),
        )

        # Xây dựng message
        messages = [{"role": "system", "content": system_prompt}]
        
        # Nạp lịch sử cuộc trò chuyện
        for h in chat_history[-10:]:  # Giới hạn số lượng tin nhắn quá khứ
            messages.append(h)
        
        # Nạp tin nhắn mới nhất
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # Vòng lặp ReACT (phiên bản thu gọn)
        tool_calls_made = []
        max_iterations = 2  # Giảm số lần lặp
        
        for iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # Phân tích lệnh gọi công cụ
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # Không thấy gọi công cụ, trả luôn kết quả
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # Khởi chạy công cụ (giới hạn số lượng)
            tool_results = []
            for call in tool_calls[:1]:  # Cả vòng chỉ cho chạy công cụ tối đa 1 lần
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # Giới hạn kích thước kết quả để tránh nghẽn
                })
                tool_calls_made.append(call)
            
            # Đắp kết quả vào message
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']} result]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # Đã đạt giới hạn lặp, sinh câu trả lời chốt chặn
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # Dọn dẹp phản hồi
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    Trình Quản lý Báo cáo
    
    Phụ trách việc lưu trữ lâu dài và trích xuất báo cáo
    
    Cấu trúc thư mục (Lưu báo cáo phân thành từng chương):
    reports/
      {report_id}/
        meta.json          - File metadata và trạng thái
        outline.json       - Dàn ý
        progress.json      - Tiến trình phát sinh báo cáo
        section_01.md      - Chương 1
        section_02.md      - Chương 2
        ...
        full_report.md     - Báo cáo hoàn chỉnh
    """
    
    # Phân vùng lưu trữ gốc
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')
    
    @classmethod
    def _ensure_reports_dir(cls):
        """Đảm bảo thư mục lưu trữ gốc luôn tồn tại"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """Lấy đường dẫn thư mục báo cáo"""
        return os.path.join(cls.REPORTS_DIR, report_id)
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """Đảm bảo thư mục báo cáo tồn tại (và trả lại đường dẫn)"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """Lấy file chi tiết cơ bản của báo cáo"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """Lấy file báo cáo dạng Markdown hợp nhất"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")
    
    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """Lấy file mang nội dung dàn ý"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """Lấy file tiến độ tạo báo cáo"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """Lấy file cho một chương Markdown chỉ định"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """Đường dẫn của Nhật ký Agent"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """Đường dẫn của file console log"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Lấy nội dung ghi chép file console_log
        
        Đây là text được in ra khi tạo báo cáo (INFO, WARNING, v.v.),
        Khác với báo cáo có cấu trúc JSON của agent_log.jsonl
        
        Args:
            report_id: ID báo cáo
            from_line: Bắt đầu lấy từ dòng nào (để phục vụ chế độ tải tuần tự cho front-end, truyền 0 để lấy từ đầu)
            
        Returns:
            {
                "logs": [Danh sách text log],
                "total_lines": Tổng dòng hiện có,
                "from_line": Số thứ tự dòng bắt đầu,
                "has_more": Cờ xét còn trang sau không
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # Giữ nguyên bản text, gạt bỏ breakline cuối chuỗi
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Vì đã đọc kịch sàn file
        }
        
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        Lấy toàn bộ console log (lấy một lần duy nhất)
        
        Args:
            report_id: ID báo cáo
            
        Returns:
            Danh sách dòng log
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        Lấy nội dung Agent log
        
        Args:
            report_id: ID báo cáo
            from_line: Bắt đầu lấy từ dòng nào (để phục vụ chế độ tải tuần tự cho front-end, truyền 0 để lấy từ đầu)
            
        Returns:
            {
                "logs": [Danh sách đối tượng log],
                "total_lines": Tổng dòng hiện có,
                "from_line": Số thứ tự dòng bắt đầu,
                "has_more": Cờ xét còn trang sau không
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # Bỏ qua những dòng parse trượt
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # Đã tới kịch trần file
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Lấy toàn bộ nội dung agent_log (để lấy một cú tóm gọn)
        
        Args:
            report_id: ID báo cáo
            
        Returns:
            Danh sách đối tượng log
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        Lưu báo cáo dàn ý
        
        Gọi ngay lập tức khi hoàn thành việc lên kế hoạch (planning)
        """
        cls._ensure_report_folder(report_id)
        
        with open(cls._get_outline_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Outline saved: {report_id}")
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        Lưu từng chương đơn lẻ

        Gọi ngay sau khi tạo xong chương báo cáo, thực hiện việc in ấn từng phần

        Args:
            report_id: ID báo cáo
            section_index: Chỉ mục chương (Cơ sở 1)
            section: Đối tượng chương

        Returns:
            Đường dẫn thư mục được ghi
        """
        cls._ensure_report_folder(report_id)

        # Build Markdown content cho chương - xóa những tiêu đề trùng (nếu có)
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # Ghi đè tệp tin
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"Chapter saved: {report_id}/{file_suffix}")
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        Làm sạch nội dung chương
        
        1. Xóa các dòng tiêu đề Markdown ở đầu trùng lặp với tiêu đề chương
        2. Biến đổi những tiêu đề cấp ### trở xuống thành in đậm
        
        Args:
            content: Nội dung thô
            section_title: Tiêu đề chương
            
        Returns:
            Nội dung sau khi làm sạch
        """
        import re
        
        if not content:
            return content
        
        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Kiểm tra dòng này có phải heading sinh từ MD không
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()
                
                # Bỏ qua nếu tiêu đề ở tầm 5 dòng đầu lại trùng khớp với nhan đề chính
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue
                
                # Đổi toàn bộ các tag MD heading (#, ##, ###, v.v...) sang in đậm Text
                # Do heading đã được config sinh từ tool gốc, không nên có MD style tại đây
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # Gắn thêm dòng trống
                continue
            
            # Nếu dòng kề là dòng trắng thuộc chuỗi heading trùng lặp, cần lược bỏ luôn
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # Bỏ đi mấy block dòng trắng vô danh ở mở đầu
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # Xóa các gạch đường phân cách ở đầu
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # Remove đồng thời new lines gắn theo gạch ngang
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls, 
        report_id: str, 
        status: str, 
        progress: int, 
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None
    ) -> None:
        """
        Cập nhật tiến độ tạo báo cáo
        
        Frontend có thể lấy tiến độ real-time theo progress.json
        """
        cls._ensure_report_folder(report_id)
        
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        
        with open(cls._get_progress_path(report_id), 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Lấy tiến độ tạo báo cáo"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        Lấy danh sách các chương đã tạo xong
        
        Trả về toàn bộ thông tin tệp từng phần
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Phân tích index của chương từ tên tệp
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        Lắp ráp toàn bộ báo cáo
        
        Từ các chương đã lưu, tổng chắp báo cáo lại và dọn dẹp nhan đề
        """
        folder = cls._get_report_folder(report_id)
        
        # Build phần Header báo cáo
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += f"---\n\n"
        
        # Đọc files từ mọi chương theo thứ tự
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # Hậu kiểm: dọn dẹp cấu trúc nhan đề trong toàn bộ file Markdown
        md_content = cls._post_process_report(md_content, outline)
        
        # Ghi lại tệp rốt cục
        full_path = cls._get_report_markdown_path(report_id)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        logger.info(f"Full report assembled: {report_id}")
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        Hậu kiểm nội dung báo cáo
        
        1. Xóa nhan đề trùng lặp
        2. Dữ nguyên nhan đề chính (#) và nhan đề chương (##), xóa/giảm các tag nhan đề phụ (###, #### v.v)
        3. Dọn dẹp khoảng trống và đường ranh giới thừa thãi
        
        Args:
            content: Nội dung thô của báo cáo
            outline: Dàn ý
            
        Returns:
            Nội dung sau khi xử lý
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # Gom góp tất thảy nhan đề từ outline
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Kiểm tra coi đây có là nhan đề hay không
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Kiểm tra nhan đề này đang quẩn quanh lặp lại chuỗi cũ chăng (ngưỡng 5 dòng)
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # Rũ đi dòng nhan đề trùng lặp và các dòng newline ngay sau
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # Xử lý quy mô cấp bậc tiêu đề:
                # - # (level=1) Chỉ dành cho nhan đề lõi của toàn văn kiện
                # - ## (level=2) Bám dính tiêu đề chương mục
                # - ### và thấp hơn (level>=3) Băm thành chữ in đậm
                
                if level == 1:
                    if title == outline.title:
                        # Giữ nhan đề gốc
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # Do nhan đề chương đánh bừa ra thẻ #, buộc ép về lại ##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # Các tiêu đề cấp 1 tạp nham cho in đậm
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # Bảo lưu nhan đề chương
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # Nếu chả phải chương thì in đậm nốt thẻ cấp 2
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                else:
                    # Thẻ cấp 3 trở đi cho in đậm
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False
                
                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # Tránh lôi đường chia gạch dưới title
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # Ngậm 1 dòng trắng kề sau nhan đề
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # Vuốt láng khoảng trắng đa tầng (chừa max 2)
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """Lưu lại metadata và toàn văn báo cáo"""
        cls._ensure_report_folder(report.report_id)
        
        # Ghi meta file dạng JSON
        with open(cls._get_report_path(report.report_id), 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # Ghi mục lục tổng quan
        if report.outline:
            cls.save_outline(report.report_id, report.outline)
        
        # Lưu file MD trọn gói
        if report.markdown_content:
            with open(cls._get_report_markdown_path(report.report_id), 'w', encoding='utf-8') as f:
                f.write(report.markdown_content)
        
        logger.info(f"Report saved: {report.report_id}")
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """Lấy về toàn văn mục báo cáo"""
        path = cls._get_report_path(report_id)
        
        if not os.path.exists(path):
            # Tương thích ngược: thử xem file .json trần trụi ở ngay thư mục gốc
            old_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Cấu trúc lại model
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # Nếu chưa bếch được đoạn markdown thì tìm từ file .md
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error')
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """Tìm báo cáo thông qua ID phiến giả lập"""
        cls._ensure_reports_dir()
        
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Định dạng mới coi nó là directory
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    return report
            # Tương thích format cũ: .json
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    return report
        
        return None
    
    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """Liệt kê rổ báo cáo"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # Standard mới
            if os.path.isdir(item_path):
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # Standard quá độ .json
            elif item.endswith('.json'):
                report_id = item[:-5]
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # Sort descending bởi thời gian tạo
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """Xóa rễ cụm folder tương ứng với report"""
        import shutil
        
        folder_path = cls._get_report_folder(report_id)
        
        # Định dạng mới quăng folder là mượt
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            logger.info(f"Report folder removed: {report_id}")
            return True
        
        # Mode tương thích: xóa file
        deleted = False
        old_json_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.json")
        old_md_path = os.path.join(cls.REPORTS_DIR, f"{report_id}.md")
        
        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True
        
        return deleted
