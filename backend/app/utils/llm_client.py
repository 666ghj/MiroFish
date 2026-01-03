"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Literal, Union
from openai import OpenAI

from ..config import Config


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class LLMChatCompletion:
    content: Optional[str]
    tool_calls: List[LLMToolCall]


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
        return response.choices[0].message.content or ""

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[Literal["auto", "none"], Dict[str, Any]]] = None,
    ) -> LLMChatCompletion:
        """
        发送聊天请求，返回结构化结果（支持 OpenAI 原生 tools/function calling）。

        Notes:
        - 当模型选择调用工具时，`content` 可能为 None，工具调用在 `tool_calls` 中返回。
        """
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        response = self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message

        tool_calls: List[LLMToolCall] = []
        if getattr(message, "tool_calls", None):
            for call in message.tool_calls:
                if getattr(call, "type", None) != "function" or not getattr(call, "function", None):
                    continue
                tool_calls.append(
                    LLMToolCall(
                        id=call.id,
                        name=call.function.name,
                        arguments_json=call.function.arguments or "{}",
                    )
                )

        return LLMChatCompletion(content=message.content, tool_calls=tool_calls)
    
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
        
        return json.loads(response)
