"""Text processing service."""

from typing import List, Optional
from ..utils.file_parser import FileParser, split_text_into_chunks


class TextProcessor:
    """Extract, split and normalize source text."""

    @staticmethod
    def extract_from_files(file_paths: List[str]) -> str:
        """Extract the combined text of several files."""
        return FileParser.extract_from_multiple(file_paths)
    
    @staticmethod
    def split_text(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50
    ) -> List[str]:
        """Split text into overlapping chunks.

        Args:
            text: The source text.
            chunk_size: Characters per chunk.
            overlap: Characters shared between adjacent chunks.

        Returns:
            The chunks, in order.
        """
        return split_text_into_chunks(text, chunk_size, overlap)
    
    @staticmethod
    def preprocess_text(text: str) -> str:
        """Normalize line endings and strip redundant whitespace.

        Args:
            text: The source text.

        Returns:
            The normalized text.
        """
        import re

        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # Collapse runs of blank lines down to one.
        text = re.sub(r'\n{3,}', '\n\n', text)

        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(lines)
        
        return text.strip()
    
    @staticmethod
    def get_text_stats(text: str) -> dict:
        """Return character, line and word counts for the text."""
        return {
            "total_chars": len(text),
            "total_lines": text.count('\n') + 1,
            "total_words": len(text.split()),
        }

