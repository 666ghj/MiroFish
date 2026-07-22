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

        # 部分网关（如本项目使用的本地 Next.js 网关）在请求非流式时仍会返回
        # SSE 流式响应（data: {...}\n\n[DONE]），导致 OpenAI SDK 无法解析、
        # content 为空并触发 500。这里统一以流式方式调用并手动拼装 SSE 文本，
        # 对标准非流式后端同样兼容（SDK 也会按流式迭代给出 delta）。
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": False}

        chunks = []
        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and getattr(delta, "content", None):
                chunks.append(delta.content)

        content = "".join(chunks)
        # 兜底：若流式拼装为空（极少数网关在 stream=False 时才返回完整 content），
        # 尝试回退到非流式调用
        if not content.strip():
            kwargs.pop("stream", None)
            kwargs.pop("stream_options", None)
            fallback = self.client.chat.completions.create(**kwargs)
            if fallback.choices and fallback.choices[0].message:
                content = fallback.choices[0].message.content or ""

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
        # 部分网关偶发返回空内容，重试几次以提升稳定性
        last_err = None
        for attempt in range(3):
            try:
                response = self.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"}
                )
                if response and response.strip():
                    break
                last_err = ValueError("LLM 返回空内容，正在重试...")
            except Exception as e:
                last_err = e
                logger.warning(f"chat_json 第 {attempt + 1} 次尝试失败: {e}")
        else:
            raise last_err or ValueError("LLM 返回空内容")
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            # 尝试从可能被截断的响应中提取第一个完整/近似完整的 JSON 对象
            extracted = _extract_first_json_object(cleaned_response)
            if extracted is not None:
                return extracted
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从文本中提取第一个 JSON 对象。

    当模型输出因 max_tokens 被截断、导致 JSON 不完整时，尝试找到第一个
    形如 { ... } 的（可能未闭合的）对象，并通过还原括号栈尽力补全后解析。
    若补全后仍失败，则从尾部逐字符裁剪（最多 256 字符）直到可解析。
    返回解析后的 dict，或无法解析时返回 None。
    """
    if not text:
        return None
    # 去掉可能的 BOM / 前后空白
    text = text.lstrip('\ufeff').strip()
    start = text.find('{')
    if start == -1:
        return None
    snippet = text[start:]

    def _try_close(s: str) -> Optional[Dict[str, Any]]:
        """尝试通过括号栈补全后再解析。"""
        stack: list[str] = []
        in_str = False
        escape = False
        for ch in s:
            if in_str:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in '{[':
                stack.append(ch)
            elif ch in '}]':
                if stack:
                    stack.pop()
        if not stack and not in_str:
            # 结构已完整闭合
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return None
        candidate = s
        if in_str:
            candidate += '"'
        candidate = candidate.rstrip()
        if candidate.endswith(',') or candidate.endswith(':'):
            candidate = candidate[:-1].rstrip()
        for opener in reversed(stack):
            candidate += '}' if opener == '{' else ']'
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    result = _try_close(snippet)
    if result is not None:
        return result

    # 兜底：从尾部逐字符裁剪（截断多发生在末尾），每次裁剪后都尝试补全括号再解析
    # 裁剪上限 256 字符已远超单次截断的影响范围
    for cut in range(1, min(257, len(snippet))):
        trimmed = snippet[:-cut]
        if not trimmed:
            break
        res = _try_close(trimmed)
        if res is not None:
            return res
    return None

