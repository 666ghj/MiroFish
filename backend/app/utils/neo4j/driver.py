"""
Neo4j 数据库连接管理
提供 Neo4j 驱动的初始化、连接池管理和健康检查
"""

import os
from typing import Optional
from dataclasses import dataclass

from neo4j import GraphDatabase
from neo4j import Driver
from neo4j.exceptions import ServiceUnavailable, AuthError

from ...config import Config
from ..logger import get_logger

logger = get_logger('mirofish.neo4j')


@dataclass
class Neo4jConfig:
    """Neo4j 配置"""
    uri: str
    username: str
    password: str
    database: str = "neo4j"
    max_connection_pool_size: int = 50
    connection_acquisition_timeout: int = 60


class Neo4jDriverManager:
    """
    Neo4j 驱动管理器

    管理 Neo4j 连接池，支持单例模式
    """

    _instance: Optional['Neo4jDriverManager'] = None
    _driver: Optional[Driver] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._config: Optional[Neo4jConfig] = None
            self._driver: Optional[Driver] = None

    def _load_config(self) -> Neo4jConfig:
        """从环境变量加载配置"""
        uri = Config.NEO4J_URI
        username = Config.NEO4J_USERNAME
        password = Config.NEO4J_PASSWORD
        database = Config.NEO4J_DATABASE

        return Neo4jConfig(
            uri=uri,
            username=username,
            password=password,
            database=database,
            max_connection_pool_size=Config.NEO4J_MAX_POOL_SIZE,
            connection_acquisition_timeout=int(os.environ.get('NEO4J_CONNECT_TIMEOUT', '60'))
        )

    def get_driver(self) -> Driver:
        """
        获取 Neo4j 驱动（单例）

        Returns:
            Neo4j Driver 实例

        Raises:
            ValueError: 如果配置不完整
        """
        if self._driver is None:
            self._config = self._load_config()

            if not self._config.password:
                raise ValueError(
                    "Neo4j 密码未配置，请设置 NEO4J_PASSWORD 环境变量"
                )

            logger.info(f"创建 Neo4j 驱动: {self._config.uri}")

            self._driver = GraphDatabase.driver(
                self._config.uri,
                auth=(self._config.username, self._config.password),
                max_connection_pool_size=self._config.max_connection_pool_size,
                connection_acquisition_timeout=self._config.connection_acquisition_timeout
            )

        return self._driver

    def close(self):
        """关闭驱动"""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j 驱动已关闭")

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            True 如果连接正常
        """
        try:
            driver = self.get_driver()
            with driver.session(database=self._config.database) as session:
                result = session.run("RETURN 1 AS test")
                result.single()
            return True
        except AuthError as e:
            logger.error(f"Neo4j 认证失败: {e}")
            return False
        except ServiceUnavailable as e:
            logger.error(f"Neo4j 服务不可用: {e}")
            return False
        except Exception as e:
            logger.error(f"Neo4j 健康检查失败: {e}")
            return False

    def verify_connectivity(self) -> bool:
        """
        验证连接（带重试）

        Returns:
            True 如果连接成功
        """
        import time

        max_retries = 3
        for attempt in range(max_retries):
            if self.health_check():
                logger.info("Neo4j 连接验证成功")
                return True

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避
                logger.warning(f"Neo4j 连接验证失败，{wait_time}秒后重试...")
                time.sleep(wait_time)

        return False


# 全局实例
_neo4j_manager = Neo4jDriverManager()


def get_neo4j_driver() -> Driver:
    """获取 Neo4j 驱动的便捷函数"""
    return _neo4j_manager.get_driver()


def close_neo4j_driver():
    """关闭 Neo4j 驱动的便捷函数"""
    _neo4j_manager.close()


def neo4j_health_check() -> bool:
    """Neo4j 健康检查的便捷函数"""
    return _neo4j_manager.health_check()
