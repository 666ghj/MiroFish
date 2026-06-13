"""
安全辅助函数（评审 H5 / 上传嗅探 / 路径校验）。
- safe_traceback: 仅在 DEBUG 时把堆栈返回客户端，生产环境只记到服务端日志
- validate_id:    校验 URL 传入的 id，避免落入文件系统 sink（路径穿越/异常字符）
- upload_content_ok: 按魔术字节嗅探上传内容，防止改扩展名的二进制混入
"""

import os
import re
import traceback as _traceback

from .logger import get_logger

# 允许的 id 字符集：字母数字 + 下划线 + 连字符，长度 1-64。
# 排除 '/'、'.'、'\\' 等可用于路径穿越或越级的字符。
_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def safe_traceback() -> str:
    """
    H5：完整堆栈始终写入服务端日志；仅在 DEBUG 模式才把堆栈返回客户端，
    生产环境返回通用提示，避免向客户端泄露内部路径/栈帧。
    """
    # 延迟导入 Config，避免与配置模块的潜在循环依赖
    from ..config import Config
    tb = _traceback.format_exc()
    get_logger('mirofish.error').error(tb)
    return tb if Config.DEBUG else 'Internal server error (see server logs)'


def safe_error(e) -> str:
    """
    客户端可见的错误文案：DEBUG 模式返回异常消息，生产环境返回通用提示，
    避免异常消息本身（如 FileNotFoundError 的路径、ValueError 里的配置值）泄露给客户端。
    完整异常仍由各调用点的 logger.error / safe_traceback 记到服务端日志。
    """
    from ..config import Config
    return str(e) if Config.DEBUG else 'Internal server error (see server logs)'


def validate_id(value: str, kind: str = 'id') -> str:
    """
    路径校验：拒绝任何不匹配 _ID_RE 的 id（含 '..'、'/'、空值），
    在 id 进入 os.path.join / makedirs / rmtree 之前阻断路径穿越。
    """
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValueError(f'Invalid {kind}: {value!r}')
    return value


def upload_content_ok(file_storage, filename: str) -> bool:
    """
    上传嗅探：按扩展名校验文件头部内容，使改名的二进制无法通过扩展名白名单。
    - pdf：必须以 %PDF- 开头
    - txt/md/markdown：头部不得含 NUL 字节（典型二进制特征）
    读取后将流指针复位，避免影响后续保存。
    """
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    head = file_storage.read(512)
    file_storage.seek(0)
    if ext == 'pdf':
        return head[:5] == b'%PDF-'
    if ext in ('txt', 'md', 'markdown'):
        # 接受带 BOM 的 UTF-16/UTF-32/UTF-8 文本（这些合法文本会含 NUL 字节，
        # 与 file_parser 的多编码支持一致）；否则按头部含 NUL 判定为二进制并拒绝。
        if head.startswith((b'\xff\xfe', b'\xfe\xff', b'\xef\xbb\xbf')):
            return True
        return b'\x00' not in head
    return False
