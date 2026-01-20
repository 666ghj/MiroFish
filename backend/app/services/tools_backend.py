"""
Tools service backend factory.

Switches between ZepToolsService and LocalToolsService based on Config.GRAPH_BACKEND.
"""

from __future__ import annotations

from ..config import Config
from app.services.zep.zep_tools import ZepToolsService
from app.services.local.local_tools import LocalToolsService


def get_tools_service() -> ZepToolsService | LocalToolsService:
    """
    获取工具服务
    
    Returns:
        ZepToolsService 或 LocalToolsService 实例
    """
    return ZepToolsService() if Config.GRAPH_BACKEND == "zep" else LocalToolsService()
