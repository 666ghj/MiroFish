"""
LLM客户端封装
支持 OpenAI 和 Anthropic SDK
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

from ..config import Config


class LLMClient:
    """LLM客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.provider = Config.LLM_PROVIDER
        
        if self.provider == 'anthropic':
            self.api_key = api_key or Config.ANTHROPIC_API_KEY
            self.base_url = base_url or Config.ANTHROPIC_BASE_URL
            self.model = model or Config.ANTHROPIC_MODEL_NAME
            
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY 未配置")
            
            if Anthropic is None:
                raise ImportError("Anthropic SDK 未安装，请运行 pip install anthropic")
                
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
                
            self.client = Anthropic(**client_kwargs)
        else:
            # 默认为 OpenAI
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
            response_format: 响应格式（如JSON模式，仅OpenAI支持）
            
        Returns:
            模型响应文本
        """
        if self.provider == 'anthropic':
            # Anthropic 适配
            system_prompt = None
            filtered_messages = []
            
            for msg in messages:
                if msg['role'] == 'system':
                    system_prompt = msg['content']
                else:
                    filtered_messages.append(msg)
            
            kwargs = {
                "model": self.model,
                "messages": filtered_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            if system_prompt:
                kwargs["system"] = system_prompt
                
            response = self.client.messages.create(**kwargs)
            return response.content[0].text
            
        else:
            # OpenAI 调用
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            
            if response_format:
                kwargs["response_format"] = response_format
            
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
    
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
        if self.provider == 'anthropic':
            # Anthropic 不支持直接的 json_object 模式，通过 Prompt 引导
            # 复制消息列表以避免修改原列表
            new_messages = [msg.copy() for msg in messages]
            
            # 检查是否有 system prompt
            has_system = False
            for msg in new_messages:
                if msg['role'] == 'system':
                    msg['content'] += "\n\nPlease output valid JSON only."
                    has_system = True
                    break
            
            if not has_system:
                new_messages.insert(0, {
                    "role": "system", 
                    "content": "You are a helpful assistant. Please output valid JSON only."
                })
            
            response_text = self.chat(
                messages=new_messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            try:
                # 尝试提取 JSON 内容 (处理可能存在的 Markdown 代码块)
                clean_text = response_text.strip()
                if "```json" in clean_text:
                    pattern = r"```json(.*?)```"
                    match = re.search(pattern, clean_text, re.DOTALL)
                    if match:
                        clean_text = match.group(1).strip()
                elif "```" in clean_text:
                    pattern = r"```(.*?)```"
                    match = re.search(pattern, clean_text, re.DOTALL)
                    if match:
                        clean_text = match.group(1).strip()
                        
                return json.loads(clean_text)
            except json.JSONDecodeError as e:
                print(f"JSON Parse Error: {e}, Response: {response_text}")
                # 尝试简单的修复或直接返回错误结构
                return {"error": "Invalid JSON response", "raw_content": response_text}
                
        else:
            # OpenAI 原生 JSON 模式
            response = self.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response)
