from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


def _load_text_processor():
    backend_dir = Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    module_path = backend_dir / "app" / "services" / "text_processor.py"
    spec = spec_from_file_location("app.services.text_processor_test", module_path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.TextProcessor


TextProcessor = _load_text_processor()


def test_preprocess_text_removes_graph_meta_and_episode_titles():
    text = """
本文供 **MiroFish** 等工具做人物与关系底座抽取与推演。

## 给 MiroFish / 知识图谱的约定（请先读）
1. **剧集怎样引用**：S04E13 *Face Off* 不是角色，勿单独建 Agent 节点。

## Walter White（一类）
高中化学教师，已以 **Heisenberg** 身份与 Jesse 制毒。
7. *End Times*：利用 Brock 急病建构 Gus 陷害叙事。
8. *Face Off* 正史：与 Hector 合谋炸弹杀 Gus。
"""

    processed = TextProcessor.preprocess_text(text)

    assert "MiroFish" not in processed
    assert "8. *Face Off*" not in processed
    assert "S04E13" not in processed
    assert "Walter White" in processed
    assert "Heisenberg" in processed
    assert "Gus" in processed


def test_preprocess_text_keeps_naming_table_but_strips_episode_title_noise():
    text = """
## 命名规范（抽取实体时请合并为单一节点）
| Walter White | 亦称 Walt；**Heisenberg** 仍指同一人，勿拆节点。 |
| Hank Schrader | DEA 探员。**DEA 为机构**，勿与 Hank 重复为同级「人物节点」。 |

## 剧集编号与惯用标题（防误抽）
| **S04E13** | *Face Off* |
- **请勿**将 *Mandala*、*Face Off* 等注册为同级人物 Agent——它们是**集名**。
"""

    processed = TextProcessor.preprocess_text(text)

    assert "Graph Extraction Hints" not in processed
    assert "Walter White" in processed
    assert "Heisenberg" in processed
    assert "DEA 为机构" in processed
    assert "S04E13" not in processed
    assert "Face Off" not in processed
    assert "Mandala" not in processed
