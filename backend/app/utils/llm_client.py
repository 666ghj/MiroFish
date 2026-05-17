"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config

logger = logging.getLogger(__name__)


def _parse_llm_json(response: str) -> Dict[str, Any]:
    """
    Robuster JSON-Parser für LLM-Outputs.

    LLMs (besonders qwen, gemma, ollama-Modelle) hängen oft Trailing-Text
    nach dem JSON an, auch mit response_format=json_object. Außerdem werden
    JSON-Blöcke häufig in ```json ... ``` Markdown-Fences gewrappt.

    Strategie:
    1. Markdown-Fences entfernen
    2. json.loads (strict, schnellster Weg)
    3. raw_decode (parsed Prefix, ignoriert Trailing-Text)
    4. Balanced-Brace-Extraktion (sucht erste vollständige {...} Struktur)
    5. Strip Control-Chars + Retry
    Bei allen Fehlern: ValueError mit hilfreichem Snippet.

    Fixes:
    - github.com/666ghj/MiroFish#624 ("Unexpected non-whitespace character after JSON at position N")
    - github.com/666ghj/MiroFish#622 (duplikat)
    - github.com/666ghj/MiroFish#601 (500 error on ontology/generate mit qwen-plus/ollama)
    """
    if not response or not response.strip():
        raise ValueError("LLM lieferte leere Antwort")

    # 1. Strip Markdown-Fences
    cleaned = response.strip()
    cleaned = re.sub(r'^```(?:json|JSON)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)
    cleaned = cleaned.strip()

    # 2. Schneller Pfad: vollständiges JSON
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e_strict:
        first_error = e_strict

    # 3. raw_decode — parsed JSON-Prefix, ignoriert Trailing-Text
    try:
        decoder = json.JSONDecoder()
        obj, end_idx = decoder.raw_decode(cleaned)
        trailing = cleaned[end_idx:].strip()
        if trailing:
            logger.warning(
                "LLM appended trailing text after JSON (%d chars), ignored. Preview: %s",
                len(trailing), trailing[:120]
            )
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            # Wrap in dict für Konsistenz mit chat_json-Erwartung
            return {"items": obj}
    except json.JSONDecodeError:
        pass

    # 4. Balanced-Brace-Extraktion: find first complete {...}
    start = cleaned.find('{')
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:i + 1]
                    try:
                        result = json.loads(candidate)
                        logger.warning(
                            "Extracted JSON from messy LLM output (%d chars before, %d after)",
                            start, len(cleaned) - (i + 1)
                        )
                        return result
                    except json.JSONDecodeError:
                        break

    # 5. Letzter Versuch: control chars entfernen + retry
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
    if sanitized != cleaned:
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            pass

    # Alle Strategien fehlgeschlagen — sprechende Fehlermeldung
    snippet = cleaned[:200] + ('...' if len(cleaned) > 200 else '')
    raise ValueError(
        f"LLM返回的JSON格式无效 (alle Parse-Strategien fehlgeschlagen): "
        f"first_error={first_error.msg} at pos {first_error.pos}. "
        f"Response-Preview: {snippet}"
    )


class LLMClient:
    """LLM客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）
            
        Returns:
            模型响应文本
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            kwargs["response_format"] = response_format
        
        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        return _parse_llm_json(response)

