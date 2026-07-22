"""
LLM客户端封装
支持OpenAI和Anthropic格式的API调用
"""

import json
import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config

# 尝试导入Anthropic SDK，如果不可用则设为None
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from anthropic import AnthropicFoundry
except ImportError:
    AnthropicFoundry = None


def _foundry_resource_from_endpoint(endpoint: str) -> str:
    """从 Foundry endpoint 提取 resource 名称。"""
    if not endpoint:
        raise ValueError("LLM_BASE_URL is empty")
    if "://" not in endpoint:
        return endpoint.strip()

    host = urlparse(endpoint).netloc
    m = re.match(r"([^.]+)\.services\.ai\.azure\.com$", host)
    if not m:
        raise ValueError(
            f"Could not parse Foundry resource from endpoint: {endpoint!r}. "
            "Expected https://<resource>.services.ai.azure.com/anthropic/"
        )
    return m.group(1)


class LLMClient:
    """LLM客户端 - 支持OpenAI和Anthropic格式"""
    
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
        
        # 检测是否是Anthropic格式的端点
        self.is_anthropic = "anthropic" in self.base_url.lower()
        
        if self.is_anthropic:
            # 使用Anthropic SDK
            if Anthropic is None:
                raise ImportError("Anthropic SDK未安装。请运行: pip install anthropic")
            is_foundry_endpoint = "services.ai.azure.com" in self.base_url.lower()
            if is_foundry_endpoint and AnthropicFoundry is not None:
                resource = _foundry_resource_from_endpoint(self.base_url)
                self.client = AnthropicFoundry(
                    api_key=self.api_key,
                    resource=resource,
                )
            else:
                self.client = Anthropic(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            self.client_type = "anthropic"
        else:
            # 使用OpenAI SDK
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            self.client_type = "openai"

    @staticmethod
    def _convert_messages_for_anthropic(messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """将 OpenAI 风格消息转换为 Anthropic Messages API 所需格式。"""
        system_parts: List[str] = []
        anthropic_messages: List[Dict[str, str]] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                if content:
                    system_parts.append(content)
                continue

            if role not in {"user", "assistant"}:
                role = "user"

            anthropic_messages.append({"role": role, "content": content})

        if not anthropic_messages:
            anthropic_messages = [{"role": "user", "content": ""}]

        result: Dict[str, Any] = {"messages": anthropic_messages}
        if system_parts:
            result["system"] = "\n\n".join(system_parts)
        return result
    
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
        if self.client_type == "anthropic":
            # 使用Anthropic SDK（system 需单独传递，messages 仅支持 user/assistant）
            converted = self._convert_messages_for_anthropic(messages)
            create_kwargs = {
                "model": self.model,
                "messages": converted["messages"],
                "system": converted.get("system"),
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            try:
                response = self.client.messages.create(**create_kwargs)
            except Exception as e:
                # 某些新模型会拒绝 temperature 参数（报错: temperature is deprecated）
                if "temperature" in str(e).lower() and "deprecated" in str(e).lower():
                    create_kwargs.pop("temperature", None)
                    response = self.client.messages.create(**create_kwargs)
                else:
                    raise
            content = response.content[0].text
        else:
            # 使用OpenAI SDK
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            
            if response_format:
                kwargs["response_format"] = response_format

            response = None
            for _ in range(3):
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    break
                except Exception as e:
                    err_text = str(e).lower()

                    # 某些模型（如部分 GPT-5 系列）不支持 max_tokens，仅支持 max_completion_tokens
                    if "unsupported parameter" in err_text and "max_tokens" in err_text and "max_tokens" in kwargs:
                        kwargs.pop("max_tokens", None)
                        kwargs["max_completion_tokens"] = max_tokens
                        continue

                    # 某些模型仅支持默认 temperature（通常是 1）
                    if "temperature" in err_text and (
                        "unsupported value" in err_text or "default (1) value" in err_text
                    ) and "temperature" in kwargs:
                        kwargs.pop("temperature", None)
                        continue

                    raise

            if response is None:
                raise RuntimeError("OpenAI chat completion failed after compatibility retries")
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
        if self.client_type == "anthropic":
            modified_messages = [dict(m) for m in messages]
            json_instruction = "IMPORTANT: You must respond with valid JSON only, no other text."
            system_index = next((i for i, m in enumerate(modified_messages) if m.get("role") == "system"), None)
            if system_index is None:
                modified_messages.insert(0, {"role": "system", "content": json_instruction})
            else:
                modified_messages[system_index]["content"] = (
                    f"{modified_messages[system_index].get('content', '')}\n\n{json_instruction}"
                )

            response_text = self.chat(
                messages=modified_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            # OpenAI格式：使用response_format
            response = self.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )
            response_text = response
        
        # 清理markdown代码块标记
        cleaned_response = response_text.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")

