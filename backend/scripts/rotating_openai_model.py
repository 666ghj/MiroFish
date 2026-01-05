"""
Camel OpenAI model backend with ordered model rotation + disk usage logging.

Used by OASIS simulation scripts to:
- keep simulations running when a specific model quota is exhausted
- persist per-request usage to `llm_usage.jsonl` under the simulation folder
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from camel.models.openai_model import OpenAIModel
from camel.messages import OpenAIMessage
from camel.types import ChatCompletion, ChatCompletionChunk
from openai import AsyncStream, Stream

from app.utils.openai_rotation import extract_error_info, should_rotate_model


class RotatingOpenAIModel(OpenAIModel):
    def __init__(
        self,
        model_pool: List[str],
        *,
        usage_log_path: Optional[str] = None,
        stage: str = "oasis_simulation",
        **kwargs: Any,
    ) -> None:
        cleaned = [str(m).strip() for m in (model_pool or []) if str(m).strip()]
        self._model_pool = cleaned[:10]
        self._usage_log_path = usage_log_path
        self._stage = stage
        self._usage_log_lock = Lock()

        # Base class needs a model_type; we use the first as a default.
        super().__init__(model_type=(self._model_pool[0] if self._model_pool else "gpt-4o-mini"), **kwargs)

    def _append_usage(self, record: Dict[str, Any]) -> None:
        if not self._usage_log_path:
            return
        try:
            os.makedirs(os.path.dirname(self._usage_log_path), exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            with self._usage_log_lock:
                with open(self._usage_log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def _request_chat_completion(
        self,
        messages: List[OpenAIMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatCompletion | Stream[ChatCompletionChunk]:
        request_config = copy.deepcopy(self.model_config_dict)
        if tools:
            request_config["tools"] = tools
        request_config = self._sanitize_config(request_config)

        model_pool = self._model_pool or [str(self.model_type)]
        last_error: Optional[BaseException] = None

        for idx, model_name in enumerate(model_pool):
            try:
                response = self._client.chat.completions.create(
                    messages=messages,
                    model=model_name,
                    **request_config,
                )
                self._append_usage(
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "success",
                        "stage": self._stage,
                        "model": model_name,
                        "usage": getattr(response, "usage", None).model_dump()
                        if getattr(response, "usage", None)
                        else None,
                    }
                )
                return response
            except Exception as e:
                rotate, reason = should_rotate_model(e)
                self._append_usage(
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "error",
                        "stage": self._stage,
                        "model": model_name,
                        "rotate": bool(rotate),
                        "reason": reason,
                        "error": extract_error_info(e),
                    }
                )
                if rotate and idx < len(model_pool) - 1:
                    last_error = e
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("LLM调用失败：未配置可用模型")

    async def _arequest_chat_completion(
        self,
        messages: List[OpenAIMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatCompletion | AsyncStream[ChatCompletionChunk]:
        request_config = copy.deepcopy(self.model_config_dict)
        if tools:
            request_config["tools"] = tools
        request_config = self._sanitize_config(request_config)

        model_pool = self._model_pool or [str(self.model_type)]
        last_error: Optional[BaseException] = None

        for idx, model_name in enumerate(model_pool):
            try:
                response = await self._async_client.chat.completions.create(
                    messages=messages,
                    model=model_name,
                    **request_config,
                )
                self._append_usage(
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "success",
                        "stage": self._stage,
                        "model": model_name,
                        "usage": getattr(response, "usage", None).model_dump()
                        if getattr(response, "usage", None)
                        else None,
                    }
                )
                return response
            except Exception as e:
                rotate, reason = should_rotate_model(e)
                self._append_usage(
                    {
                        "ts": datetime.now().isoformat(),
                        "event": "error",
                        "stage": self._stage,
                        "model": model_name,
                        "rotate": bool(rotate),
                        "reason": reason,
                        "error": extract_error_info(e),
                    }
                )
                if rotate and idx < len(model_pool) - 1:
                    last_error = e
                    continue
                raise

        if last_error:
            raise last_error
        raise RuntimeError("LLM调用失败：未配置可用模型")

