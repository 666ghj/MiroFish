"""
文本处理服务
"""

import re
from typing import List, Optional
from ..utils.file_parser import FileParser, split_text_into_chunks


class TextProcessor:
    """文本处理器"""

    # 这类章节和说明更像“如何喂系统”的元文本，不应直接送入图谱抽取。
    GRAPH_META_SECTION_PATTERNS = (
        r"给\s*MiroFish\s*/\s*知识图谱的约定",
        r"剧集编号与惯用标题",
        r"防误抽",
    )

    GRAPH_META_LINE_PATTERNS = (
        r"本文供\s*\*{0,2}MiroFish",
        r"供\s*MiroFish.*抽取.*推演",
        r"请勿.*Agent",
        r"请勿.*节点",
        r"非角色",
        r"抽取实体时请合并",
        r"平行假设放哪",
        r"勿把平行结局写进本文件正文",
    )

    @staticmethod
    def extract_from_files(file_paths: List[str]) -> str:
        """从多个文件提取文本"""
        return FileParser.extract_from_multiple(file_paths)
    
    @staticmethod
    def split_text(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50
    ) -> List[str]:
        """
        分割文本
        
        Args:
            text: 原始文本
            chunk_size: 块大小
            overlap: 重叠大小
            
        Returns:
            文本块列表
        """
        text = TextProcessor.preprocess_text(text)
        return split_text_into_chunks(text, chunk_size, overlap)
    
    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        预处理文本
        - 移除多余空白
        - 标准化换行
        - 保守清理“说明层/导航层”文本
        - 删除剧集编号与英文单集标题等非主体锚点
        
        Args:
            text: 原始文本
            
        Returns:
            处理后的文本
        """
        # 标准化换行
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        raw_lines = [line.strip() for line in text.split('\n')]
        title_pattern = re.compile(r"(?<!\*)\*([A-Za-z][A-Za-z0-9 '\-]{1,60})\*(?!\*)")
        non_subject_terms = set()

        for line in raw_lines:
            if "惯用标题" in line or ("|" in line and re.search(r"\bS\d{2}E\d{2}\b", line)):
                for match in title_pattern.findall(line):
                    non_subject_terms.add(match.strip())

        cleaned_lines: List[str] = []
        skip_section = False
        in_naming_section = False

        for line in raw_lines:
            if not line:
                cleaned_lines.append("")
                continue

            if line.startswith("## "):
                in_naming_section = "命名规范" in line
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in TextProcessor.GRAPH_META_SECTION_PATTERNS):
                    skip_section = True
                    continue
                skip_section = False

            if skip_section:
                continue

            if in_naming_section and "|" in line:
                columns = [part.strip() for part in line.strip("|").split("|")]
                if len(columns) >= 2:
                    canonical = re.sub(r"\*+", "", columns[0]).strip()
                    note = columns[1]
                    line = f"| {canonical} | {note.strip()} |"

            if any(re.search(pattern, line, re.IGNORECASE) for pattern in TextProcessor.GRAPH_META_LINE_PATTERNS):
                continue

            line = re.sub(r"\bS\d{2}E\d{2}\b", "", line)
            line = re.sub(r"(?<!\*)\*([A-Za-z][A-Za-z0-9 '\-]{1,60})\*(?!\*)", "", line)

            for term in sorted(non_subject_terms, key=len, reverse=True):
                line = re.sub(rf"\*{{0,3}}{re.escape(term)}\*{{0,3}}", "", line)

            if re.fullmatch(r"[|\-:\s]+", line):
                continue

            simplified = re.sub(r"[\s|:\-*`_]+", "", line)
            if not simplified:
                continue

            line = re.sub(r"\s{2,}", " ", line).strip()
            if not line:
                continue

            cleaned_lines.append(line)

        text = "\n".join(cleaned_lines)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    
    @staticmethod
    def get_text_stats(text: str) -> dict:
        """获取文本统计信息"""
        return {
            "total_chars": len(text),
            "total_lines": text.count('\n') + 1,
            "total_words": len(text.split()),
        }
