"""
图谱记忆管理器工厂

根据 GRAPH_BACKEND 配置返回对应的图谱记忆管理器：
- "zep": 使用 ZepGraphMemoryManager（Zep Cloud）
- "local": 使用 LocalGraphMemoryManager（本地 Neo4j）
"""

from typing import Type, Union

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.graph_memory_backend")

from .zep_graph_memory_updater import ZepGraphMemoryManager
from .local_graph_memory_updater import LocalGraphMemoryManager


def get_graph_memory_manager() -> type[ZepGraphMemoryManager | LocalGraphMemoryManager]:
    """
    获取图谱记忆管理器类
    
    Returns:
        ZepGraphMemoryManager 或 LocalGraphMemoryManager 类
    """
    backend = Config.GRAPH_BACKEND.lower()
    
    if backend == "zep":
        logger.debug("使用 ZepGraphMemoryManager")
        return ZepGraphMemoryManager
    else:
        logger.debug("使用 LocalGraphMemoryManager")
        return LocalGraphMemoryManager


def create_memory_updater(simulation_id: str, graph_id: str):
    """
    创建图谱记忆更新器实例
    
    这是一个便捷函数，直接调用对应管理器的 create_updater 方法。
    
    Args:
        simulation_id: 模拟ID
        graph_id: 图谱ID
        
    Returns:
        图谱记忆更新器实例
    """
    manager = get_graph_memory_manager()
    return manager.create_updater(simulation_id, graph_id)


def get_memory_updater(simulation_id: str):
    """
    获取已存在的图谱记忆更新器
    
    Args:
        simulation_id: 模拟ID
        
    Returns:
        图谱记忆更新器实例，如果不存在则返回 None
    """
    manager = get_graph_memory_manager()
    return manager.get_updater(simulation_id)


def stop_memory_updater(simulation_id: str):
    """
    停止图谱记忆更新器
    
    Args:
        simulation_id: 模拟ID
    """
    manager = get_graph_memory_manager()
    manager.stop_updater(simulation_id)


def stop_all_memory_updaters():
    """
    停止所有图谱记忆更新器
    """
    manager = get_graph_memory_manager()
    manager.stop_all()


def get_all_memory_stats():
    """
    获取所有更新器的统计信息
    
    Returns:
        字典，包含各模拟的统计信息
    """
    manager = get_graph_memory_manager()
    return manager.get_all_stats()
