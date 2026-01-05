"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import os
import json
import re
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Literal, Union
from datetime import datetime
from threading import Lock
from openai import OpenAI

from ..config import Config, _normalize_openai_base_url
from .llm_settings import load_llm_settings, LLMSettings
from .openai_rotation import extract_error_info, should_rotate_model


logger = logging.getLogger(__name__)


class LLMEmptyResponseError(Exception):
    """LLM 返回空响应时抛出"""
    pass


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class LLMChatCompletion:
    content: Optional[str]
    tool_calls: List[LLMToolCall]


def _extract_json_from_response(text: str) -> str:
    """
    从响应中提取 JSON 内容。
    处理 markdown 代码块包裹的情况：```json ... ```
    """
    if not text:
        return text

    # 尝试提取 ```json ... ``` 或 ``` ... ``` 包裹的内容
    patterns = [
        r"```json\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            # 验证是否是有效 JSON
            try:
                json.loads(extracted)
                return extracted
            except json.JSONDecodeError:
                continue

    return text.strip()


class LLMClient:
    """LLM客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        models: Optional[List[str]] = None,
        default_stage: str = "llm",
        usage_log_path: Optional[str] = None,
    ):
        self._settings = load_llm_settings()

        resolved_api_key = (api_key or self._settings.api_key or Config.LLM_API_KEY or "").strip()
        resolved_base_url = (base_url or self._settings.base_url or Config.LLM_BASE_URL or "").strip()
        if resolved_base_url:
            resolved_base_url = _normalize_openai_base_url(resolved_base_url)

        resolved_models: List[str] = []
        if models is not None:
            resolved_models = [str(m).strip() for m in models if str(m).strip()]
        elif model:
            resolved_models = [model.strip()]
        else:
            resolved_models = list(self._settings.models) if self._settings.models else []
            if not resolved_models:
                fallback_model = (Config.LLM_MODEL_NAME or "").strip()
                if fallback_model:
                    resolved_models = [fallback_model]

        if not resolved_api_key:
            raise ValueError("LLM_API_KEY 未配置")

        self.api_key = resolved_api_key
        self.base_url = resolved_base_url
        self.models = resolved_models[:10] if resolved_models else []
        self.model = self.models[0] if self.models else (model or Config.LLM_MODEL_NAME)
        self.default_stage = default_stage
        self._usage_log_path = usage_log_path
        self._usage_log_lock = Lock()

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def get_model_for_stage(self, stage: str) -> Optional[str]:
        """
        根据 stage 获取对应的模型。
        优先使用 model_routing 配置，否则返回 None（使用默认模型池）。

        注意：每次调用都会重新加载配置，确保能获取最新设置。
        """
        # 重新加载配置，确保使用最新的 model_routing
        fresh_settings = load_llm_settings()
        return fresh_settings.get_model_for_stage(stage)

    def _append_llm_usage(self, usage_log_path: Optional[str], record: Dict[str, Any]) -> None:
        path = usage_log_path or self._usage_log_path
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            with self._usage_log_lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def _create_chat_completion_with_rotation(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[Literal["auto", "none"], Dict[str, Any]]] = None,
        stage: str,
        usage_log_path: Optional[str],
    ):
        kwargs: Dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        # 根据 stage 获取对应模型，如果配置了则优先使用
        stage_model = self.get_model_for_stage(stage)
        if stage_model:
            # 使用 stage 指定的模型作为第一选择
            model_pool = [stage_model]
            # 如果该模型在 models 列表中，将其他模型作为备选
            other_models = [m for m in self.models if m != stage_model]
            model_pool.extend(other_models)
        else:
            model_pool = self.models or [self.model]

        last_error: Optional[BaseException] = None

        for idx, model_name in enumerate(model_pool):
            try:
                response = self.client.chat.completions.create(model=model_name, **kwargs)
                self._append_llm_usage(
                    usage_log_path,
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "success",
                        "stage": stage,
                        "model": model_name,
                        "usage": getattr(response, "usage", None).model_dump()
                        if getattr(response, "usage", None)
                        else None,
                    },
                )
                return response, model_name
            except Exception as e:
                rotate, reason = should_rotate_model(e)
                self._append_llm_usage(
                    usage_log_path,
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "error",
                        "stage": stage,
                        "model": model_name,
                        "rotate": bool(rotate),
                        "reason": reason,
                        "error": extract_error_info(e),
                    },
                )
                if rotate and idx < len(model_pool) - 1:
                    last_error = e
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("LLM调用失败：未配置可用模型")
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        *,
        stage: Optional[str] = None,
        usage_log_path: Optional[str] = None,
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
        response, _used_model = self._create_chat_completion_with_rotation(
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            stage=stage or self.default_stage,
            usage_log_path=usage_log_path,
        )
        return response.choices[0].message.content or ""

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[Literal["auto", "none"], Dict[str, Any]]] = None,
        stage: Optional[str] = None,
        usage_log_path: Optional[str] = None,
    ) -> LLMChatCompletion:
        """
        发送聊天请求，返回结构化结果（支持 OpenAI 原生 tools/function calling）。

        Notes:
        - 当模型选择调用工具时，`content` 可能为 None，工具调用在 `tool_calls` 中返回。
        """
        response, _used_model = self._create_chat_completion_with_rotation(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            stage=stage or self.default_stage,
            usage_log_path=usage_log_path,
        )
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
        max_tokens: int = 4096,
        *,
        stage: Optional[str] = None,
        usage_log_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            stage: 任务阶段，用于模型路由（默认 "json_structure"）

        Returns:
            解析后的JSON对象

        Raises:
            LLMEmptyResponseError: 当 LLM 返回空响应时
            json.JSONDecodeError: 当响应不是有效 JSON 时
        """
        # 默认使用 json_structure stage
        actual_stage = stage or "json_structure"

        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            stage=actual_stage,
            usage_log_path=usage_log_path,
        )

        # 检测空响应
        if not response or not response.strip():
            logger.warning(f"LLM 返回空响应 (stage={actual_stage})")
            raise LLMEmptyResponseError(f"LLM 返回空响应 (stage={actual_stage})")

        # 尝试提取 JSON（处理 markdown 包裹）
        json_text = _extract_json_from_response(response)

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}, 原始响应: {response[:200]}...")
            raise
