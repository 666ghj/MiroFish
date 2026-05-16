"""
文件解析工具
支持PDF、Markdown、TXT、音频、视频文件的文本提取
"""

import os
import tempfile
from pathlib import Path
from typing import List, Optional


def _read_text_with_fallback(file_path: str) -> str:
    """
    读取文本文件，UTF-8失败时自动探测编码。
    
    采用多级回退策略：
    1. 首先尝试 UTF-8 解码
    2. 使用 charset_normalizer 检测编码
    3. 回退到 chardet 检测编码
    4. 最终使用 UTF-8 + errors='replace' 兜底
    
    Args:
        file_path: 文件路径
        
    Returns:
        解码后的文本内容
    """
    data = Path(file_path).read_bytes()
    
    # 首先尝试 UTF-8
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    
    # 尝试使用 charset_normalizer 检测编码
    encoding = None
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best and best.encoding:
            encoding = best.encoding
    except Exception:
        pass
    
    # 回退到 chardet
    if not encoding:
        try:
            import chardet
            result = chardet.detect(data)
            encoding = result.get('encoding') if result else None
        except Exception:
            pass
    
    # 最终兜底：使用 UTF-8 + replace
    if not encoding:
        encoding = 'utf-8'
    
    return data.decode(encoding, errors='replace')


class FileParser:
    """文件解析器"""

    # Formats sent directly to the transcription endpoint (or multimodal chat after PyAV conversion)
    _AUDIO_NATIVE = {'.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.ogg', '.wav', '.webm', '.flac'}
    # Video container formats — audio extracted via PyAV before transcription
    _VIDEO_CONTAINERS = {'.mkv', '.avi', '.mov', '.wmv'}

    SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.markdown', '.txt'} | _AUDIO_NATIVE | _VIDEO_CONTAINERS

    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """
        从文件中提取文本

        Args:
            file_path: 文件路径

        Returns:
            提取的文本内容
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()

        if suffix not in cls.SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件格式: {suffix}")

        if suffix == '.pdf':
            return cls._extract_from_pdf(file_path)
        elif suffix in {'.md', '.markdown'}:
            return cls._extract_from_md(file_path)
        elif suffix == '.txt':
            return cls._extract_from_txt(file_path)
        elif suffix in cls._AUDIO_NATIVE:
            return cls._transcribe_audio(file_path)
        elif suffix in cls._VIDEO_CONTAINERS:
            return cls._transcribe_video(file_path)

        raise ValueError(f"无法处理的文件格式: {suffix}")
    
    @staticmethod
    def _extract_from_pdf(file_path: str) -> str:
        """从PDF提取文本"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("需要安装PyMuPDF: pip install PyMuPDF")
        
        text_parts = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    text_parts.append(text)
        
        return "\n\n".join(text_parts)
    
    @staticmethod
    def _extract_from_md(file_path: str) -> str:
        """从Markdown提取文本，支持自动编码检测"""
        return _read_text_with_fallback(file_path)
    
    @staticmethod
    def _extract_from_txt(file_path: str) -> str:
        """从TXT提取文本，支持自动编码检测"""
        return _read_text_with_fallback(file_path)
    
    @staticmethod
    def _to_wav_bytes(file_path: str) -> bytes:
        """Extract audio from any container and return raw WAV bytes using PyAV."""
        try:
            import av
        except ImportError:
            raise ImportError(
                "PyAV is required to convert audio/video files. "
                "Install it with: pip install av"
            )
        import io

        buf = io.BytesIO()
        with av.open(file_path) as inp:
            audio = next((s for s in inp.streams if s.type == 'audio'), None)
            if audio is None:
                raise ValueError(f"No audio track found in: {file_path}")
            with av.open(buf, 'w', format='wav') as out:
                out_stream = out.add_stream('pcm_s16le', rate=16000, layout='mono')
                for packet in inp.demux(audio):
                    for frame in packet.decode():
                        frame.pts = None
                        for pkt in out_stream.encode(frame):
                            out.mux(pkt)
                for pkt in out_stream.encode(None):
                    out.mux(pkt)
        buf.seek(0)
        return buf.read()

    @staticmethod
    def _transcribe_audio(file_path: str) -> str:
        """Transcribe audio file.

        Tries the Whisper-style /audio/transcriptions endpoint first (OpenAI, Groq, etc.).
        Falls back to multimodal chat (Gemini and other vision/audio LLMs) if the
        provider doesn't support that endpoint (404).
        """
        import base64
        from openai import OpenAI, NotFoundError
        from ..config import Config

        client = OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL)

        # --- attempt 1: Whisper-compatible endpoint ---
        try:
            with open(file_path, 'rb') as f:
                transcript = client.audio.transcriptions.create(
                    model=Config.WHISPER_MODEL,
                    file=f,
                )
            return transcript.text
        except NotFoundError:
            pass  # Provider doesn't expose Whisper; fall through to multimodal chat

        # --- attempt 2: multimodal chat (e.g. Gemini) ---
        # Gemini only accepts wav/mp3; convert anything else using PyAV (no system ffmpeg needed)
        fmt = Path(file_path).suffix.lower().lstrip('.')
        if fmt in ('wav', 'mp3'):
            with open(file_path, 'rb') as f:
                audio_bytes = f.read()
        else:
            audio_bytes = FileParser._to_wav_bytes(file_path)
            fmt = 'wav'

        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        response = client.chat.completions.create(
            model=Config.LLM_MODEL_NAME,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": fmt},
                    },
                    {
                        "type": "text",
                        "text": "Transcribe this audio accurately. Return only the transcription text, no commentary.",
                    },
                ],
            }],
        )
        content = response.choices[0].message.content
        # Strip <think> tags that some models inject
        import re
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    @classmethod
    def _transcribe_video(cls, file_path: str) -> str:
        """Extract audio from video container and transcribe, using PyAV (no system ffmpeg needed)."""
        import io
        # Convert to WAV in memory, write to a temp file so _transcribe_audio can open it
        wav_bytes = cls._to_wav_bytes(file_path)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name
        try:
            return cls._transcribe_audio(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @classmethod
    def extract_from_multiple(cls, file_paths: List[str]) -> str:
        """
        从多个文件提取文本并合并
        
        Args:
            file_paths: 文件路径列表
            
        Returns:
            合并后的文本
        """
        all_texts = []
        
        for i, file_path in enumerate(file_paths, 1):
            try:
                text = cls.extract_text(file_path)
                filename = Path(file_path).name
                all_texts.append(f"=== 文档 {i}: {filename} ===\n{text}")
            except Exception as e:
                all_texts.append(f"=== 文档 {i}: {file_path} (提取失败: {str(e)}) ===")
        
        return "\n\n".join(all_texts)


def split_text_into_chunks(
    text: str, 
    chunk_size: int = 500, 
    overlap: int = 50
) -> List[str]:
    """
    将文本分割成小块
    
    Args:
        text: 原始文本
        chunk_size: 每块的字符数
        overlap: 重叠字符数
        
    Returns:
        文本块列表
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # 尝试在句子边界处分割
        if end < len(text):
            # 查找最近的句子结束符
            for sep in ['。', '！', '？', '.\n', '!\n', '?\n', '\n\n', '. ', '! ', '? ']:
                last_sep = text[start:end].rfind(sep)
                if last_sep != -1 and last_sep > chunk_size * 0.3:
                    end = start + last_sep + len(sep)
                    break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # 下一个块从重叠位置开始
        start = end - overlap if end < len(text) else len(text)
    
    return chunks

