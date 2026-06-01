"""
Quản lý cấu hình
Tải cấu hình thống nhất từ tệp .env ở thư mục gốc dự án
"""

import os
from dotenv import load_dotenv

# Tải tệp .env ở thư mục gốc dự án
# Đường dẫn: MiroFish/.env (tương đối với backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # Nếu thư mục gốc không có .env, thử nạp biến môi trường sẵn có (cho production)
    load_dotenv(override=True)


class Config:
    """Lớp cấu hình cho Flask"""
    
    # Cấu hình Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # Cấu hình JSON - tắt escape ASCII để tiếng Trung hiển thị trực tiếp (thay vì dạng \uXXXX)
    JSON_AS_ASCII = False
    
    # Cấu hình LLM (thống nhất theo định dạng OpenAI)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Cấu hình Neo4j (Graphiti backend)
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD')

    # Cấu hình Embedding (fallback về LLM_API_KEY nếu không set riêng)
    EMBEDDING_API_KEY = os.environ.get('EMBEDDING_API_KEY') or os.environ.get('LLM_API_KEY')
    EMBEDDING_BASE_URL = os.environ.get('EMBEDDING_BASE_URL', 'https://api.openai.com/v1')
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'text-embedding-3-small')
    
    # Cấu hình upload tệp
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # Cấu hình xử lý văn bản
    DEFAULT_CHUNK_SIZE = 500  # Kích thước chunk mặc định
    DEFAULT_CHUNK_OVERLAP = 50  # Độ chồng lấp mặc định
    
    # Cấu hình mô phỏng OASIS
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # Cấu hình action khả dụng theo nền tảng OASIS
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Cấu hình Report Agent
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls):
        """Kiểm tra các cấu hình bắt buộc"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is not configured")
        if not cls.NEO4J_URI:
            errors.append("NEO4J_URI is not configured")
        if not cls.NEO4J_PASSWORD:
            errors.append("NEO4J_PASSWORD is not configured")
        if not cls.EMBEDDING_API_KEY:
            errors.append("EMBEDDING_API_KEY is not configured (set EMBEDDING_API_KEY or LLM_API_KEY)")
        return errors

