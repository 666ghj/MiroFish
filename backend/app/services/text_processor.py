"""
Dịch vụ xử lý văn bản (Text processing service)
"""

from typing import List, Optional
from ..utils.file_parser import FileParser, split_text_into_chunks


class TextProcessor:
    """Trình xử lý văn bản"""
    
    @staticmethod
    def extract_from_files(file_paths: List[str]) -> str:
        """Trích xuất và kết hợp văn bản từ nhiều file (các đường dẫn file truyền vào)"""
        return FileParser.extract_from_multiple(file_paths)
    
    @staticmethod
    def split_text(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50
    ) -> List[str]:
        """
        Chia nhỏ văn bản (Phân mảnh văn bản dài thành các đoạn nhỏ hơn - chunking)
        
        Args:
            text: Văn bản gốc cần chia
            chunk_size: Kích thước tối đa của mỗi đoạn (chunk)
            overlap: Số ký tự chồng chéo giữa các đoạn liên tiếp (để giữ bối cảnh không bị đứt đoạn)
            
        Returns:
            Danh sách gồm các mảng văn bản sau khi chia
        """
        return split_text_into_chunks(text, chunk_size, overlap)
    
    @staticmethod
    def preprocess_text(text: str) -> str:
        """
        Tiền xử lý văn bản (Làm sạch văn bản)
        - Xoá bỏ các khoảng trắng thừa
        - Chuẩn hoá định dạng xuống dòng (Line breaks)
        
        Args:
            text: Văn bản thô ban đầu
            
        Returns:
            Văn bản đã được tinh giản, làm sạch
        """
        import re
        
        # Chuẩn hoá ký tự xuống dòng (Windows \r\n hoặc Mac cũ \r thành \n chuẩn Linux)
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Xoá các dòng trống liên tiếp (Chỉ giữ lại tối đa 2 lần xuống dòng liên tiếp)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Loại bỏ khoảng trắng đầu và cuối
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)
        
        return text.strip()
    
    @staticmethod
    def get_text_stats(text: str) -> dict:
        """Lấy một số thông tin thống kê về đoạn văn bản (Số ký tự, số dòng, số từ)"""
        return {
            "total_chars": len(text),
            "total_lines": text.count('\n') + 1,
            "total_words": len(text.split()),
        }

