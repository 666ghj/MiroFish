"""
File parsing utilities
Supports text extraction from PDF, Markdown, and TXT files.
"""

import os
from pathlib import Path
from typing import List, Optional


def _read_text_with_fallback(file_path: str) -> str:
    """
    Read a text file; if UTF-8 decoding fails, automatically detect the encoding.

    Uses a multi-level fallback strategy:
    1. First try decoding as UTF-8.
    2. Detect the encoding using charset_normalizer.
    3. Fall back to chardet for encoding detection.
    4. As a final fallback, decode as UTF-8 with errors='replace'.

    Args:
        file_path: file path

    Returns:
        Decoded text content
    """
    data = Path(file_path).read_bytes()

    # First try UTF-8
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass

    # Try detecting the encoding with charset_normalizer
    encoding = None
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        pass

    # Fall back to chardet
    if not encoding:
        try:
            import chardet
            result = chardet.detect(data)
            encoding = result.get('encoding') if result else None
        except Exception:
            pass

    # Final fallback: UTF-8 + replace
    if not encoding:
        encoding = 'utf-8'

    return data.decode(encoding, errors='replace')


class FileParser:
    """File parser"""

    SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown', '.txt'}

    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """
        Extract text from a file.

        Args:
            file_path: file path

        Returns:
            Extracted text content
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        suffix = path.suffix.lower()

        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file format: {suffix}")

        if suffix == '.pdf':
            return cls._extract_from_pdf(file_path)
        elif suffix in {'.md', '.markdown'}:
            return cls._extract_from_md(file_path)
        elif suffix == '.txt':
            return cls._extract_from_txt(file_path)

        raise ValueError(f"Unhandled file format: {suffix}")

    @staticmethod
    def _extract_from_pdf(file_path: str) -> str:
        """Extract text from a PDF"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF must be installed: pip install PyMuPDF")

        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)

        return "\n\n".join(text_parts)

    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        """Extract text from Markdown, with automatic encoding detection"""
        return _read_text_with_fallback(file_path)

    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        """Extract text from TXT, with automatic encoding detection"""
        return _read_text_with_fallback(file_path)

    @classmethod
    def extract_from_multiple(cls, file_paths: List[str]) -> str:
        """
        Extract text from multiple files and merge.

        Args:
            file_paths: list of file paths

        Returns:
            Combined text
        """
        all_texts = []

        for i, file_path in enumerate(file_paths, 1):
            try:
                text = cls.extract_text(file_path)
                filename = Path(file_path).name
                all_texts.append(f"=== Document {i}: {filename} ===\n{text}")
            except Exception as e:
                all_texts.append(f"=== Document {i}: {file_path} (extraction failed: {str(e)}) ===")

        return "\n\n".join(all_texts)


def split_text_into_chunks(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[str]:
    """
    Split text into smaller chunks.

    Args:
        text: original text
        chunk_size: number of characters per chunk
        overlap: number of overlapping characters

    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Try to split at a sentence boundary
        if end < len(text):
            # Look for the nearest sentence-ending separator (CJK punctuation kept intentionally so
            # that Chinese-language input still splits at sentence boundaries; do not translate these).
            for sep in ['。', '！', '？', '.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ']:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Next chunk starts at the overlap position
        start = end - overlap if end < len(text) else len(text)

    return chunks
