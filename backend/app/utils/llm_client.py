"""
LLM客户端封装
统一使用OpenAI格式调用，兼容 MiniMax 等 OpenAI 兼容 API
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config


def _is_minimax(model: str, base_url: str) -> bool:
    """检测当前是否使用 MiniMax 模型"""
    model_lower = (model or "").lower()
    url_lower = (base_url or "").lower()
    return "minimax" in model_lower or "minimax" in url_lower


def _clamp_temperature(temperature: float, model: str, base_url: str) -> float:
    """MiniMax 要求 temperature 在 (0.0, 1.0] 之间，不能为 0"""
    if _is_minimax(model, base_url) and temperature <= 0:
        return 0.01
    return temperature


def parse_json_from_response(content: str) -> Any:
    """从 LLM 响应中解析 JSON，支持多种格式"""
    trimmed = content.strip()

    # 1. 直接解析
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass

    # 2. 提取 markdown code block
    code_block_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', trimmed)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 提取 { } 或 [ ]
    json_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', trimmed)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"LLM返回的JSON格式无效: {trimmed}")


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

    @property
    def is_minimax(self) -> bool:
        """检测当前是否使用 MiniMax 模型"""
        return _is_minimax(self.model, self.base_url)

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
        temperature = _clamp_temperature(temperature, self.model, self.base_url)

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # MiniMax 不支持 response_format，改用 prompt 引导 JSON 输出
        if response_format and self.is_minimax:
            messages = _inject_json_instruction(messages)
        elif response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # 部分模型（如MiniMax M3 等推理型模型）会在content中包含<think>思考内容，需要移除
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
        return parse_json_from_response(response)


def _inject_json_instruction(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """在消息列表中注入 JSON 输出指令（用于不支持 response_format 的模型）"""
    json_hint = "\n\nYou must respond with valid JSON only. No markdown, no explanation, no extra text."
    messages = [msg.copy() for msg in messages]
    # 优先追加到 system 消息
    for msg in messages:
        if msg.get("role") == "system":
            msg["content"] = msg["content"] + json_hint
            return messages
    # 如果没有 system 消息，在开头插入一条
    messages.insert(0, {"role": "system", "content": json_hint.strip()})
    return messages

