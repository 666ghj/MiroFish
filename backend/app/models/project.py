"""
Quản lý context (ngữ cảnh) của dự án
Được sử dụng để lưu trữ trạng thái dự án trên server (persistence),
giúp tránh việc frontend phải gửi đi một lượng lớn dữ liệu mỗi lần gọi API.
"""

import os
import json
import uuid
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field, asdict
from ..config import Config


class ProjectStatus(str, Enum):
    """Trạng thái hiện tại của dự án"""
    CREATED = "created"              # Dự án vừa được tạo, các file đã được tải lên thành công
    ONTOLOGY_GENERATED = "ontology_generated"  # Đã hoàn tất khởi tạo Ontology 
    GRAPH_BUILDING = "graph_building"    # Tri thức đồ thị (Knowledge Graph) đang được xây dựng
    GRAPH_COMPLETED = "graph_completed"  # Đã hoàn thành quá trình Graph
    FAILED = "failed"                # Thiết lập / Xử lý gặp lỗi


@dataclass
class Project:
    """Mô hình dữ liệu (Data model) của dự án"""
    project_id: str
    name: str
    status: ProjectStatus
    created_at: str
    updated_at: str
    
    # File information
    files: List[Dict[str, str]] = field(default_factory=list)  # [{filename, path, size}]
    total_text_length: int = 0
    
    # Thông tin ontology (được điền sau khi API 1 xử lý xong)
    ontology: Optional[Dict[str, Any]] = None
    analysis_summary: Optional[str] = None
    
    # Thông tin graph (được điền sau khi API 2 hoàn thành)
    graph_id: Optional[str] = None
    graph_build_task_id: Optional[str] = None
    
    # Cấu hình
    simulation_requirement: Optional[str] = None
    chunk_size: int = 500
    chunk_overlap: int = 50
    
    # Thông tin lỗi
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Biến đổi đối tượng (Object) thành Dictionary (để dễ dàng chuyển thành JSON và lưu trữ)"""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, ProjectStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": self.files,
            "total_text_length": self.total_text_length,
            "ontology": self.ontology,
            "analysis_summary": self.analysis_summary,
            "graph_id": self.graph_id,
            "graph_build_task_id": self.graph_build_task_id,
            "simulation_requirement": self.simulation_requirement,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "error": self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        """Khởi tạo một instance Project từ dữ liệu kiểu Dictionary (khi load lên từ hệ thống lưu trữ)"""
        status = data.get('status', 'created')
        if isinstance(status, str):
            status = ProjectStatus(status)
        
        return cls(
            project_id=data['project_id'],
            name=data.get('name', 'Unnamed Project'),
            status=status,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            files=data.get('files', []),
            total_text_length=data.get('total_text_length', 0),
            ontology=data.get('ontology'),
            analysis_summary=data.get('analysis_summary'),
            graph_id=data.get('graph_id'),
            graph_build_task_id=data.get('graph_build_task_id'),
            simulation_requirement=data.get('simulation_requirement'),
            chunk_size=data.get('chunk_size', 500),
            chunk_overlap=data.get('chunk_overlap', 50),
            error=data.get('error')
        )


class ProjectManager:
    """Quản lý các dự án (ProjectManager) - Chịu trách nhiệm lưu trữ và truy xuất thông tin dự án"""
    
    # Thư mục gốc để lưu trữ toàn bộ dữ liệu dự án trên máy chủ
    PROJECTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'projects')
    
    @classmethod
    def _ensure_projects_dir(cls):
        """Đảm bảo thư mục lưu trữ dự án đã được tạo, nếu không có thì self tạo mới"""
        os.makedirs(cls.PROJECTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_project_dir(cls, project_id: str) -> str:
        """Đường dẫn tới thư mục lưu trữ tương ứng với project_id"""
        return os.path.join(cls.PROJECTS_DIR, project_id)
    
    @classmethod
    def _get_project_meta_path(cls, project_id: str) -> str:
        """Đường dẫn lấy file cài đặt metadata (thường là project.json)"""
        return os.path.join(cls._get_project_dir(project_id), 'project.json')
    
    @classmethod
    def _get_project_files_dir(cls, project_id: str) -> str:
        """Đường dẫn đến thư mục chứa các file nguyên thuỷ do người dùng kéo thả tải lên cho dự án"""
        return os.path.join(cls._get_project_dir(project_id), 'files')
    
    @classmethod
    def _get_project_text_path(cls, project_id: str) -> str:
        """Lấy vị trí của tệp văn bản (txt) đã được hệ thống trích xuất nội dung"""
        return os.path.join(cls._get_project_dir(project_id), 'extracted_text.txt')
    
    @classmethod
    def create_project(cls, name: str = "Unnamed Project") -> Project:
        """
        Khởi tạo và tạo mới cấu trúc dự án trên server
        
        Args:
            name: Tên của dự án
            
        Returns:
            Project object vừa được tạo
        """
        cls._ensure_projects_dir()
        
        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        
        project = Project(
            project_id=project_id,
            name=name,
            status=ProjectStatus.CREATED,
            created_at=now,
            updated_at=now
        )
        
        # Thiết lập các thư mục con trong không gian thư mục của project
        project_dir = cls._get_project_dir(project_id)
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(files_dir, exist_ok=True)
        
        # Ghi các trường thông tin (metadata) của project vào file cứng
        cls.save_project(project)
        
        return project
    
    @classmethod
    def save_project(cls, project: Project) -> None:
        """Ghi chồng cấu hình cập nhật (metadata mới) đối của project vào file (Mặc định: project.json) """
        project.updated_at = datetime.now().isoformat()
        meta_path = cls._get_project_meta_path(project.project_id)
        
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def get_project(cls, project_id: str) -> Optional[Project]:
        """
        Get Project
        
        Args:
            project_id: Project ID
            
        Returns:
            Project object; if it does not exist, return None.
        """
        meta_path = cls._get_project_meta_path(project_id)
        
        if not os.path.exists(meta_path):
            return None
        
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return Project.from_dict(data)
    
    @classmethod
    def list_projects(cls, limit: int = 50) -> List[Project]:
        """
        Lấy danh sách tất cả các dự án (projects) đang có trên system
        
        Args:
            limit: Giới hạn số lượng hiển thị (mặc định lấy 50 project)
            
        Returns:
            Danh sách gồm các Object Project, xếp theo ngày/giờ giảm dần (từ mới tạo -> cũ nhất)
        """
        cls._ensure_projects_dir()
        
        projects = []
        for project_id in os.listdir(cls.PROJECTS_DIR):
            project = cls.get_project(project_id)
            if project:
                projects.append(project)
        
        # Sắp xếp lại lịch sử project theo thứ tự giảm dần thời gian
        projects.sort(key=lambda p: p.created_at, reverse=True)
        
        return projects[:limit]
    
    @classmethod
    def delete_project(cls, project_id: str) -> bool:
        """
        Xoá vĩnh viễn dữ liệu về project và mọi file liên quan của nó khỏi server
        
        Args:
            project_id: Mã ID của Project
            
        Returns:
            Boolean đại diện cờ Thành công / Thất bại của việc xoá
        """
        project_dir = cls._get_project_dir(project_id)
        
        if not os.path.exists(project_dir):
            return False
        
        shutil.rmtree(project_dir) # Xoá toàn bộ thư mục dữ liệu project_id
        return True
    
    @classmethod
    def save_file_to_project(cls, project_id: str, file_storage, original_filename: str) -> Dict[str, str]:
        """
        Ghi dữ liệu file đính kèm mà người dùng upload lên vào kho dự án
        
        Args:
            project_id: Mã định danh của Project
            file_storage: Đối tượng Request File (từ framework, VD: của thư viện Flask/FastAPI) chứa nội dung file byte
            original_filename: Tên ban đầu từ máy tính người dùng
            
        Returns:
            Object chứa kết quả lưu file mới gồm {tên ban đầu, tên hash được lưu, đường dẫn đầy đủ, dung lượng}
        """
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(files_dir, exist_ok=True)
        
        # Biến đổi tên file thành chuỗi an toàn độc nhất (UUID) để giữ các phiên bản không bị ghi đè, với phần mở rộng ban đầu
        ext = os.path.splitext(original_filename)[1].lower()
        safe_filename = f"{uuid.uuid4().hex[:8]}{ext}"
        file_path = os.path.join(files_dir, safe_filename)
        
        # Uỷ quyền lưu vào đường dẫn đích
        file_storage.save(file_path)
        
        # Đếm kích thước dung lượng (byte) của tập tin tĩnh tại ổ cứng
        file_size = os.path.getsize(file_path)
        
        return {
            "original_filename": original_filename,
            "saved_filename": safe_filename,
            "path": file_path,
            "size": file_size
        }
    
    @classmethod
    def save_extracted_text(cls, project_id: str, text: str) -> None:
        """Tạo/ghi văn bản trích xuất (từ nội dung phân tích File upload) cho dự án vào folder dữ liệu"""
        text_path = cls._get_project_text_path(project_id)
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(text)
    
    @classmethod
    def get_extracted_text(cls, project_id: str) -> Optional[str]:
        """Đọc và lấy nội dung File văn bản được trích xuất nếu có trước đó"""
        text_path = cls._get_project_text_path(project_id)
        
        if not os.path.exists(text_path):
            return None
        
        with open(text_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    @classmethod
    def get_project_files(cls, project_id: str) -> List[str]:
        """Lấy danh sách link đường dẫn gốc (absolute path) của các files (Tài liệu upload) thuộc dự án này"""
        files_dir = cls._get_project_files_dir(project_id)
        
        if not os.path.exists(files_dir):
            return []
        
        return [
            os.path.join(files_dir, f) 
            for f in os.listdir(files_dir) 
            if os.path.isfile(os.path.join(files_dir, f))
        ]

