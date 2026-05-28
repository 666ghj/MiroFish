"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI, BadRequestError, APIError

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
        self.default_max_tokens = Config.LLM_MAX_TOKENS

        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    @staticmethod
    def _trim_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        当消息列表过长导致上下文溢出时，裁剪中间的历史消息。
        保留第一条（system prompt）和最后几条消息，移除中间部分。
        """
        if len(messages) <= 4:
            return messages

        # 保留 system prompt（第1条）+ 最近3轮对话（最后6条）
        keep_tail = min(6, len(messages) - 1)
        trimmed = [messages[0]] + messages[-keep_tail:]
        logger.warning(
            f"消息上下文过长，已裁剪: {len(messages)} -> {len(trimmed)} 条消息"
        )
        return trimmed

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数（默认使用配置值）
            response_format: 响应格式（如JSON模式）

        Returns:
            模型响应文本
        """
        if max_tokens is None:
            max_tokens = self.default_max_tokens

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        try:
            response = self.client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            error_msg = str(e).lower()
            # 处理上下文长度超限错误：自动裁剪消息后重试一次
            if "context_length" in error_msg or "maximum context" in error_msg or "token" in error_msg:
                logger.warning(
                    f"上下文长度超限，尝试裁剪消息后重试: {e}"
                )
                trimmed_messages = self._trim_messages(messages)
                if len(trimmed_messages) == len(messages):
                    # 无法进一步裁剪，向上抛出
                    raise
                kwargs["messages"] = trimmed_messages
                response = self.client.chat.completions.create(**kwargs)
            else:
                raise
        except APIError as e:
            logger.error(f"LLM API 调用失败: {e}")
            raise

        content = response.choices[0].message.content
        # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数（默认使用配置值）

        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")
