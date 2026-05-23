"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config


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
    
    def _stub_key(self, messages: list[dict]) -> str:
        user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        # Allow callers to embed an explicit stub_key=... token
        for chunk in user_msg.split():
            if chunk.startswith("stub_key="):
                return chunk[len("stub_key="):]
        import hashlib
        return hashlib.sha256((sys_msg + "|" + user_msg).encode("utf-8")).hexdigest()[:12]

    def _stub_response(self, messages: list[dict]) -> str:
        import json as _json
        return _json.dumps(self._stub_response_json(messages), ensure_ascii=False)

    def _stub_response_json(self, messages: list[dict]) -> dict:
        import hashlib, json as _json
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        usr_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        h = hashlib.sha256((sys_msg + "|" + usr_msg).encode("utf-8")).hexdigest()
        seed = int(h[:8], 16)
        rng = (seed % 5) + 1

        # Longitudinal Likert (12 items)
        if all(tok in usr_msg for tok in ("stk_1", "gov_1", "mkt_1", "clm_1")):
            ids = ["stk_1","stk_2","stk_3","gov_1","gov_2","gov_3",
                   "mkt_1","mkt_2","mkt_3","clm_1","clm_2","clm_3"]
            return {"responses": {k: ((seed >> (i*3)) % 5) + 1 for i, k in enumerate(ids)},
                    "confidence": {k: 0.6 for k in ids},
                    "open_comment": f"stub:{h[:8]}"}

        # Diversity Q-sort: 24 statements + 6 axes, forced distribution 2,3,4,6,4,3,2
        if "st_01" in usr_msg and "ax_pres_extr" in usr_msg:
            buckets = [-3]*2 + [-2]*3 + [-1]*4 + [0]*6 + [1]*4 + [2]*3 + [3]*2
            stmts = [f"st_{i+1:02d}" for i in range(24)]
            # shuffle deterministically
            order = sorted(range(24), key=lambda i: (h[i % len(h)], i))
            placements = {stmts[i]: buckets[order.index(i)] for i in range(24)}
            return {
                "placements": placements,
                "likert_axes": {a: ((seed >> (j*3)) % 7) + 1 for j, a in enumerate(
                    ["ax_pres_extr","ax_loc_eu","ax_sci_trad",
                     "ax_ind_col","ax_short_long","ax_mkt_reg"])},
            }

        # Scenario: S1..S4 × 4 dims
        if all(s in usr_msg for s in ("S1:", "S2:", "S3:", "S4:")):
            return {"ratings": {sid: {
                "desirability": ((seed >> (i*3)) % 7) + 1,
                "plausibility": ((seed >> (i*3+1)) % 7) + 1,
                "impact_on_my_group": ((seed >> (i*3+2)) % 7) + 1,
                "fairness": ((seed >> (i*3+4)) % 7) + 1,
                "if_woke_up_response": f"act-{sid}-{h[:4]}",
            } for i, sid in enumerate(["S1","S2","S3","S4"])}}

        # Delphi R1: q1..q4 free text
        if "q1" in usr_msg and "q2" in usr_msg and "Bewerten" not in usr_msg and "Sie sehen" not in usr_msg:
            return {"answers": {qid: f"stub-themes-{qid}-{h[:4]}" for qid in ("q1","q2","q3","q4")}}

        # Delphi theme extraction (no in-character system prompt)
        if "extract distinct thematic codes" in sys_msg:
            return {"themes": [{"theme_id": f"theme_{i}", "label": f"Thema {i}"} for i in range(5)]}

        # Delphi R2 (rate) or R3 (revise)
        if "Bewerten Sie jedes Thema" in usr_msg or "Sie sehen unten" in usr_msg \
           or "Rate each theme" in usr_msg or "Below are the anonymised" in usr_msg:
            theme_ids = [f"theme_{i}" for i in range(5)]
            out = {"ratings": {tid: {"importance": ((seed >> (i*2)) % 5) + 1,
                                     "plausibility": ((seed >> (i*2+1)) % 5) + 1}
                               for i, tid in enumerate(theme_ids)}}
            if "Sie sehen unten" in usr_msg or "Below are the anonymised" in usr_msg:
                out["justification"] = "stub-revision"
            return out

        # Fallback
        return {"stub_key": h[:12], "value": rng}

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
        from app.config import Config
        if getattr(Config, "LLM_STUB_MODE", False):
            return self._stub_response(messages)

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
        from app.config import Config
        if getattr(Config, "LLM_STUB_MODE", False):
            return self._stub_response_json(messages)

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

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")

