"""
Zep API 速率限制与响应缓存

为 Zep Cloud FREE 计划提供保护：
- 响应缓存：graph data 请求在 TTL 内返回缓存结果，避免重复调用 Zep API
- 可通过 .env 配置参数，升级付费计划后可放宽限制
"""

import time
import threading
from typing import Any, Dict, Optional, Tuple

from .logger import get_logger

logger = get_logger('mirofish.zep_cache')


class ZepResponseCache:
    """
    线程安全的 Zep API 响应缓存。

    缓存 graph data 的成功响应，在 TTL 内直接返回缓存数据，
    避免频繁调用 Zep API 导致 429 错误。
    """

    def __init__(self, default_ttl: int = 30):
        """
        Args:
            default_ttl: 默认缓存生存时间（秒）。0 表示不缓存。
        """
        self._cache: Dict[str, Tuple[float, Any]] = {}  # key -> (expire_time, data)
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    @property
    def ttl(self) -> int:
        return self._default_ttl

    @ttl.setter
    def ttl(self, value: int):
        self._default_ttl = max(0, value)

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据。如果缓存存在且未过期，返回数据；否则返回 None。
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            expire_time, data = entry
            if time.time() > expire_time:
                # 缓存已过期
                del self._cache[key]
                logger.debug(f"Cache expired for key: {key}")
                return None

            remaining = int(expire_time - time.time())
            logger.debug(f"Cache hit for key: {key} (expires in {remaining}s)")
            return data

    def set(self, key: str, data: Any, ttl: Optional[int] = None):
        """
        设置缓存数据。

        Args:
            key: 缓存键
            data: 要缓存的数据
            ttl: 缓存生存时间（秒）。None 表示使用默认 TTL。
        """
        effective_ttl = ttl if ttl is not None else self._default_ttl
        if effective_ttl <= 0:
            return  # 不缓存

        with self._lock:
            self._cache[key] = (time.time() + effective_ttl, data)
            logger.debug(f"Cache set for key: {key} (TTL={effective_ttl}s)")

    def invalidate(self, key: str):
        """删除指定缓存。"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache invalidated for key: {key}")

    def clear(self):
        """清除所有缓存。"""
        with self._lock:
            self._cache.clear()
            logger.debug("Cache cleared")


# 全局缓存实例（在模块加载时创建，TTL 在 app 初始化时通过 Config 设置）
graph_data_cache = ZepResponseCache(default_ttl=30)
