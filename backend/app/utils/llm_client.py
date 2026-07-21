"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
import time
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config
from .logger import get_logger
from .llm_gate import main_llm_slot

logger = get_logger('mirofish.llm')


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
        
        with main_llm_slot():
            response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        content = re.sub(r'^Thinking Process:[\s\S]*?(?=\{|\[)', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        max_retries: Optional[int] = None
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
        retries = Config.LLM_JSON_MAX_RETRIES if max_retries is None else max_retries
        last_error: Exception | None = None
        last_response = ""

        for attempt in range(retries + 1):
            attempt_messages = list(messages)
            if attempt > 0:
                attempt_messages.append({
                    "role": "user",
                    "content": (
                        "The previous answer was not valid JSON. Return exactly one valid JSON object. "
                        "Do not include markdown fences, explanation, comments, or thinking text."
                    )
                })

            try:
                response = self.chat(
                    messages=attempt_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"}
                )
                last_response = response
                parsed = self._parse_json_lenient(response)
                if parsed is not None:
                    if attempt > 0:
                        logger.info("LLM JSON recovered after retry %s/%s", attempt, retries)
                    return parsed

                last_error = ValueError("LLM returned unparsable JSON")
                logger.warning(
                    "LLM returned invalid JSON on attempt %s/%s: %s",
                    attempt + 1,
                    retries + 1,
                    self._cleanup_response(response)[:1000],
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM JSON call failed on attempt %s/%s: %s",
                    attempt + 1,
                    retries + 1,
                    str(exc)[:1000],
                )

            if attempt < retries:
                time.sleep(min(2.0, 0.5 * (attempt + 1)))

        cleaned = self._cleanup_response(last_response)
        if cleaned:
            logger.error("LLM returned invalid JSON after retries: %s", cleaned[:2000])
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned[:1000]}")
        raise last_error or ValueError("LLM JSON call failed")

    def _parse_json_lenient(self, text: str) -> Dict[str, Any] | None:
        cleaned = self._cleanup_response(text)
        candidates = [cleaned]

        for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", text or "", flags=re.IGNORECASE):
            candidates.append(self._cleanup_response(block))

        candidates.extend(self._balanced_json_objects(cleaned))

        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            candidates.append(cleaned[start:end + 1])

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            repaired = self._repair_json(candidate)
            try:
                parsed = json.loads(repaired)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                pass

        return None

    def _cleanup_response(self, text: str) -> str:
        cleaned = text or ""
        cleaned = cleaned.replace("\ufeff", "").replace("\u200b", "")
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned).strip()
        cleaned = re.sub(r"^Thinking Process:[\s\S]*?(?=\{|\[)", "", cleaned).strip()
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        return cleaned.strip()

    def _repair_json(self, text: str) -> str:
        repaired = text.strip()
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        repaired = re.sub(r"\bNone\b", "null", repaired)
        repaired = re.sub(r"\bTrue\b", "true", repaired)
        repaired = re.sub(r"\bFalse\b", "false", repaired)
        return repaired

    def _balanced_json_objects(self, text: str) -> List[str]:
        objects: List[str] = []
        start = None
        depth = 0
        in_string = False
        escape = False

        for index, char in enumerate(text or ""):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}" and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:index + 1])
                    start = None

        # Prefer larger objects first; noisy LLM text may contain small examples.
        return sorted(objects, key=len, reverse=True)
