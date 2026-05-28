"""
文本处理服务
"""

from typing import List, Optional
from ..utils.file_parser import FileParser, split_text_into_chunks


class TextProcessor:
    """文本处理器"""
    
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
        return split_text_into_chunks(text, chunk_size, overlap)
    
    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        预处理文本
        - 移除多余空白
        - 标准化换行
        
        Args:
            text: 原始文本
            
        Returns:
            处理后的文本
        """
        import re
        
        # 标准化换行
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # 移除连续空行（保留最多两个换行）
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 移除行首行尾空白
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)
        
        return text.strip()
    
    @staticmethod
    def get_text_stats(text: str) -> dict:
        """获取文本统计信息"""
        return {
            "total_chars": len(text),
            "total_lines": text.count('\n') + 1,
            "total_words": len(text.split()),
        }

