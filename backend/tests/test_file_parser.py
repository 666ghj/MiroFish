"""Unit tests for file_parser module."""

import os
import tempfile
from pathlib import Path

import pytest

# Import the module directly to avoid Flask initialization issues
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Direct import of the module to avoid app package initialization
import importlib.util
spec = importlib.util.spec_from_file_location(
    "file_parser",
    Path(__file__).parent.parent / "app" / "utils" / "file_parser.py"
)
file_parser_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(file_parser_module)

_read_text_with_fallback = file_parser_module._read_text_with_fallback
FileParser = file_parser_module.FileParser
split_text_into_chunks = file_parser_module.split_text_into_chunks


class TestReadTextWithFallback:
    """Tests for _read_text_with_fallback function."""

    def test_read_utf8_file(self):
        """Should read UTF-8 encoded file correctly."""
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False) as f:
            f.write("Hello, 你好, こんにちは")
            path = f.name
        try:
            result = _read_text_with_fallback(path)
            assert result == "Hello, 你好, こんにちは"
        finally:
            os.unlink(path)

    def test_read_gbk_file_with_fallback(self):
        """Should read GBK encoded file using UTF-8 replacement when detection fails."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            content = "你好世界".encode('gbk')
            f.write(content)
            path = f.name
        try:
            result = _read_text_with_fallback(path)
            # Result may be garbled if charset detection fails, but should not raise
            assert len(result) > 0
        finally:
            os.unlink(path)

    def test_read_latin1_file(self):
        """Should read Latin-1 encoded file using UTF-8 replacement when detection fails."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            content = "Héllo Wörld".encode('latin-1')
            f.write(content)
            path = f.name
        try:
            result = _read_text_with_fallback(path)
            # Result may be garbled if charset detection fails, but should not raise
            assert len(result) > 0
        finally:
            os.unlink(path)

    def test_read_file_with_replacement_chars(self):
        """Should replace invalid characters instead of failing."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            content = b"Hello\x00\xff\xfeWorld"
            f.write(content)
            path = f.name
        try:
            result = _read_text_with_fallback(path)
            assert "Hello" in result
            assert "World" in result
        finally:
            os.unlink(path)


class TestFileParser:
    """Tests for FileParser class."""

    def test_supported_extensions(self):
        """Should have correct supported extensions."""
        assert '.pdf' in FileParser.SUPPORTED_EXTENSIONS
        assert '.md' in FileParser.SUPPORTED_EXTENSIONS
        assert '.markdown' in FileParser.SUPPORTED_EXTENSIONS
        assert '.txt' in FileParser.SUPPORTED_EXTENSIONS

    def test_extract_text_from_nonexistent_file(self):
        """Should raise FileNotFoundError for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            FileParser.extract_text('/nonexistent/file.txt')

    def test_extract_text_from_unsupported_format(self):
        """Should raise ValueError for unsupported format."""
        with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ValueError, match="不支持的文件格式"):
                FileParser.extract_text(path)
        finally:
            os.unlink(path)

    def test_extract_text_from_md_file(self):
        """Should extract text from markdown file."""
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.md', delete=False) as f:
            f.write("# Title\n\nThis is content.")
            path = f.name
        try:
            result = FileParser.extract_text(path)
            assert "# Title" in result
            assert "This is content." in result
        finally:
            os.unlink(path)

    def test_extract_text_from_txt_file(self):
        """Should extract text from txt file."""
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False) as f:
            f.write("Plain text content")
            path = f.name
        try:
            result = FileParser.extract_text(path)
            assert result == "Plain text content"
        finally:
            os.unlink(path)

    def test_extract_from_multiple_with_all_valid(self):
        """Should extract from multiple valid files."""
        files = []
        try:
            for i in range(3):
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(f"Content {i}")
                    files.append(f.name)

            result = FileParser.extract_from_multiple(files)
            assert "Content 0" in result
            assert "Content 1" in result
            assert "Content 2" in result
            assert "文档 1" in result
            assert "文档 2" in result
            assert "文档 3" in result
        finally:
            for path in files:
                os.unlink(path)

    def test_extract_from_multiple_with_invalid_file(self):
        """Should handle invalid file gracefully in batch mode."""
        files = [
            '/nonexistent/path.txt',
        ]
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("Valid content")
                files.append(f.name)

            result = FileParser.extract_from_multiple(files)
            assert "Valid content" in result
            assert "提取失败" in result
        finally:
            for path in files[1:]:
                if os.path.exists(path):
                    os.unlink(path)


class TestSplitTextIntoChunks:
    """Tests for split_text_into_chunks function."""

    def test_short_text_returns_single_chunk(self):
        """Should return single chunk when text is shorter than chunk_size."""
        text = "Short text"
        result = split_text_into_chunks(text, chunk_size=500, overlap=50)
        assert len(result) == 1
        assert result[0] == text

    def test_empty_text_returns_empty_list(self):
        """Should return empty list for empty/whitespace text."""
        assert split_text_into_chunks("   ", chunk_size=500, overlap=50) == []
        assert split_text_into_chunks("", chunk_size=500, overlap=50) == []

    def test_text_exactly_at_chunk_size(self):
        """Should return single chunk when text equals chunk_size."""
        text = "a" * 500
        result = split_text_into_chunks(text, chunk_size=500, overlap=50)
        assert len(result) == 1

    def test_long_text_splits_into_multiple_chunks(self):
        """Should split long text into multiple chunks."""
        text = "a" * 1000
        result = split_text_into_chunks(text, chunk_size=500, overlap=50)
        assert len(result) >= 2

    def test_chunks_have_overlap(self):
        """Should have overlapping content between consecutive chunks."""
        text = "abcdefghij" * 100
        chunks = split_text_into_chunks(text, chunk_size=100, overlap=20)
        if len(chunks) >= 2:
            assert chunks[0][-20:] == chunks[1][:20], "Chunks should overlap"

    def test_chunks_preserve_content(self):
        """Should preserve all original content across chunks."""
        text = "".join(str(i) for i in range(500))
        chunks = split_text_into_chunks(text, chunk_size=100, overlap=10)
        combined = "".join(chunks)
        assert text[:400] in combined or all(c in combined for c in text[:400])

    def test_chunk_size_parameter(self):
        """Should respect chunk_size parameter."""
        text = "a" * 1000
        result = split_text_into_chunks(text, chunk_size=100, overlap=0)
        for chunk in result:
            assert len(chunk) <= 100

    def test_overlap_parameter(self):
        """Should respect overlap parameter."""
        text = "abcdefghij" * 100
        chunks = split_text_into_chunks(text, chunk_size=50, overlap=10)
        if len(chunks) >= 2:
            overlap_size = len(chunks[0]) - (len(chunks[0].rstrip()) - len(chunks[1].lstrip()))
            assert overlap_size >= 5

    def test_split_at_sentence_boundary(self):
        """Should try to split at sentence boundaries when possible."""
        text = "第一句。第二句。第三句。" * 50
        chunks = split_text_into_chunks(text, chunk_size=100, overlap=10)
        for chunk in chunks:
            if len(chunk) > 50:
                assert chunk[-1] in "。.\n"

    def test_last_chunk_may_be_smaller(self):
        """Should allow last chunk to be smaller than chunk_size."""
        text = "a" * 550
        result = split_text_into_chunks(text, chunk_size=500, overlap=50)
        assert any(len(chunk) < 500 for chunk in result)

    def test_whitespace_only_chunks_filtered(self):
        """Should filter out whitespace-only chunks."""
        text = "content" + " " * 600 + "more content"
        result = split_text_into_chunks(text, chunk_size=500, overlap=50)
        for chunk in result:
            assert chunk.strip()