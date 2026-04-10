"""
LLM客户端封装
Supports two backends:
  1. Prompture (optional) — 12+ providers: LM Studio, Ollama, Claude, Groq, Kimi, etc.
  2. OpenAI SDK (default fallback) — any OpenAI-compatible API
Install Prompture for multi-provider support: pip install prompture
"""

import json
import re
from typing import Optional, Dict, Any, List

from ..config import Config

# Try to import Prompture; fall back to OpenAI SDK if not installed
try:
    from prompture.agents import Conversation
    from prompture.infra.provider_env import ProviderEnvironment
    from prompture.extraction.tools import strip_think_tags, clean_json_text
    _HAS_PROMPTURE = True
except ImportError:
    _HAS_PROMPTURE = False

if not _HAS_PROMPTURE:
    from openai import OpenAI


# Provider name → ProviderEnvironment field name
_KEY_MAP = {
    "openai": "openai_api_key",
    "claude": "claude_api_key",
    "google": "google_api_key",
    "groq": "groq_api_key",
    "grok": "grok_api_key",
    "openrouter": "openrouter_api_key",
    "moonshot": "moonshot_api_key",
}


class LLMClient:
    """LLM客户端

    When Prompture is installed, ``model`` accepts the ``"provider/model"``
    format for multi-provider support::

        "lmstudio/local-model"        → LM Studio (free, local)
        "ollama/llama3.1:8b"          → Ollama (free, local)
        "openai/gpt-4o"               → OpenAI
        "claude/claude-sonnet-4-20250514"     → Anthropic
        "moonshot/moonshot-v1-8k"     → Kimi / Moonshot
        "groq/llama-3.1-70b"          → Groq

    Without Prompture, the original OpenAI SDK backend is used (any
    OpenAI-compatible API via LLM_BASE_URL).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if _HAS_PROMPTURE:
            self._init_prompture()
        else:
            self._init_openai()

    # ── Prompture backend ──────────────────────────────────────────

    def _init_prompture(self):
        env_kwargs: Dict[str, Any] = {}
        if self.api_key:
            provider = self.model.split("/")[0] if "/" in self.model else "openai"
            env_field = _KEY_MAP.get(provider)
            if env_field:
                env_kwargs[env_field] = self.api_key

        self._env = ProviderEnvironment(**env_kwargs) if env_kwargs else None
        self._driver_options: Dict[str, Any] = {}
        if self.base_url:
            self._driver_options["base_url"] = self.base_url

    def _make_conversation(self, temperature: float, max_tokens: int) -> "Conversation":
        opts: Dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self._driver_options,
        }
        return Conversation(self.model, options=opts, env=self._env)

    # ── OpenAI fallback backend ────────────────────────────────────

    def _init_openai(self):
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    # ── Public API ─────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
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
        if _HAS_PROMPTURE:
            content = self._chat_prompture(messages, temperature, max_tokens)
            return strip_think_tags(content)
        else:
            content = self._chat_openai(messages, temperature, max_tokens, response_format)
            # Fallback: strip think tags with regex when Prompture is not available
            return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
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
        if _HAS_PROMPTURE:
            response = self._chat_prompture(messages, temperature, max_tokens)
            # Prompture's clean_json_text strips think tags + markdown fences
            cleaned = clean_json_text(response)
        else:
            response = self._chat_openai(
                messages, temperature, max_tokens
            )
            # Fallback cleaning when Prompture is not available
            cleaned = re.sub(r'<think>[\s\S]*?</think>', '', response).strip()
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\n?```\s*$', '', cleaned)
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned}")

    # ── Private: Prompture path ────────────────────────────────────

    def _chat_prompture(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        conv = self._make_conversation(temperature, max_tokens)

        # Inject system prompt
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        if system_parts:
            conv._messages.append({"role": "system", "content": "\n".join(system_parts)})

        # Replay prior turns
        non_system = [m for m in messages if m["role"] != "system"]
        for msg in non_system[:-1]:
            conv._messages.append({"role": msg["role"], "content": msg["content"]})

        prompt = non_system[-1]["content"] if non_system else ""
        return conv.ask(prompt)

    # ── Private: OpenAI fallback path ──────────────────────────────

    def _chat_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None,
    ) -> str:
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
