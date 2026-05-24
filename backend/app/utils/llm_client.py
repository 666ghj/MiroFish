"""
Lớp bao bọc LLM client
Thống nhất gọi theo định dạng OpenAI
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config
from .llm_cost import create_tracked_chat_completion


class LLMClient:
    """LLM client"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        component: str = "llm_client",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        self.component = component
        self.default_metadata = metadata or {}
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY is not configured")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 16000,
        response_format: Optional[Dict] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Gửi yêu cầu chat

        Args:
            messages: Danh sách message
            temperature: Tham số nhiệt độ
            max_tokens: Số token tối đa
            response_format: Định dạng response (ví dụ JSON mode)

        Returns:
            Nội dung response từ model
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            kwargs["response_format"] = response_format

        call_metadata = dict(self.default_metadata)
        if metadata:
            call_metadata.update(metadata)
        call_metadata.setdefault("component", self.component)
        
        response = create_tracked_chat_completion(
            client=self.client,
            model=self.model,
            messages=messages,
            metadata=call_metadata,
            **{k: v for k, v in kwargs.items() if k not in {"model", "messages"}},
        )
        content = response.choices[0].message.content or ""
        # Một số model (vd MiniMax M2.5) chèn nội dung <think> vào content, cần loại bỏ
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 50000,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Gửi yêu cầu chat và trả về JSON

        Args:
            messages: Danh sách message
            temperature: Tham số nhiệt độ
            max_tokens: Số token tối đa

        Returns:
            JSON object sau khi parse
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            metadata=metadata,
        )
        # Làm sạch markdown code fence
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned invalid JSON: {cleaned_response}")

