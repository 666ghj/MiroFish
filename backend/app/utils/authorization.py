"""
中心化资源所有权授权（resource-level authorization）。

认证中间件（app.utils.auth）负责回答"你是谁"，把结果写入 flask.g.current_user_id。
本模块负责回答"你能不能操作这个资源"：把已获取的资源对象（Project /
SimulationState / Report，或任何带 owner_id 属性的对象）与当前请求的用户比对。

约定：
- 若认证功能未启用（Config.API_KEYS 为空），g.current_user_id 恒为 None，
  且所有资源在创建时也会把 owner_id 记为 None —— 因此下面的比较永远视为同一
  用户，单用户/本地场景不受影响。
- 若认证已启用，g.current_user_id 在进入视图函数时保证是一个已认证用户
  （认证中间件已在此之前拒绝匿名请求），但资源的 owner_id 仍可能是 None——
  这只会发生在启用认证之前就已创建的历史数据上。这些历史资源被视为"无主"
  资源，任何已认证用户都可以访问，避免升级后所有旧数据被永久锁死；新创建的
  资源会始终记录 owner_id，因此不受此例外影响。

调用方应先像现在一样完成"资源是否存在"的查找与 404 处理，再对已取到的资源
调用 authorize()。authorize(None) 是安全的空操作，不会影响既有的 404 逻辑。
"""

from typing import Optional

from flask import g


class ForbiddenError(Exception):
    """Raised when the current user is authenticated but does not own the resource."""


def current_user_id() -> Optional[str]:
    return getattr(g, 'current_user_id', None)


def check_owner(resource_owner_id: Optional[str]) -> None:
    """Raise ForbiddenError if the current user does not own a resource with this owner_id."""
    user_id = current_user_id()
    if user_id is None:
        # Authentication disabled — no ownership enforcement.
        return
    if resource_owner_id is None:
        # Legacy resource created before ownership tracking existed.
        return
    if resource_owner_id != user_id:
        raise ForbiddenError("You do not have access to this resource")


def authorize(resource) -> None:
    """
    Check that the current user owns `resource` (anything with an `owner_id`
    attribute — Project / SimulationState / Report). No-op if `resource` is
    None so existing "not found" handling at call sites keeps working as-is.
    """
    if resource is None:
        return
    check_owner(getattr(resource, 'owner_id', None))


def is_owned_by_current_user(resource) -> bool:
    """Non-raising variant of authorize(), for filtering list endpoints."""
    if resource is None:
        return False
    user_id = current_user_id()
    owner_id = getattr(resource, 'owner_id', None)
    if user_id is None or owner_id is None:
        return True
    return owner_id == user_id


def authorize_any(resources) -> None:
    """
    Raise ForbiddenError unless the current user owns at least one resource in
    `resources` (used where a single downstream identifier, e.g. a Zep graph_id,
    can be reached through more than one locally tracked resource). An empty
    list is treated as "no proof of access" and rejected, except when
    authentication is disabled entirely.
    """
    if current_user_id() is None:
        return
    if any(is_owned_by_current_user(r) for r in resources if r is not None):
        return
    raise ForbiddenError("You do not have access to this resource")
