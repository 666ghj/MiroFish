"""
LLM client wrapper
Unified interface using the OpenAI-compatible API format
"""

import json
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs, urlunparse
from openai import OpenAI

from ..config import Config


def parse_azure_url(raw_url: str):
    """Strip /chat/completions or /embeddings suffix from Azure endpoint URLs.

    Azure Portal gives full URLs like:
      https://<resource>.cognitiveservices.azure.com/openai/deployments/<model>/chat/completions?api-version=...
    The OpenAI SDK expects a base_url and appends /chat/completions itself.

    Returns (clean_base_url, default_query_dict).
    """
    default_query: Dict[str, str] = {}
    if raw_url and ('/chat/completions' in raw_url or '/embeddings' in raw_url):
        parsed = urlparse(raw_url)
        qs = parse_qs(parsed.query)
        if 'api-version' in qs:
            default_query['api-version'] = qs['api-version'][0]
        clean_path = (parsed.path
                      .replace('/chat/completions', '')
                      .replace('/embeddings', '')
                      .rstrip('/'))
        raw_url = urlunparse(parsed._replace(path=clean_path, query=''))
    return raw_url, default_query


class LLMClient:
    """LLM client"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        raw_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY is not configured")

        # Google AI Studio OpenAI-compatible endpoint
        if (Config.LLM_PROVIDER or "").lower() == "gemini" and not base_url:
            raw_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

        raw_url, default_query = parse_azure_url(raw_url)

        self.base_url = raw_url
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_query=default_query if default_query else None
        )

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        Send a chat request

        Args:
            messages: List of messages
            temperature: Temperature parameter
            max_tokens: Maximum number of tokens
            response_format: Response format (e.g. JSON mode)

        Returns:
            Model response text
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # Some models (e.g. MiniMax M2.5) include <think> reasoning content in the response; strip it out
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Send a chat request and return parsed JSON

        Args:
            messages: List of messages
            temperature: Temperature parameter
            max_tokens: Maximum number of tokens

        Returns:
            Parsed JSON object
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # Strip markdown code-block markers if present
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON returned by LLM: {cleaned_response}")
