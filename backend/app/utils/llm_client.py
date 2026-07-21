"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import time
import re
from typing import Optional, Dict, Any, List, Callable
from openai import OpenAI

from ..config import Config
from .logger import get_logger

logger = get_logger('mirofish.llm_client')


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
        max_tokens: Optional[int] = 4096,
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
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        
        if response_format:
            kwargs["response_format"] = response_format
        
        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return self._clean_response_text(content)

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = 4096,
        max_attempts: int = 1,
        temperature_step: float = 0.0,
        fallback_parser: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        retry_delay_seconds: float = 0.0
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
        last_error: Optional[Exception] = None
        last_response = ""

        for attempt in range(max_attempts):
            current_temperature = max(0.0, temperature - (attempt * temperature_step))

            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": current_temperature,
                    "response_format": {"type": "json_object"}
                }

                if max_tokens is not None:
                    kwargs["max_tokens"] = max_tokens

                response = self.client.chat.completions.create(**kwargs)
                raw_content = response.choices[0].message.content or ""
                finish_reason = response.choices[0].finish_reason

                cleaned_response = self._clean_response_text(raw_content)
                if finish_reason == 'length':
                    logger.warning(f"LLM输出被截断 (attempt {attempt + 1})")
                    cleaned_response = self._fix_truncated_json(cleaned_response)

                last_response = cleaned_response

                try:
                    return self._parse_json_response(cleaned_response)
                except json.JSONDecodeError as parse_error:
                    logger.warning(f"JSON解析失败 (attempt {attempt + 1}): {str(parse_error)[:80]}")

                    fixed = self._try_fix_json(cleaned_response)
                    if fixed is not None:
                        return fixed

                    if fallback_parser is not None:
                        fallback_result = fallback_parser(cleaned_response)
                        if fallback_result is not None:
                            return fallback_result

                    last_error = parse_error

            except Exception as exc:
                logger.warning(f"LLM调用失败 (attempt {attempt + 1}): {str(exc)[:80]}")
                last_error = exc

            if attempt < max_attempts - 1 and retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds * (attempt + 1))

        raise ValueError(f"LLM返回的JSON格式无效: {last_response}") from last_error

    def _clean_response_text(self, content: str) -> str:
        """清理模型响应中的思考内容和Markdown包裹。"""
        cleaned = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        return cleaned.strip()

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        return json.loads(content)

    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON内容。"""
        content = content.strip()

        # If the number of unescaped quotes is odd we are inside an open string.
        unescaped_quote_count = len(re.findall(r'(?<!\\)"', content))
        if unescaped_quote_count % 2 == 1:
            content += '"'

        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        content += ']' * open_brackets
        content += '}' * open_braces
        return content

    def _try_fix_json(self, content: str) -> Optional[Dict[str, Any]]:
        """尝试从近似JSON内容中恢复结构化对象。"""
        content = self._fix_truncated_json(content)
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            return None

        json_str = json_match.group()

        def fix_string_newlines(match: re.Match[str]) -> str:
            value = match.group(0)
            value = value.replace('\n', ' ').replace('\r', ' ')
            value = re.sub(r'\s+', ' ', value)
            return value

        json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
            json_str = re.sub(r'\s+', ' ', json_str)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                return None
