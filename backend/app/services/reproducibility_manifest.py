"""
模拟可复现性清单（Reproducibility Manifest）

在每次模拟准备（prepare_simulation）完成后，与其他产物一起持久化一份清单，
记录足以在事后重建或对比一次运行执行条件的信息：使用了哪个 LLM 模型、
源文档/本体/生成的 Agent Profile 的内容哈希、控制 MiroFish 自身非 LLM
随机性的种子、以及运行时的代码/依赖版本。

重要限制：这不能让整个模拟变成完全确定性的。LLM 在温度 > 0 时采样本身
就不是确定性的，MiroFish 也没有向 LLM API 传递 seed 参数；OASIS 内部的
随机性同样不受此处控制。清单中的 `randomness` 字段明确说明了这一点，
而不是假装提供了它做不到的保证。

范围限制：这份清单只捕获"准备阶段"（prepare_simulation）的执行条件，
不包含只有在"运行阶段"（/api/simulation/start）才会确定的事实——例如
调用方传入的 max_rounds 覆盖值，或 run_parallel_simulation.py 在启用
LLM_BOOST_* 配置时为 OASIS Agent 实际选用的加速模型（可能与本清单
`model` 字段记录的准备阶段模型不同）。将清单扩展到覆盖运行阶段、并在
/start 时更新它，是一项独立的后续工作。
"""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.state_machine import atomic_write_json

logger = get_logger('mirofish.reproducibility')

SCHEMA_VERSION = 1
MANIFEST_FILENAME = "reproducibility_manifest.json"


# ────────────────────────── 哈希辅助函数 ──────────────────────────

def sha256_text(text: Optional[str]) -> Optional[str]:
    """UTF-8 字符串的 SHA-256 十六进制摘要；输入为空则返回 None。"""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(data: Any) -> Optional[str]:
    """JSON 可序列化值的 SHA-256 摘要，使用稳定（key 排序）的编码方式。"""
    if not data:
        return None
    return sha256_text(json.dumps(data, sort_keys=True, ensure_ascii=False))


def sha256_file(path: Optional[str]) -> Optional[str]:
    """文件内容的 SHA-256 摘要；文件不存在则返回 None。"""
    if not path or not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ────────────────────────── 运行时版本信息 ──────────────────────────

def get_mirofish_revision() -> str:
    """尽力获取当前后端代码的 git commit hash；不可用时退回包版本号，再不行返回 'unknown'。"""
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return f"mirofish-backend=={get_package_version('mirofish-backend')}"


def get_package_version(name: str) -> str:
    """尽力获取已安装包的版本号；不可用时返回 'unknown'。"""
    try:
        return importlib.metadata.version(name)
    except Exception:
        return "unknown"


# ────────────────────────── 数据结构 ──────────────────────────

@dataclass
class ModelInfo:
    provider: str
    name: str
    base_url: str


@dataclass
class SimulationInfo:
    simulation_id: str
    project_id: str
    graph_id: str
    entity_types: List[str] = field(default_factory=list)
    entities_count: int = 0
    agent_count: int = 0
    enable_twitter: bool = True
    enable_reddit: bool = True


@dataclass
class ArtifactHashes:
    ontology_hash: Optional[str] = None
    source_document_hash: Optional[str] = None
    reddit_profiles_hash: Optional[str] = None
    twitter_profiles_hash: Optional[str] = None
    simulation_config_hash: Optional[str] = None


@dataclass
class RuntimeInfo:
    mirofish_revision: str = "unknown"
    oasis_version: str = "unknown"
    camel_ai_version: str = "unknown"
    python_version: str = "unknown"


@dataclass
class RandomnessInfo:
    seed: Optional[int] = None
    deterministic: bool = False
    notes: str = (
        "seed 只控制 MiroFish 自身在 profile 生成阶段的兜底随机默认值"
        "（当 LLM 未给出某个人设字段时，如年龄/性别/MBTI/karma 等）。"
        "它不会让 LLM 生成的内容变得确定（温度 > 0 且未向 LLM API 传递 seed），"
        "也不控制 OASIS 内部自身的随机性。"
    )


@dataclass
class ReproducibilityManifest:
    schema_version: int
    simulation: SimulationInfo
    model: ModelInfo
    artifacts: ArtifactHashes
    runtime: RuntimeInfo
    randomness: RandomnessInfo
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "simulation": asdict(self.simulation),
            "model": asdict(self.model),
            "artifacts": asdict(self.artifacts),
            "runtime": asdict(self.runtime),
            "randomness": asdict(self.randomness),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReproducibilityManifest':
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            generated_at=data.get("generated_at", ""),
            simulation=SimulationInfo(**data.get("simulation", {})),
            model=ModelInfo(**data.get("model", {})),
            artifacts=ArtifactHashes(**data.get("artifacts", {})),
            runtime=RuntimeInfo(**data.get("runtime", {})),
            randomness=RandomnessInfo(**data.get("randomness", {})),
        )


# ────────────────────────── 构建与持久化 ──────────────────────────

def build_manifest(
    *,
    state,
    sim_dir: str,
    project=None,
    sim_params=None,
    document_text: Optional[str] = None,
) -> ReproducibilityManifest:
    """
    构建一份可复现性清单。

    Args:
        state: SimulationState（已完成 profile / config 生成）
        sim_dir: 该模拟的持久化目录（包含 profiles / config 等产物文件）
        project: 对应的 Project（可选；提供时用于计算本体哈希，以及在未显式
            传入 document_text 时作为源文档哈希的后备来源）
        sim_params: SimulationConfigGenerator 生成的 SimulationParameters（可选；
            提供时用于计算 agent_count）
        document_text: prepare_simulation 本次实际使用的源文档文本。应始终
            传入这个值而不是让本函数重新从 Project 读取——调用方接收到的
            document_text 参数可能与 Project 当前持久化的提取文本不一致
            （例如后续被重新上传/覆盖），此时重新读取会让清单记录错误的
            源文档指纹。
    """
    ontology_hash = sha256_json(project.ontology) if project else None

    if document_text is not None:
        source_document_hash = sha256_text(document_text)
    else:
        source_document_hash = None
        if project:
            try:
                from ..models.project import ProjectManager
                source_document_hash = sha256_text(
                    ProjectManager.get_extracted_text(project.project_id)
                )
            except Exception:
                logger.exception(f"计算源文档哈希失败: project_id={project.project_id}")

    reddit_path = os.path.join(sim_dir, "reddit_profiles.json")
    twitter_path = os.path.join(sim_dir, "twitter_profiles.csv")
    config_path = os.path.join(sim_dir, "simulation_config.json")

    agent_count = (
        len(sim_params.agent_configs) if sim_params is not None else state.profiles_count
    )

    return ReproducibilityManifest(
        schema_version=SCHEMA_VERSION,
        simulation=SimulationInfo(
            simulation_id=state.simulation_id,
            project_id=state.project_id,
            graph_id=state.graph_id,
            entity_types=list(state.entity_types),
            entities_count=state.entities_count,
            agent_count=agent_count,
            enable_twitter=state.enable_twitter,
            enable_reddit=state.enable_reddit,
        ),
        model=ModelInfo(
            provider="openai-compatible",
            name=Config.LLM_MODEL_NAME,
            base_url=Config.LLM_BASE_URL,
        ),
        artifacts=ArtifactHashes(
            ontology_hash=ontology_hash,
            source_document_hash=source_document_hash,
            reddit_profiles_hash=sha256_file(reddit_path) if state.enable_reddit else None,
            twitter_profiles_hash=sha256_file(twitter_path) if state.enable_twitter else None,
            simulation_config_hash=sha256_file(config_path),
        ),
        runtime=RuntimeInfo(
            mirofish_revision=get_mirofish_revision(),
            oasis_version=get_package_version("camel-oasis"),
            camel_ai_version=get_package_version("camel-ai"),
            python_version=platform.python_version(),
        ),
        randomness=RandomnessInfo(seed=getattr(state, "random_seed", None)),
    )


def manifest_path(sim_dir: str) -> str:
    return os.path.join(sim_dir, MANIFEST_FILENAME)


def save_manifest(sim_dir: str, manifest: ReproducibilityManifest) -> None:
    """原子性地将清单写入该模拟目录。"""
    atomic_write_json(manifest_path(sim_dir), manifest.to_dict())


def load_manifest(sim_dir: str) -> Optional[Dict[str, Any]]:
    """读取该模拟目录下已持久化的清单；不存在则返回 None。"""
    path = manifest_path(sim_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        logger.exception(f"读取可复现性清单失败: {path}")
        return None
