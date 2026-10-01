"""
历史回测（Historical Backtesting）框架

一次"有趣的模拟"和一套"经过验证的预测方法"之间的区别，在于后者被拿去跟
真实发生过的历史结果做过量化比较。这个模块把"T0 时刻能拿到的信息 -> 跑
MiroFish -> 模拟结果（预测）-> T1 时刻真实发生的结果 -> 比较"这条流程落到
具体的存储与打分逻辑上。

MiroFish 在这里的角色定位——记账与打分基础设施，不是自动化的预测引擎：

1. "预测"由调用方显式提交，而不是本模块从模拟日志里自动抽取/解读。
   自动从叙事性的模拟报告或动作日志里推断"这次模拟预测了什么"是一个
   本质上主观、容易出错的自然语言理解问题，超出了这个模块的职责范围；
   人类（或上层调用方）看过已完成的模拟/集成结果后，把结论提炼成
   结构化的 Prediction 提交进来，MiroFish 只负责把这份提交与它引用的
   来源模拟/集成绑定、加时间戳、之后锁定。

2. 防止"未来信息泄漏进 T0 预测"这件事，本模块只能做结构上能做到的部分：
   create_backtest（登记场景 + 预测）与 record_ground_truth（登记真实
   结果）被拆成两个必须按顺序调用的独立接口——不存在任何一次调用能同时
   提交预测和真实结果，也不可能在 backtest case 创建之前就登记真实结果
   （因为这时 backtest_id 还不存在）。这确保了"预测"这份记录，在时间戳
   意义上，一定早于"真实结果"这份记录。
   但这没法验证一个更深层的问题：模拟本身的输入（graph/profiles/config）
   是否真的只包含 T0 时刻已知的信息，而不是调用方自己就已经知道 T1
   结果、然后倒着构造了一个"看起来很准"的输入。这一点完全依赖于场景
   策划者的诚实——如实标注 t0_cutoff 只是一个供人核对的说明字段，不是
   一个技术上被强制执行的约束。

   还有一个相关但更技术性的问题：source_simulation_id 是可以被原地
   重跑复用的（/api/simulation/start 允许对同一个 simulation_id 重新
   跑一遍，run_state 会被替换）；集成本身的 ensemble_id 虽然不会被
   重跑，但它的每一个成员在 SimulationRunner 眼里就是一次普普通通、
   同样可以被原地重启的模拟，ensemble_id/created_at 本身侦测不到某个
   成员被重跑过。如果一个 backtest 创建之后，它引用的来源（或某个
   集成成员）后来被重跑了，这份被锁定的 prediction 名义上还挂在同一个
   id 下，但实际支撑它的那次运行已经不是原来那次了——审计链断了。
   本模块不会、也做不到冻结一份完整的输入快照（那需要连人设/配置/
   动作日志一起拷贝，超出这个模块的范围），只在创建时记录一个可验证
   的快照（source_run_snapshot_at）：单次模拟是那次运行的
   run_state.started_at；集成是把每个已成功完成的成员各自的
   started_at 拼成的一份复合指纹——只要任何一个成员后来被重启过，它的
   started_at 就会变，指纹也就对不上了。这两种情况都特意绕开了
   SimulationRunner.get_run_state 的进程内缓存（force_reload=True，
   见下面第6条），否则这份"快照"本身就可能基于一份过期的缓存数据。
   日后可以拿这个字段跟来源当前的实际状态重新核对，一旦对不上就说明
   "这个来源已经不是当初那一次了"，需要人工核实。

3. 来源必须是一次已经跑到终态并且成功完成的单次模拟（SimulationRunner，
   platform 不限）或一次集成（EnsembleRunner，见 TASK 8），预测的
   probability/distribution 字段（用于 Brier/校准误差/分布距离）通常是
   从对应集成的 outcome_frequency 聚合里读出来的（重复运行的比例），单次
   模拟只能给出确定性的 occurred/direction/sentiment，没有天然的概率——
   如果调用方硬要为单次模拟提交 probability，本模块不会阻止（这属于
   调用方自己的建模选择），但也不会替它编造一个。

4. 六个指标里，direction accuracy / event occurrence / sentiment
   direction / distribution distance 是"单个 case 内部"就能算的——一旦
   record_ground_truth 提交，立刻算出来存在这个 case 自己的 metrics 里。
   rank correlation 和 calibration error 天生是"一批 case 放在一起才有
   意义"的统计量（"这次预测的相对排名对不对"、"这一批打了 70% 置信度
   的预测里真的有 70% 发生了吗"），所以由 get_suite_summary 在查询时对
   一批已打分的 case 现算，而不是存在单个 case 上。

5. 与 EnsembleRunner/SimulationRunner 保持一致的"目录即存储"风格：每个
   backtest case 在 uploads/backtests/<backtest_id>/backtest.json 下保存
   一份记录。record_ground_truth 之后这份记录被视为不可再变——重新提交
   真实结果会被拒绝，而不是静默覆盖（防止"看到打分不满意就悄悄改真实
   结果重新打分"）。这份不可变性通过一个独占创建的声明文件
   （O_CREAT|O_EXCL）实现，而不是进程内的 threading.Lock——后者在多
   worker/多容器共享同一个 uploads 目录的部署下毫无用处（见
   record_ground_truth 自己的 docstring）。

6. create_backtest 判断来源"是否已成功完成"、以及为来源生成
   source_run_snapshot_at 快照时，都会对 SimulationRunner.get_run_state
   传 force_reload=True，跳过它默认优先使用的进程内缓存。原因见第2条：
   这两个决定一旦做出就不可撤销（写进一份被当作证据锁定的记录），不能
   信任一份可能已经过期、由本进程碰巧缓存下来的状态——多 worker 部署下，
   另一个进程完全可能已经把这个来源重新启动过。
"""

import json
import math
import os
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logger import get_logger
from ..utils.id_validation import validate_backtest_id, safe_join
from ..utils.state_machine import atomic_write_json
from .simulation_manager import SimulationManager, SimulationStatus
from .simulation_runner import SimulationRunner, RunnerStatus
from .ensemble_runner import EnsembleRunner

logger = get_logger('mirofish.backtest')

BACKTEST_FILENAME = "backtest.json"

# Prediction/GroundTruth 里被认可的分类型字段，用来判断"两者之间是否至少
# 共享一个可打分的维度"；rank 不在这里——它只贡献给套件级别的排名相关性，
# 不产生单 case 指标，所以单独校验。
_COMPARABLE_SCALAR_FIELDS = ("occurred", "direction", "sentiment")

# Prediction.from_dict/GroundTruth.from_dict 对不认识的键（比如拼错的
# "direciton"）不会报错——dataclass 的 from_dict 只是 .get(...) 对应字段，
# 多余的键会被直接忽略。如果不在这里显式拒绝，一次提交里的拼写错误会
# 悄悄地让某个字段永远是 None（未被识别），而不是报错——对 prediction
# 这只是发现得晚；对 ground_truth 则是永久性的，因为它一次性、不可变，
# 提交之后没有第二次机会去补救这个被吞掉的字段。
_PREDICTION_ALLOWED_FIELDS = frozenset(
    {"occurred", "probability", "direction", "sentiment", "rank", "distribution"}
)
_GROUND_TRUTH_ALLOWED_FIELDS = frozenset(
    {"occurred", "direction", "sentiment", "rank", "distribution"}
)


@dataclass
class Prediction:
    """
    调用方在场景已经跑完之后、真实结果公开之前提交的结构化预测。
    所有字段都是可选的——具体填哪些取决于这个场景本来就是在预测什么。
    """
    occurred: Optional[bool] = None
    probability: Optional[float] = None  # 预测事件发生的概率，用于 Brier/校准误差，取值 [0, 1]
    direction: Optional[str] = None      # 例如 "up"/"down"/"flat"；比较时忽略大小写与首尾空白
    sentiment: Optional[str] = None      # 例如 "positive"/"negative"/"neutral"；同上
    rank: Optional[float] = None         # 用于套件级别排名相关性的分数/排名
    distribution: Optional[Dict[str, float]] = None  # 标签 -> 预测占比

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Prediction":
        return cls(
            occurred=data.get("occurred"),
            probability=data.get("probability"),
            direction=data.get("direction"),
            sentiment=data.get("sentiment"),
            rank=data.get("rank"),
            distribution=data.get("distribution"),
        )


@dataclass
class GroundTruth:
    """T1 时刻真实发生的结果，字段含义与 Prediction 一一对应（除了 probability——
    真实结果不存在"概率"，一件事只会发生或不发生）。"""
    occurred: Optional[bool] = None
    direction: Optional[str] = None
    sentiment: Optional[str] = None
    rank: Optional[float] = None
    distribution: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GroundTruth":
        return cls(
            occurred=data.get("occurred"),
            direction=data.get("direction"),
            sentiment=data.get("sentiment"),
            rank=data.get("rank"),
            distribution=data.get("distribution"),
        )


@dataclass
class BacktestCase:
    backtest_id: str
    project_id: str
    source_simulation_id: Optional[str]
    source_ensemble_id: Optional[str]
    scenario_description: str
    t0_cutoff: str
    prediction: Prediction
    created_at: str
    ground_truth: Optional[GroundTruth] = None
    ground_truth_recorded_at: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    owner_id: Optional[str] = None
    # 来源在创建这个 case 时的一个可验证快照时间戳——单次模拟用它的
    # run_state.started_at，集成用它的 created_at（集成永远不会被"重启"，
    # 一次新的集成运行总会拿到一个全新的 ensemble_id，只有模拟可以在原地
    # 重跑）。不是一份完整的输入快照（那需要连人设/配置/动作日志一起
    # 拷一份，超出本模块范围），只是让日后审计时能够核对："我现在看到的
    # source_simulation_id 对应的最新一次运行，是不是就是这份预测当初
    # 依据的那一次？" ——如果两者的时间戳对不上，说明这个来源后来被重跑
    # 过，这份预测的可信来源已经变了，需要人工核实。
    source_run_snapshot_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backtest_id": self.backtest_id,
            "project_id": self.project_id,
            "source_simulation_id": self.source_simulation_id,
            "source_ensemble_id": self.source_ensemble_id,
            "scenario_description": self.scenario_description,
            "t0_cutoff": self.t0_cutoff,
            "prediction": self.prediction.to_dict(),
            "created_at": self.created_at,
            "ground_truth": self.ground_truth.to_dict() if self.ground_truth else None,
            "ground_truth_recorded_at": self.ground_truth_recorded_at,
            "metrics": self.metrics,
            "owner_id": self.owner_id,
            "source_run_snapshot_at": self.source_run_snapshot_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BacktestCase":
        ground_truth_data = data.get("ground_truth")
        return cls(
            backtest_id=data["backtest_id"],
            project_id=data.get("project_id", ""),
            source_simulation_id=data.get("source_simulation_id"),
            source_ensemble_id=data.get("source_ensemble_id"),
            scenario_description=data.get("scenario_description", ""),
            t0_cutoff=data.get("t0_cutoff", ""),
            prediction=Prediction.from_dict(data.get("prediction", {})),
            created_at=data.get("created_at", datetime.now().isoformat()),
            ground_truth=GroundTruth.from_dict(ground_truth_data) if ground_truth_data else None,
            ground_truth_recorded_at=data.get("ground_truth_recorded_at"),
            metrics=data.get("metrics"),
            owner_id=data.get("owner_id"),
            source_run_snapshot_at=data.get("source_run_snapshot_at"),
        )


def _normalize_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip().lower()


def _is_finite_number(value: Any) -> bool:
    """
    math.isfinite() 对超大 Python int（比如一个 ~309 位的整数）会在内部转换
    成 float 时抛 OverflowError，而不是像对 float 输入那样干净地返回
    False——所有校验路径都统一走这个包装，把"转换失败"也当作"不是一个
    有限数字"来拒绝，而不是让 500 泄漏出去。
    """
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _normalize_distribution(distribution: Dict[str, float]) -> Dict[str, float]:
    total = sum(distribution.values())
    # 即使每个值单独都是有限数字，加起来仍然可能溢出成 inf（例如两个
    # 1e308 相加）；不检查的话，除出来的"归一化"分布会退化成一堆 0，
    # 让后续的分布距离计算给出一个看似合理但完全错误的数字，而不是
    # 报错。
    if not _is_finite_number(total) or total <= 0:
        raise ValueError(
            "distribution values must be non-negative finite numbers summing to "
            "a positive finite total"
        )
    return {label: value / total for label, value in distribution.items()}


def _total_variation_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    norm_a = _normalize_distribution(a)
    norm_b = _normalize_distribution(b)
    keys = set(norm_a) | set(norm_b)
    return 0.5 * sum(abs(norm_a.get(k, 0.0) - norm_b.get(k, 0.0)) for k in keys)


def _rank_values(values: List[float]) -> List[float]:
    """按升序给出平均名次（并列取平均），用于 Spearman 排名相关性。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman_rank_correlation(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    rx = _rank_values(xs)
    ry = _rank_values(ys)
    mean_rx = statistics.mean(rx)
    mean_ry = statistics.mean(ry)
    covariance = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    variance_x = sum((a - mean_rx) ** 2 for a in rx)
    variance_y = sum((b - mean_ry) ** 2 for b in ry)
    if variance_x == 0 or variance_y == 0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


class BacktestRunner:
    """历史回测的编排入口：登记预测 -> 登记真实结果（打分） -> 查询套件级聚合。"""

    BACKTEST_DATA_DIR = os.path.join(
        os.path.dirname(__file__),
        '../../uploads/backtests'
    )

    @classmethod
    def _get_backtest_dir(cls, backtest_id: str) -> str:
        validate_backtest_id(backtest_id)
        return safe_join(cls.BACKTEST_DATA_DIR, backtest_id)

    @classmethod
    def _backtest_path(cls, backtest_id: str) -> str:
        return os.path.join(cls._get_backtest_dir(backtest_id), BACKTEST_FILENAME)

    @classmethod
    def get_backtest(cls, backtest_id: str) -> Optional[BacktestCase]:
        path = cls._backtest_path(backtest_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return BacktestCase.from_dict(json.load(f))
        except Exception:
            logger.exception(f"读取回测记录失败: backtest_id={backtest_id}")
            return None

    @classmethod
    def list_backtests(cls, project_id: Optional[str] = None) -> List[BacktestCase]:
        cases: List[BacktestCase] = []
        if not os.path.exists(cls.BACKTEST_DATA_DIR):
            return cases
        for backtest_id in os.listdir(cls.BACKTEST_DATA_DIR):
            if backtest_id.startswith('.'):
                continue
            try:
                case = cls.get_backtest(backtest_id)
            except Exception:
                continue
            if case is None:
                continue
            if project_id is None or case.project_id == project_id:
                cases.append(case)
        cases.sort(key=lambda c: c.created_at, reverse=True)
        return cases

    # ────────────────────────── 登记预测 ──────────────────────────

    @classmethod
    def create_backtest(
        cls,
        scenario_description: str,
        t0_cutoff: str,
        prediction: Dict[str, Any],
        source_simulation_id: Optional[str] = None,
        source_ensemble_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> BacktestCase:
        """
        登记一次回测场景：绑定一个已成功完成的来源（单次模拟或集成）与一份
        结构化预测。此接口不接受任何"真实结果"字段——真实结果只能在这个
        case 创建之后，通过 record_ground_truth 单独登记。

        Args:
            scenario_description: 这次场景在预测什么，人类可读的说明。
            t0_cutoff: "预测所依据的信息截止到什么时候"的说明性时间点
                （不是技术强制约束，见模块文档第2条）。
            prediction: 结构化预测，字段见 Prediction。
            source_simulation_id: 提供预测依据的单次模拟 ID（与
                source_ensemble_id 二者恰好提供一个）。
            source_ensemble_id: 提供预测依据的集成 ID。
            owner_id: 这个新建 backtest 的所有者——调用方（API 层）传入当前
                已认证用户的 id，而不是从来源模拟/集成的 owner_id 继承。
                这两者不一定相同：如果来源是一个在启用认证之前创建的"无主"
                历史资源（owner_id=None），任何已认证用户都可以读它，但由
                它派生出的这个 backtest 必须归属于真正发起这次登记的人——
                否则它会继承来源的"无主"状态，变成任何认证用户都能读取、
                甚至提交一次性真实结果的公共资源。project_id 不受此影响，
                仍然从来源继承，因为它只是描述性的归类信息，不是访问控制。
        """
        # 只把字面上的空字符串当作"没提供"再归一化成 None，而不是用
        # `x or None`——后者会把任何 falsy 值（0、False、[] 这类明显不是
        # 合法 id、本该被下面的身份校验拒绝的畸形输入）也一并抹成 None。
        if source_simulation_id == "":
            source_simulation_id = None
        if source_ensemble_id == "":
            source_ensemble_id = None
        # 互斥校验和下面的分支选择必须用同一套"是否提供"的判定标准——都是
        # `is not None`，而不是 bool(...)。否则像 0/False/[] 这类
        # is-not-None 为真但 bool(...) 为假的畸形取值，会在这里被误判为
        # "没提供"从而放行一个实际上传了两个来源的请求，下面的分支却又
        # 按 `is not None` 把它当成"提供了"走进对应分支，两处判断不一致。
        if (source_simulation_id is not None) == (source_ensemble_id is not None):
            raise ValueError(
                "必须且只能提供 source_simulation_id 或 source_ensemble_id 中的一个"
            )
        if not isinstance(scenario_description, str) or not scenario_description.strip():
            raise ValueError("scenario_description 不能为空")
        if not isinstance(t0_cutoff, str) or not t0_cutoff.strip():
            raise ValueError("t0_cutoff 不能为空")

        parsed_prediction = cls._parse_prediction(prediction)

        if source_simulation_id is not None:
            manager = SimulationManager()
            # SimulationManager 没有内存缓存，每次都直接读盘，不需要
            # force_reload 这类机制。
            state = manager.get_simulation(source_simulation_id)
            if state is None:
                raise ValueError(f"来源模拟不存在: {source_simulation_id}")
            # /api/simulation/prepare 支持 force_regenerate=True，可以对一个
            # 已经 COMPLETED 的模拟原地重新生成人设/配置——这会把
            # SimulationState.status 改成 PREPARING/READY，但完全不会去碰
            # SimulationRunner 自己的 run_state.json（那是另一个文件，由
            # 另一个模块管理），所以仅凭 run_state.runner_status ==
            # COMPLETED 侦测不到"这次预测依据的输入（人设/配置）已经被
            # 重新生成过、不再是原来那一次运行真正用过的输入"这种情况。
            # state.status 才是"这个模拟当前处于什么阶段"的权威来源；
            # 只有它也确认是 COMPLETED（而不是重新准备后又停在
            # PREPARING/READY，还没被重新 START）时，才信任 run_state.json
            # 里的那份历史 COMPLETED 快照。
            if state.status != SimulationStatus.COMPLETED:
                raise ValueError(
                    f"来源模拟尚未成功完成，无法作为回测预测依据: {source_simulation_id}"
                )
            # force_reload=True：这是一次要把结果永久锁定成回测证据的
            # 资格判断，不能信任本进程可能过期的内存缓存——在多 worker
            # 部署下，另一个进程完全可能已经把这个 simulation_id 重新
            # 启动了，磁盘上早已不是 COMPLETED。
            run_state = SimulationRunner.get_run_state(source_simulation_id, force_reload=True)
            if run_state is None or run_state.runner_status != RunnerStatus.COMPLETED:
                raise ValueError(
                    f"来源模拟尚未成功完成，无法作为回测预测依据: {source_simulation_id}"
                )
            project_id = state.project_id
            # simulation_id 是可以被原地重跑复用的（同一个 id，新的
            # run_state），不像 ensemble_id 那样每次都是全新的——记下这次
            # 用作预测依据的这一次运行的 started_at，供日后审计比对。
            source_run_snapshot_at = run_state.started_at
        else:
            record = EnsembleRunner.get_ensemble_record(source_ensemble_id)
            if record is None:
                raise ValueError(f"来源集成不存在: {source_ensemble_id}")
            project_id = record.project_id
            # 特意不先用 get_ensemble_summary() 的（默认缓存路径）状态做
            # 提前退出：那样看似是个廉价优化，实际上会引入相反方向的假
            # 阴性——如果这个进程恰好缓存了某个成员较早的 RUNNING 状态，
            # 而它其实已经在另一个 worker 上真正跑完了，summary 会一直
            # 报"running"，导致一个货真价实已完成的集成被永久拒绝，永远
            # 走不到下面这段真正准确的复核。是否"能被这份回测锁定"完全
            # 由下面这个循环（每个成员都 force_reload=True）说了算。
            #
            # EnsembleRecord.created_at 本身也不足以证明"这份聚合背后的
            # 每个成员运行都还是当初那一次"——集成的每个成员本质上就是
            # 一次普通的、可以被 /api/simulation/start 原地重启的模拟，
            # ensemble_id/created_at 完全侦测不到某个成员被重跑过；所以
            # 这里对每个成员单独 force_reload、只把确实仍处于 COMPLETED
            # 的那些计入"已完成成员"集合，拼成 source_run_snapshot_at 的
            # 复合指纹——任何成员如果 force_reload 后不再是 COMPLETED
            # （无论是仍在跑、还是被重启后又在跑），都不能被当作这份预测
            # 的可信依据，必须整体拒绝，而不是悄悄把它排除在指纹之外。
            #
            # 三类成员会被正常跳过、不参与判定：
            # - member.start_error is not None：启动阶段就失败了。
            # - FAILED/STOPPED：本来就不参与 EnsembleRunner 的聚合统计
            #   （见 TASK 8 的 _compute_aggregate），状态变化与这份预测
            #   的可信度无关。
            # - record.cancelled 为真、且这个成员从未真正启动过（没有
            #   start_error，也没有 run_state）：这是 TASK 8 里"启动循环
            #   崩溃后被取消"的占位成员——get_ensemble_summary() 会把它
            #   归类为已取消的终态失败，而不是"未知"；这里必须用同样的
            #   逻辑对待它，否则一个 summary 认为完全可以打分的集成会在
            #   这里被误判为"缺状态、需要拒绝"。
            manager = SimulationManager()
            member_snapshots = []
            for member in record.members:
                if member.start_error is not None:
                    continue
                member_run_state = SimulationRunner.get_run_state(
                    member.simulation_id, force_reload=True
                )
                if member_run_state is None:
                    if record.cancelled:
                        continue
                    raise ValueError(
                        f"来源集成尚未成功完成，无法作为回测预测依据: {source_ensemble_id}"
                    )
                if member_run_state.runner_status in (
                    RunnerStatus.FAILED, RunnerStatus.STOPPED
                ):
                    continue
                # 与单次模拟来源同样的道理：成员本质上就是一个普通的
                # SimulationState，同样可以被 /api/simulation/prepare
                # (force_regenerate=True) 原地重新生成人设/配置而不清空
                # 它的 run_state.json。
                member_state = manager.get_simulation(member.simulation_id)
                if member_state is None or member_state.status != SimulationStatus.COMPLETED:
                    raise ValueError(
                        f"来源集成尚未成功完成，无法作为回测预测依据: {source_ensemble_id}"
                        f"（成员 {member.simulation_id} 的输入可能已被重新生成）"
                    )
                if member_run_state.runner_status != RunnerStatus.COMPLETED:
                    raise ValueError(
                        f"来源集成尚未成功完成，无法作为回测预测依据: {source_ensemble_id}"
                        f"（成员 {member.simulation_id} 当前不处于已完成状态，"
                        f"可能已被重新启动）"
                    )
                member_snapshots.append(
                    f"{member.simulation_id}:{member_run_state.started_at}"
                )
            if not member_snapshots:
                raise ValueError(
                    f"来源集成尚未成功完成，无法作为回测预测依据: {source_ensemble_id}"
                )
            source_run_snapshot_at = "|".join(sorted(member_snapshots))

        backtest_id = f"bt_{uuid.uuid4().hex[:12]}"
        case = BacktestCase(
            backtest_id=backtest_id,
            project_id=project_id,
            source_simulation_id=source_simulation_id,
            source_ensemble_id=source_ensemble_id,
            scenario_description=scenario_description,
            t0_cutoff=t0_cutoff,
            prediction=parsed_prediction,
            created_at=datetime.now().isoformat(),
            owner_id=owner_id,
            source_run_snapshot_at=source_run_snapshot_at,
        )
        backtest_dir = cls._get_backtest_dir(backtest_id)
        os.makedirs(backtest_dir, exist_ok=True)
        atomic_write_json(cls._backtest_path(backtest_id), case.to_dict())
        return case

    # ────────────────────────── 登记真实结果 + 打分 ──────────────────────────

    @classmethod
    def record_ground_truth(
        cls, backtest_id: str, ground_truth: Dict[str, Any]
    ) -> BacktestCase:
        """
        登记这个场景真实发生的结果，并立刻计算该 case 自己的指标。

        一旦登记过一次，这个 case 就被视为已打分、不可变——重复调用会被
        拒绝，而不是覆盖之前的真实结果（防止"看到分数不满意就悄悄改真实
        结果重新打分"）。

        这个"一次性"保证用一个独占创建的声明文件（O_CREAT|O_EXCL）来
        实现，而不是 threading.Lock：Lock 只在单个 Python 进程内有效——
        一旦部署到多进程/多容器（例如 gunicorn --workers > 1）、共享同一个
        uploads 目录，各个进程各自持有自己的锁字典，互相之间毫无阻挡，
        两个几乎同时到达不同进程的请求依然能都读到 ground_truth is None、
        都"成功"，后一次悄悄覆盖前一次本该不可变的结果。而 O_CREAT|O_EXCL
        创建同一个路径，在同一台机器的多个进程之间也是操作系统保证的原子
        操作——谁先创建成功，谁就独占了"登记真实结果"这个一次性操作，
        不依赖任何进程内数据结构。

        校验（_parse_ground_truth/_ensure_scorable）被安排在声明这个独占
        权之前完成：这样一次因为输入格式错误而失败的请求不会白白消耗掉
        这个一次性声明——调用方修正输入后应该还能重试。一旦声明成功，
        后续任何失败（包括落盘失败）都不会释放这个声明——宁可让这个 case
        卡在一个需要人工介入的状态，也不要重新打开一个可能导致重复登记
        的竞争窗口。
        """
        case = cls.get_backtest(backtest_id)
        if case is None:
            raise ValueError(f"回测不存在: {backtest_id}")
        if case.ground_truth is not None:
            raise ValueError(f"该回测已经登记过真实结果，不能重复登记: {backtest_id}")

        parsed_ground_truth = cls._parse_ground_truth(ground_truth)
        cls._ensure_scorable(case.prediction, parsed_ground_truth)

        claim_path = cls._ground_truth_claim_path(backtest_id)
        try:
            claim_fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(claim_fd)
        except FileExistsError:
            raise ValueError(f"该回测已经登记过真实结果，不能重复登记: {backtest_id}")

        # 拿到声明之后重新读一次最新状态——防御性检查：理论上声明已经
        # 保证了独占，这里不应该再看到 ground_truth 已存在，但如果真的
        # 出现（比如声明文件是上一次崩溃在写入 backtest.json 之前留下的
        # 残留），情愿诚实报错，也不要在没有真实数据支撑的情况下继续。
        case = cls.get_backtest(backtest_id)
        if case is None or case.ground_truth is not None:
            raise ValueError(f"该回测已经登记过真实结果，不能重复登记: {backtest_id}")

        case.ground_truth = parsed_ground_truth
        case.ground_truth_recorded_at = datetime.now().isoformat()
        case.metrics = cls._score_case(case.prediction, parsed_ground_truth)

        atomic_write_json(cls._backtest_path(backtest_id), case.to_dict())
        return case

    @classmethod
    def _ground_truth_claim_path(cls, backtest_id: str) -> str:
        return os.path.join(cls._get_backtest_dir(backtest_id), "ground_truth.claim")

    @staticmethod
    def _ensure_scorable(prediction: Prediction, ground_truth: GroundTruth) -> None:
        has_scalar_overlap = any(
            getattr(prediction, field_name) is not None
            and getattr(ground_truth, field_name) is not None
            for field_name in _COMPARABLE_SCALAR_FIELDS
        )
        has_distribution_overlap = (
            prediction.distribution is not None and ground_truth.distribution is not None
        )
        has_rank_overlap = prediction.rank is not None and ground_truth.rank is not None
        # probability 本身不在 _COMPARABLE_SCALAR_FIELDS 里（它不是一个跟
        # ground_truth 同名字段做相等比较的量），但 probability + 真实的
        # occurred 恰好就是 Brier score 需要的那对数据——一份只提交了
        # probability、没有提交 occurred 的合法概率预测，不能因为它没有
        # 命中 _COMPARABLE_SCALAR_FIELDS 就被判定为"不可打分"。
        has_probability_overlap = (
            prediction.probability is not None and ground_truth.occurred is not None
        )
        if not (
            has_scalar_overlap
            or has_distribution_overlap
            or has_rank_overlap
            or has_probability_overlap
        ):
            raise ValueError(
                "ground_truth 与该回测登记的 prediction 没有任何可比较的共同字段"
            )

    @staticmethod
    def _score_case(prediction: Prediction, ground_truth: GroundTruth) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}

        if prediction.occurred is not None and ground_truth.occurred is not None:
            metrics["event_occurrence_correct"] = (
                prediction.occurred == ground_truth.occurred
            )

        # Brier score 只需要 probability + 真实的 occurred，独立于
        # prediction 是否也提交了确定性的 occurred 字段——一份"我认为有
        # 70% 概率会发生"的预测，即使没有额外给出一个二元判断，也应该能
        # 被打分。
        if prediction.probability is not None and ground_truth.occurred is not None:
            actual = 1.0 if ground_truth.occurred else 0.0
            metrics["brier_score"] = (prediction.probability - actual) ** 2

        if prediction.direction is not None and ground_truth.direction is not None:
            metrics["direction_correct"] = (
                _normalize_label(prediction.direction) == _normalize_label(ground_truth.direction)
            )

        if prediction.sentiment is not None and ground_truth.sentiment is not None:
            metrics["sentiment_correct"] = (
                _normalize_label(prediction.sentiment) == _normalize_label(ground_truth.sentiment)
            )

        if prediction.distribution is not None and ground_truth.distribution is not None:
            metrics["distribution_distance"] = _total_variation_distance(
                prediction.distribution, ground_truth.distribution
            )

        return metrics

    @staticmethod
    def _reject_unknown_fields(data: Dict[str, Any], allowed: frozenset, label: str) -> None:
        unknown = set(data.keys()) - allowed
        if unknown:
            raise ValueError(
                f"{label} 包含无法识别的字段: {sorted(unknown)}（可能是拼写错误；"
                f"支持的字段为: {sorted(allowed)}）"
            )

    @classmethod
    def _parse_prediction(cls, data: Dict[str, Any]) -> Prediction:
        if not isinstance(data, dict):
            raise ValueError("prediction 必须是一个 JSON 对象")
        cls._reject_unknown_fields(data, _PREDICTION_ALLOWED_FIELDS, "prediction")
        prediction = Prediction.from_dict(data)
        cls._validate_scalar_fields(prediction.occurred, prediction.direction, prediction.sentiment)
        if prediction.probability is not None:
            if not isinstance(prediction.probability, (int, float)) or isinstance(
                prediction.probability, bool
            ) or not _is_finite_number(prediction.probability):
                raise ValueError("prediction.probability 必须是数字")
            if not (0.0 <= prediction.probability <= 1.0):
                raise ValueError("prediction.probability 必须在 0 到 1 之间")
        if prediction.rank is not None and (
            not isinstance(prediction.rank, (int, float))
            or isinstance(prediction.rank, bool)
            or not _is_finite_number(prediction.rank)
        ):
            raise ValueError("prediction.rank 必须是有限数字")
        if prediction.distribution is not None:
            cls._validate_distribution(prediction.distribution)
        if not cls._has_any_field(prediction):
            raise ValueError("prediction 必须至少提供一个字段")
        return prediction

    @classmethod
    def _parse_ground_truth(cls, data: Dict[str, Any]) -> GroundTruth:
        if not isinstance(data, dict):
            raise ValueError("ground_truth 必须是一个 JSON 对象")
        cls._reject_unknown_fields(data, _GROUND_TRUTH_ALLOWED_FIELDS, "ground_truth")
        ground_truth = GroundTruth.from_dict(data)
        cls._validate_scalar_fields(
            ground_truth.occurred, ground_truth.direction, ground_truth.sentiment
        )
        if ground_truth.rank is not None and (
            not isinstance(ground_truth.rank, (int, float))
            or isinstance(ground_truth.rank, bool)
            or not _is_finite_number(ground_truth.rank)
        ):
            raise ValueError("ground_truth.rank 必须是有限数字")
        if ground_truth.distribution is not None:
            cls._validate_distribution(ground_truth.distribution)
        if not cls._has_any_field(ground_truth):
            raise ValueError("ground_truth 必须至少提供一个字段")
        return ground_truth

    @staticmethod
    def _validate_scalar_fields(occurred, direction, sentiment) -> None:
        if occurred is not None and not isinstance(occurred, bool):
            raise ValueError("occurred 必须是布尔值")
        if direction is not None:
            if not isinstance(direction, str):
                raise ValueError("direction 必须是字符串")
            if not direction.strip():
                raise ValueError("direction 不能是空字符串")
        if sentiment is not None:
            if not isinstance(sentiment, str):
                raise ValueError("sentiment 必须是字符串")
            if not sentiment.strip():
                raise ValueError("sentiment 不能是空字符串")

    @staticmethod
    def _validate_distribution(distribution: Any) -> None:
        if not isinstance(distribution, dict) or not distribution:
            raise ValueError("distribution 必须是非空的 {标签: 数值} 对象")
        for label, value in distribution.items():
            if not isinstance(label, str):
                raise ValueError("distribution 的键必须是字符串")
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not _is_finite_number(value)
                or value < 0
            ):
                raise ValueError("distribution 的值必须是非负的有限数字")
        # 每个值单独有限，加起来仍然可能溢出成 inf（例如两个 1e308 相加）；
        # 不检查的话，_normalize_distribution 会在真正打分时才发现总和不是
        # 有限数字。这里在入库前就拒绝，报错更及时。
        total = sum(distribution.values())
        if not _is_finite_number(total) or total <= 0:
            raise ValueError("distribution 的值之和必须是大于 0 的有限数字")

    @staticmethod
    def _has_any_field(obj) -> bool:
        return any(v is not None for v in asdict(obj).values())

    # ────────────────────────── 套件级聚合 ──────────────────────────

    @classmethod
    def get_suite_summary(cls, project_id: Optional[str] = None) -> Dict[str, Any]:
        """按 project_id（可选）过滤后现算套件级别聚合指标的便捷入口。多用户
        部署下，调用方（API 层）需要按调用者的所有权先过滤 case 列表，再改用
        summarize_cases——直接用这个方法会聚合所有用户的 case。"""
        return cls.summarize_cases(cls.list_backtests(project_id))

    @classmethod
    def summarize_cases(cls, cases: List[BacktestCase]) -> Dict[str, Any]:
        """
        对给定的一批回测 case 现算套件级别的聚合指标：rank correlation、
        calibration error（expected calibration error），以及各单 case
        指标的整体准确率/均值，作为便于人工核对的补充。只使用已登记过真实
        结果（已打分）的 case，未打分的会被忽略。
        """
        cases = [c for c in cases if c.ground_truth is not None]

        direction_hits = [c.metrics.get("direction_correct") for c in cases if c.metrics and c.metrics.get("direction_correct") is not None]
        sentiment_hits = [c.metrics.get("sentiment_correct") for c in cases if c.metrics and c.metrics.get("sentiment_correct") is not None]
        occurrence_hits = [c.metrics.get("event_occurrence_correct") for c in cases if c.metrics and c.metrics.get("event_occurrence_correct") is not None]
        distances = [c.metrics.get("distribution_distance") for c in cases if c.metrics and c.metrics.get("distribution_distance") is not None]
        brier_scores = [c.metrics.get("brier_score") for c in cases if c.metrics and c.metrics.get("brier_score") is not None]

        calibration = cls._compute_calibration_error(cases)
        rank_correlation = cls._compute_rank_correlation(cases)

        return {
            "scored_case_count": len(cases),
            "direction_accuracy": cls._hit_rate(direction_hits),
            "sentiment_accuracy": cls._hit_rate(sentiment_hits),
            "event_occurrence_accuracy": cls._hit_rate(occurrence_hits),
            "mean_distribution_distance": (
                statistics.mean(distances) if distances else None
            ),
            "mean_brier_score": statistics.mean(brier_scores) if brier_scores else None,
            "calibration_error": calibration,
            "rank_correlation": rank_correlation,
        }

    @staticmethod
    def _hit_rate(hits: List[bool]) -> Optional[Dict[str, Any]]:
        if not hits:
            return None
        return {
            "count": len(hits),
            "correct": sum(1 for h in hits if h),
            "accuracy": sum(1 for h in hits if h) / len(hits),
        }

    @staticmethod
    def _compute_calibration_error(cases: List[BacktestCase]) -> Optional[Dict[str, Any]]:
        """
        以十分位（0-0.1, 0.1-0.2, ..., 0.9-1.0）为桶的 expected calibration
        error：每个桶内比较"平均预测概率"与"实际发生比例"，按桶大小加权
        平均绝对差。需要至少 2 个同时具备 probability 与 occurred 真实结果
        的 case，否则视为数据不足，诚实地返回 None 而不是编造一个数字。
        """
        samples: List[Tuple[float, bool]] = []
        for case in cases:
            if case.prediction.probability is None or case.ground_truth is None:
                continue
            if case.ground_truth.occurred is None:
                continue
            samples.append((case.prediction.probability, case.ground_truth.occurred))

        if len(samples) < 2:
            return {"sample_count": len(samples), "expected_calibration_error": None}

        buckets: Dict[int, List[Tuple[float, bool]]] = {}
        for probability, occurred in samples:
            bucket_index = min(int(probability * 10), 9)
            buckets.setdefault(bucket_index, []).append((probability, occurred))

        total = len(samples)
        ece = 0.0
        bucket_details = []
        for bucket_index in sorted(buckets):
            bucket_samples = buckets[bucket_index]
            mean_predicted = statistics.mean(p for p, _ in bucket_samples)
            actual_rate = sum(1 for _, occurred in bucket_samples if occurred) / len(bucket_samples)
            weight = len(bucket_samples) / total
            ece += weight * abs(mean_predicted - actual_rate)
            bucket_details.append({
                "bucket": f"{bucket_index / 10:.1f}-{(bucket_index + 1) / 10:.1f}",
                "count": len(bucket_samples),
                "mean_predicted_probability": mean_predicted,
                "actual_occurrence_rate": actual_rate,
            })

        return {
            "sample_count": total,
            "expected_calibration_error": ece,
            "buckets": bucket_details,
        }

    @staticmethod
    def _compute_rank_correlation(cases: List[BacktestCase]) -> Optional[Dict[str, Any]]:
        pairs = [
            (case.prediction.rank, case.ground_truth.rank)
            for case in cases
            if case.prediction.rank is not None
            and case.ground_truth is not None
            and case.ground_truth.rank is not None
        ]
        if len(pairs) < 3:
            return {"sample_count": len(pairs), "spearman_rho": None}
        predicted_ranks = [p for p, _ in pairs]
        actual_ranks = [a for _, a in pairs]
        rho = _spearman_rank_correlation(predicted_ranks, actual_ranks)
        return {"sample_count": len(pairs), "spearman_rho": rho}
