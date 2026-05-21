"""
图谱分页读取工具（存根模块）

原来封装 Zep Cloud 的分页逻辑。
现在图谱数据存储在本地 JSON 文件中，不再需要分页。
本模块保留以避免破坏未更新的旧导入。
"""

from __future__ import annotations

from ..utils.logger import get_logger

logger = get_logger('mirofish.zep_paging')


def fetch_all_nodes(client, graph_id: str, **kwargs) -> list:
    """已废弃：请直接使用 LocalGraphStore.get_nodes()"""
    logger.warning("fetch_all_nodes 已废弃，请使用 LocalGraphStore.get_nodes()")
    return []


def fetch_all_edges(client, graph_id: str, **kwargs) -> list:
    """已废弃：请直接使用 LocalGraphStore.get_edges()"""
    logger.warning("fetch_all_edges 已废弃，请使用 LocalGraphStore.get_edges()")
    return []
