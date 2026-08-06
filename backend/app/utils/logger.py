"""
日志配置模块
提供统一的日志管理，同时输出到控制台和文件
"""

import os
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _ensure_utf8_stdout():
    """
    确保 stdout/stderr 使用 UTF-8 编码
    解决 Windows 控制台中文乱码问题
    """
    if sys.platform == 'win32':
        # Windows 下重新配置标准输出为 UTF-8
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')


def setup_logger(name: str = 'mirofish', level: int = logging.DEBUG) -> logging.Logger:
    """
    设置日志器
    
    Args:
        name: 日志器名称
        level: 日志级别
        
    Returns:
        配置好的日志器
    """
    # 确保日志目录存在
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # 创建日志器
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 阻止日志向上传播到根 logger，避免重复输出
    logger.propagate = False
    
    # 如果已经有处理器，不重复添加
    if logger.handlers:
        return logger
    
    # 日志格式
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # 1. 文件处理器 - 详细日志（按日期命名，带轮转）
    log_filename = datetime.now().strftime('%Y-%m-%d') + '.log'
    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, log_filename),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # 2. 控制台处理器 - 简洁日志（INFO及以上）
    # 确保 Windows 下使用 UTF-8 编码，避免中文乱码
    _ensure_utf8_stdout()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = 'mirofish') -> logging.Logger:
    """
    获取日志器（如果不存在则创建）
    
    Args:
        name: 日志器名称
        
    Returns:
        日志器实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


# 创建默认日志器
logger = setup_logger()


# 便捷方法
def debug(msg: str, *args, **kwargs) -> None:
    logger.debug(msg, *args, **kwargs)

def info(msg: str, *args, **kwargs) -> None:
    logger.info(msg, *args, **kwargs)

def warning(msg: str, *args, **kwargs) -> None:
    logger.warning(msg, *args, **kwargs)

def error(msg: str, *args, **kwargs) -> None:
    logger.error(msg, *args, **kwargs)

def critical(msg: str, *args, **kwargs) -> None:
    logger.critical(msg, *args, **kwargs)

