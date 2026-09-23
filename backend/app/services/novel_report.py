"""小说模式报告约束与确定性后处理（novel-mac fork，改造 ③）。

novel seed 建立的项目在报告生成时启用：
1. 大纲规划 prompt 的小说 craft 附加强约束；
2. LLM 失败时的确定性 fallback 大纲（章节即 craft 面）；
3. 最终 markdown 的确定性后处理：越界市场断言降级标注，追加
   「限制与不确定」一节（非市场代表、不作预测、proposal-only、
   标注 sourceRevision）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

NOVEL_OUTLINE_ADDENDUM = (
    "\n\n【小说沙盘模式附加要求】本报告服务小说创作推演，大纲必须包含且仅面向：\n"
    "1. 每个显式读者 Persona 的原始反应与正文引用片段（逐 Persona）；\n"
    "2. Persona 之间的分歧与误读（对照正文证据）；\n"
    "3. 期待与退出点：哪些期待被建立、哪些 Persona 在哪里失去继续阅读的理由；\n"
    "4. 未收束钩子：模拟结束时仍悬置的线索与问题；\n"
    "5. 限制与不确定：模拟人群不是市场代表，不得给出任何市场/销量/流量预测。\n"
    "禁止输出『必然爆款』『必火』『销量』『流量密码』等市场断言作为结论。"
)

NOVEL_FALLBACK_TITLE = "小说沙盘推演报告"
NOVEL_FALLBACK_SUMMARY = "读者 Persona 群体反应的小说创作参考（非市场预测）"
NOVEL_FALLBACK_SECTIONS = [
    "Persona 反应与正文引用",
    "分歧与误读",
    "期待与退出点",
    "未收束钩子",
    "限制与不确定",
]

_MARKET_CLAIM_PATTERN = re.compile(
    r"(必然爆款|必火|大爆|爆款预定|销量[会必]|流量密码|市场必然|稳了[！!]|封神[之作]?)"
)
_MARKET_WARNING = "⚠️ 未经证实的市场断言（原文保留，不作结论）："


def neutralize_market_claims(markdown: str) -> str:
    """把含市场断言的整行降级为警告前缀的引用行；原文保留。"""

    lines = markdown.splitlines(keepends=False)
    treated = []
    for line in lines:
        if _MARKET_CLAIM_PATTERN.search(line):
            treated.append(f"> {_MARKET_WARNING}{line.strip()}")
        else:
            treated.append(line)
    return "\n".join(treated) + ("\n" if markdown.endswith("\n") else "")


def _constraints_section(novel_seed: Dict[str, Any]) -> str:
    project_id = novel_seed.get("projectId", "")
    revision = novel_seed.get("sourceRevision", "?")
    input_hash = novel_seed.get("inputHash", "")
    return (
        "\n\n## 限制与不确定\n\n"
        "- 本报告是小说沙盘推演的群体模拟产物，模拟人群**不是**市场代表，"
        "任何结论都不可外推为市场表现或销量/流量预测。\n"
        f"- 来源：novel-agent 已接受修订 R{revision}"
        f"（project {project_id}，input hash `{input_hash}`）。\n"
        "- 所有内容仅为创作参考；要写进故事事实，必须回到 novel-agent 的"
        "提案审阅 → 作者接受流程（proposal-only）。\n"
    )


def novel_report_postprocess(markdown: str, novel_seed: Optional[Dict[str, Any]]) -> str:
    """小说模式的确定性报告后处理；无 novel_seed 时恒等返回。"""

    if not novel_seed:
        return markdown
    result = neutralize_market_claims(markdown)
    if "## 限制与不确定" not in result:
        result = result.rstrip("\n") + _constraints_section(novel_seed)
    return result
