"""
File parsing utilities.

Extracts plain text from PDF, Markdown and TXT files.
"""

import os
from pathlib import Path
from typing import List, Optional


def _read_text_with_fallback(file_path: str) -> str:
    """
    Read a text file, detecting the encoding when UTF-8 fails.

    The fallback chain is:
    1. Decode as UTF-8
    2. Detect the encoding with charset_normalizer
    3. Detect the encoding with chardet
    4. Decode as UTF-8 with errors='replace'

    Args:
        file_path: Path to the file

    Returns:
        The decoded text
    """
    data = Path(file_path).read_bytes()
    
    # UTF-8 first: it is what everything the product writes uses.
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    
    # Fall back to detection.
    encoding = None
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        pass
    
    if not encoding:
        try:
            import chardet
            result = chardet.detect(data)
            encoding = result.get('encoding') if result else None
        except Exception:
            pass
    
    # Last resort: decode as UTF-8 and replace whatever does not fit.
    if not encoding:
        encoding = 'utf-8'
    
    return data.decode(encoding, errors='replace')


class FileParser:
    """Text extraction for the supported document formats."""
    
    SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown', '.txt'}
    
    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """
        Report whether the file format is supported.

        Args:
            file_path: Path to the file

        Returns:
            True when the format is supported
        """
        suffix = Path(file_path).suffix.lower()
        return suffix in cls.SUPPORTED_EXTENSIONS
    
    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """
        Extract the text of a single file.

        Args:
            file_path: Path to the file

        Returns:
            The extracted text
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        suffix = path.suffix.lower()
        
        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file format: {suffix}")
        
        if suffix == '.pdf':
            return cls._extract_from_pdf(file_path)
        elif suffix in {'.md', '.markdown'}:
            return cls._extract_from_md(file_path)
        elif suffix == '.txt':
            return cls._extract_from_txt(file_path)
        
        raise ValueError(f"No parser is registered for the file format {suffix}.")
    
    @staticmethod
    def _extract_from_pdf(file_path: str) -> str:
        """Extract the text of a PDF."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF is required. Install it with: pip install PyMuPDF")
        
        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        """Extract the text of a Markdown file, detecting the encoding."""
        return _read_text_with_fallback(file_path)
    
    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        """Extract the text of a plain text file, detecting the encoding."""
        return _read_text_with_fallback(file_path)
    
    @classmethod
    def extract_from_multiple(cls, file_paths: List[str]) -> str:
        """
        Extract the text of several files and concatenate it.

        Args:
            file_paths: Paths to the files

        Returns:
            The combined text
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
    Split text into overlapping chunks.

    Args:
        text: The source text
        chunk_size: Characters per chunk
        overlap: Characters shared between adjacent chunks

    Returns:
        The list of chunks
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # Prefer a sentence boundary over a hard cut.
        if end < len(text):
            # Search backwards for the last sentence terminator in this window.
            for sep in ['.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ']:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # The next chunk starts inside the current one, by `overlap` characters.
        start = end - overlap if end < len(text) else len(text)
    
    return chunks

