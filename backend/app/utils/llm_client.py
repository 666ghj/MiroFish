"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config
from .llm_rate_limit import call_llm_with_rate_limit_retry


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
        
        # MiniMax 不支持 response_format 参数，跳过
        if response_format and "MiniMax" not in self.model and "minimax" not in self.model:
            kwargs["response_format"] = response_format
        
        response = call_llm_with_rate_limit_retry(
            lambda: self.client.chat.completions.create(**kwargs),
            operation_name="LLM chat"
        )
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
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        # 尝试直接解析
        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            pass

        # 策略2: 尝试提取 JSON 对象（可能嵌套在其他文本中）
        json_patterns = [
            r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # 简单嵌套
            r'(\{"[^"]*"\s*:\s*)',  # JSON 开始位置
        ]
        for pattern in json_patterns:
            match = re.search(pattern, cleaned_response, re.DOTALL)
            if match:
                try:
                    # 尝试从匹配位置开始解析
                    candidate = match.group(0) if match.group(0).startswith('{') else match.group(1)
                    # 向后扩展直到找到完整对象
                    for end in range(len(candidate), len(cleaned_response) + 1):
                        try:
                            result = json.loads(cleaned_response[match.start():end])
                            return result
                        except json.JSONDecodeError:
                            continue
                except Exception:
                    pass

        # 策略3: 尝试修复常见 JSON 问题
        fixed = cleaned_response
        # 移除控制字符
        fixed = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', fixed)
        # 修复单引号
        fixed = re.sub(r"'", '"', fixed)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 策略4: 查找 ```json ... ``` 块
        code_block_match = re.search(r'```json\s*\n?(.*?)\n?```', cleaned_response, re.DOTALL | re.IGNORECASE)
        if code_block_match:
            try:
                return json.loads(code_block_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response[:500]}")

