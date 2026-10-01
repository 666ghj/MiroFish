"""
定时事件（event_config.scheduled_events）的共享逻辑

三个运行脚本（run_parallel_simulation.py、run_twitter_simulation.py、
run_reddit_simulation.py）共用这里的两步：

1. group_events_by_round：校验输入并按轮次分组。轮次为 1 基，第 1 轮对应主循环的
   第一次迭代。格式错误的事件记录警告后跳过，不会中断模拟。
2. build_post_actions：把同一轮的帖子合并为一次 env.step() 的动作字典。同一 Agent
   的多条帖子合并为列表，不会互相覆盖。

本模块不依赖 OASIS：动作对象由调用方传入的工厂函数创建，便于单元测试。
"""

from typing import Any, Callable, Dict, List, Optional, Tuple


def _parse_round(value: Any) -> Optional[int]:
    """把轮次解析为整数；无法无损转换时返回 None（不做截断，2.5 不会变成 2）"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def group_events_by_round(
    scheduled_events: Any,
    total_rounds: int,
) -> Tuple[Dict[int, List[Dict[str, Any]]], List[str]]:
    """
    校验定时事件并按轮次分组

    Args:
        scheduled_events: event_config.scheduled_events 的原始值
        total_rounds: 实际模拟轮数（可能已被 max_rounds 截断）

    Returns:
        (events_by_round, warnings)
        - events_by_round: 轮次 -> 事件列表，只包含 1..total_rounds 内的有效事件
        - warnings: 需要输出的警告信息；超出范围的事件明确告警，不静默丢弃
    """
    events_by_round: Dict[int, List[Dict[str, Any]]] = {}
    warnings: List[str] = []

    if not scheduled_events:
        return events_by_round, warnings
    if not isinstance(scheduled_events, list):
        warnings.append(
            f"scheduled_events 应为列表，实际为 {type(scheduled_events).__name__}，已忽略"
        )
        return events_by_round, warnings

    out_of_range: Dict[int, int] = {}
    for event in scheduled_events:
        if not isinstance(event, dict):
            warnings.append(f"定时事件格式无效（应为对象），已跳过: {event!r}")
            continue
        round_num = _parse_round(event.get("round"))
        if round_num is None:
            warnings.append(f"定时事件轮次无效，已跳过: {event}")
            continue
        content = event.get("content")
        if not isinstance(content, str) or not content.strip():
            warnings.append(f"定时事件内容为空，已跳过: {event}")
            continue
        if round_num < 1 or round_num > total_rounds:
            out_of_range[round_num] = out_of_range.get(round_num, 0) + 1
            continue
        events_by_round.setdefault(round_num, []).append(event)

    if out_of_range:
        warnings.append(
            f"{sum(out_of_range.values())} 条定时事件的轮次超出实际模拟轮数 "
            f"(total_rounds={total_rounds})，将不会触发: {sorted(out_of_range)}"
        )

    return events_by_round, warnings


def build_post_actions(
    posts: List[Dict[str, Any]],
    get_agent: Callable[[Any], Any],
    make_action: Callable[[str], Any],
) -> Tuple[Dict[Any, Any], List[Tuple[Any, str]], List[str]]:
    """
    把帖子合并为一次 env.step() 的动作字典

    Args:
        posts: 帖子列表，每条包含 poster_agent_id 和 content
        get_agent: agent_id -> Agent（通常为 env.agent_graph.get_agent）
        make_action: content -> 动作对象（通常为 CREATE_POST 的 ManualAction）

    Returns:
        (actions, posted, warnings)
        - actions: Agent -> 动作；同一 Agent 有多条帖子时为列表（OASIS env.step 支持）
        - posted: 成功加入的 (agent_id, content)，按输入顺序
        - warnings: 无法解析 Agent 的帖子
    """
    actions: Dict[Any, Any] = {}
    posted: List[Tuple[Any, str]] = []
    warnings: List[str] = []

    for post in posts:
        agent_id = post.get("poster_agent_id", 0)
        content = post.get("content", "")
        try:
            agent = get_agent(agent_id)
        except Exception as e:
            warnings.append(f"无法为Agent {agent_id}创建定时事件帖子: {e}")
            continue

        action = make_action(content)
        if agent in actions:
            if not isinstance(actions[agent], list):
                actions[agent] = [actions[agent]]
            actions[agent].append(action)
        else:
            actions[agent] = action
        posted.append((agent_id, content))

    return actions, posted, warnings
