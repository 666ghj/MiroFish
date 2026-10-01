"""
模拟检查点（Checkpoint）

记录一次模拟运行已确认到达的轮次与动作水位线，使得运行该模拟的进程被
杀死/崩溃后，运维者和前端能够准确知道"跑到哪一轮了"，而不是面对一个
含糊的 FAILED 状态无从下手。

重要限制——这不是真正的"从检查点恢复执行"：
OASIS/camel-ai 目前把每个 Agent 的对话记忆（camel 的 ChatHistoryMemory）
完全保存在进程内存中（InMemoryKeyValueStorage），没有任何序列化/反序列化
能力；AgentGraph、OasisEnv 也都不暴露任何 save/load/state-dict 接口
（详见 backend/.venv 中 camel-oasis 包源码，整个包搜不到一处
checkpoint/resume/save_state/load_state）。因此一旦运行该模拟的子进程
被杀死，所有 Agent 的认知状态——它们在对话中已经"记住"、已经形成的
上下文——就永久丢失，无法从 round 31 真正接着跑下去，必须从 round 0
重新开始一次全新的模拟。

这个模块做的是诚实地记录"模拟到底跑到哪儿了"，而不是假装提供一个当前
架构做不到的"续跑"能力。真正的续跑需要 OASIS/camel-ai 自身先支持
Agent 记忆与环境状态的序列化。

另一个已知的架构性限制——单进程假设：SimulationRunner 把子进程句柄
（_processes）、监控线程（_monitor_threads）、IPC 队列等全部保存在
本进程的内存字典中，这些东西本来就无法跨进程共享。也就是说，即便在
多 worker 部署下共享同一份磁盘目录，也只有真正启动了某个模拟的那个
worker 进程能够停止/监控它——这是 SimulationRunner 整体架构自带的限制，
不是这个检查点功能引入的。因此这里没有专门为"另一个进程的内存缓存
读到过期的 run_state"这类场景做额外处理；要修好它需要重新设计
SimulationRunner 的进程模型（参见路线图中 P2 的 simulation_runner.py
拆分项），超出了本模块的范围。

第三个已知限制——轮内崩溃可能低报进度：_read_action_log 只在解析到
round_end 事件时才推进 twitter_current_round / reddit_current_round；
单条 action 记录只会计入 twitter_actions_count / reddit_actions_count，
不会单独把某个平台的"当前轮次"往前推。也就是说，如果进程恰好在第 N 轮
执行到一半（已经记录了这一轮的若干 action，但 round_end 还没写入）时
被杀死，检查点里该平台的轮次会停留在 N-1，即便动作日志已经证明它至少
进入过第 N 轮。这是 run_state.json 里 current_round 系列字段本身既有
的计量粒度（这些字段同时被 run-status API 等其他消费者使用，不是本次
新增的行为），要修需要改变 _read_action_log 更新这些字段的时机，属于
比检查点功能更大的改动，这里不做处理，只如实记录。
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from ..utils.logger import get_logger
from ..utils.state_machine import atomic_write_json

logger = get_logger('mirofish.checkpoint')

CHECKPOINT_FILENAME = "checkpoint.json"

RESUME_LIMITATION_NOTE = (
    "OASIS/camel-ai 中每个 Agent 的对话记忆仅保存在进程内存中，没有任何"
    "序列化能力，AgentGraph/OasisEnv 也不提供 save/load 接口。因此该检查点"
    "只能告诉你模拟运行到了哪一轮，不能被用来真正恢复执行——"
    "必须从 round 0 重新开始一次全新的模拟。"
)


@dataclass
class Checkpoint:
    simulation_id: str
    twitter_round: int = 0
    reddit_round: int = 0
    total_rounds: int = 0
    twitter_action_count: int = 0
    reddit_action_count: int = 0
    runner_status: str = "unknown"
    checkpointed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # 目前恒为 False：详见模块docstring。字段保留是为了让 API/UI 不需要
    # 靠字符串匹配 resume_limitation 就能判断"这份检查点能不能用来续跑"，
    # 以及为将来 OASIS 若支持状态序列化时的扩展留出位置。
    resumable: bool = False
    resume_limitation: str = RESUME_LIMITATION_NOTE

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def checkpoint_path(sim_dir: str) -> str:
    return os.path.join(sim_dir, CHECKPOINT_FILENAME)


def save_checkpoint(sim_dir: str, checkpoint: Checkpoint) -> None:
    """原子性地将检查点写入该模拟目录。"""
    atomic_write_json(checkpoint_path(sim_dir), checkpoint.to_dict())


def load_checkpoint(sim_dir: str) -> Optional[Dict[str, Any]]:
    """读取该模拟目录下已持久化的检查点；不存在则返回 None。"""
    path = checkpoint_path(sim_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.exception(f"读取检查点失败: {path}")
        return None


def build_checkpoint_from_state(state) -> Checkpoint:
    """
    从 SimulationRunState 构建一份检查点快照。

    checkpointed_at 使用 state.updated_at，而不是构建时的当前时间：
    updated_at 只在 SimulationRunState.add_action() 里被更新——也就是
    真正观察到新动作/轮次推进时——而不是每次保存或每次被轮询时都刷新。
    这样 API 消费者才能用这个时间戳判断"模拟上一次真正取得进展是什么时候"，
    而不是每次请求都看到一个变化的时间戳、误以为模拟仍在推进。
    """
    return Checkpoint(
        simulation_id=state.simulation_id,
        twitter_round=state.twitter_current_round,
        reddit_round=state.reddit_current_round,
        total_rounds=state.total_rounds,
        twitter_action_count=state.twitter_actions_count,
        reddit_action_count=state.reddit_actions_count,
        runner_status=state.runner_status.value,
        checkpointed_at=state.updated_at,
    )
