"""
中心化 API 认证。

当前实现为 API Key 认证：客户端通过 `Authorization: Bearer <key>` 或
`X-API-Key: <key>` 请求头携带凭证，服务端在 Config.API_KEYS 中查找匹配的
{api_key: user_id} 映射。

若 Config.API_KEYS 为空（未配置 MIROFISH_API_KEYS），则视为未启用认证，
所有请求都会被当作匿名请求放行（仅适用于本地单用户场景，参见
Config.validate() 中的告警）。

本模块只负责“你是谁”（认证）。“你能不能操作这个资源”（基于资源所有权的
授权）由后续任务负责，会消费这里写入 flask.g.current_user_id 的值。
"""

import hmac
from typing import Optional

from flask import request

from ..config import Config


class AuthenticationError(Exception):
    """Raised when a request carries no, or an invalid, credential while auth is enabled."""


def _extract_presented_key() -> Optional[str]:
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        candidate = auth_header[len('Bearer '):].strip()
        return candidate or None

    api_key_header = request.headers.get('X-API-Key')
    if api_key_header:
        return api_key_header.strip() or None

    return None


def authenticate_request() -> Optional[str]:
    """
    对当前 Flask 请求进行认证。

    Returns:
        已认证用户的 user_id；若认证功能未启用（Config.API_KEYS 为空）则返回 None。

    Raises:
        AuthenticationError: 认证已启用，但请求未携带凭证或凭证不匹配任何已配置的 API Key。
    """
    if not Config.API_KEYS:
        return None

    presented = _extract_presented_key()
    if not presented:
        raise AuthenticationError("Missing API key")

    for configured_key, user_id in Config.API_KEYS.items():
        if hmac.compare_digest(configured_key, presented):
            return user_id

    raise AuthenticationError("Invalid API key")
