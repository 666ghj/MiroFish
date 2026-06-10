"""
LLM client wrapper
Unified OpenAI-format invocation
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config


class LLMClient:
    """LLM client"""
    
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
            raise ValueError("LLM_API_KEY is not configured")
        
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
        Send a chat completion request
        
        Args:
            messages: message list
            temperature: sampling temperature
            max_tokens: max tokens
            response_format: response format（e.g. JSON mode）
            
        Returns:
            model response text
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
        # Some models (e.g. MiniMax M2.5) embed <think>...</think> reasoning in content — strip it
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 16384
    ) -> Dict[str, Any]:
        """
        Send a chat completion requestand parse the response as JSON

        Args:
            messages: message list
            temperature: sampling temperature
            max_tokens: max tokens (default 16384 — MiniMax M3 in ontology / config
                long-JSON mode — 4096 tokens frequently truncates the JSON in the middle)

        Returns:
            parsed JSON object
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # Strip markdown code-block fences
        # MiniMax M3 ignores response_format=json_object and wraps JSON in
        # markdown fences. Be aggressive about stripping them, including the
        # ```json\n and trailing ``` even when surrounded by other content.
        cleaned_response = response.strip()
        # Strip a leading ``` (with optional language tag and newline)
        cleaned_response = re.sub(r'^```(?:json|JSON)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        # Strip a trailing ``` (with optional preceding newline)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        # If there's still a ```json or ``` anywhere, take the first JSON-looking
        # block from the response.
        if '```' in cleaned_response:
            m = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', cleaned_response)
            if m:
                cleaned_response = m.group(1)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned invalid JSON: {cleaned_response[:200]}")

