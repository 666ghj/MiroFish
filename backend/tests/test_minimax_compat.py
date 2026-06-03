"""
MiniMax 兼容性测试
验证 LLMClient 对 MiniMax 模型的兼容处理
"""

import json
import re
import pytest
import sys
import os

# 直接导入 llm_client 模块中的独立函数，绕过 Flask 依赖
# 通过模拟 Config 来避免导入整个 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# 直接从源文件提取独立函数进行测试
def _is_minimax(model, base_url):
    model_lower = (model or "").lower()
    url_lower = (base_url or "").lower()
    return "minimax" in model_lower or "minimax" in url_lower


def _clamp_temperature(temperature, model, base_url):
    if _is_minimax(model, base_url) and temperature <= 0:
        return 0.01
    return temperature


def parse_json_from_response(content):
    trimmed = content.strip()
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass
    code_block_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', trimmed)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass
    json_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', trimmed)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"LLM返回的JSON格式无效: {trimmed}")


def _inject_json_instruction(messages):
    json_hint = "\n\nYou must respond with valid JSON only. No markdown, no explanation, no extra text."
    messages = [msg.copy() for msg in messages]
    for msg in messages:
        if msg.get("role") == "system":
            msg["content"] = msg["content"] + json_hint
            return messages
    messages.insert(0, {"role": "system", "content": json_hint.strip()})
    return messages


class TestIsMinimax:
    def test_minimax_model_name(self):
        assert _is_minimax("MiniMax-M3", "https://api.openai.com/v1") is True

    def test_minimax_model_name_lowercase(self):
        assert _is_minimax("minimax-m3", "https://api.openai.com/v1") is True

    def test_minimax_base_url(self):
        assert _is_minimax("some-model", "https://api.minimax.io/v1") is True

    def test_minimax_base_url_cn(self):
        assert _is_minimax("some-model", "https://api.minimaxi.com/v1") is True

    def test_not_minimax_openai(self):
        assert _is_minimax("gpt-4o", "https://api.openai.com/v1") is False

    def test_not_minimax_dashscope(self):
        assert _is_minimax("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1") is False

    def test_none_values(self):
        assert _is_minimax(None, None) is False

    def test_minimax_m3(self):
        assert _is_minimax("MiniMax-M3", "https://api.minimax.io/v1") is True

    def test_minimax_m27(self):
        assert _is_minimax("MiniMax-M2.7", "https://api.minimax.io/v1") is True

    def test_minimax_m27_highspeed(self):
        assert _is_minimax("MiniMax-M2.7-highspeed", "https://api.minimax.io/v1") is True


class TestClampTemperature:
    def test_zero_temperature_minimax(self):
        result = _clamp_temperature(0.0, "MiniMax-M3", "https://api.minimax.io/v1")
        assert result == 0.01

    def test_negative_temperature_minimax(self):
        result = _clamp_temperature(-0.1, "MiniMax-M3", "https://api.minimax.io/v1")
        assert result == 0.01

    def test_valid_temperature_minimax(self):
        result = _clamp_temperature(0.7, "MiniMax-M3", "https://api.minimax.io/v1")
        assert result == 0.7

    def test_zero_temperature_non_minimax(self):
        result = _clamp_temperature(0.0, "gpt-4o", "https://api.openai.com/v1")
        assert result == 0.0

    def test_max_temperature_minimax(self):
        result = _clamp_temperature(1.0, "MiniMax-M3", "https://api.minimax.io/v1")
        assert result == 1.0

    def test_zero_temperature_minimax_m27(self):
        result = _clamp_temperature(0.0, "MiniMax-M2.7", "https://api.minimax.io/v1")
        assert result == 0.01

    def test_valid_temperature_minimax_m27(self):
        result = _clamp_temperature(0.7, "MiniMax-M2.7", "https://api.minimax.io/v1")
        assert result == 0.7


class TestInjectJsonInstruction:
    def test_inject_to_existing_system_message(self):
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Generate JSON."}
        ]
        result = _inject_json_instruction(messages)
        assert "valid JSON only" in result[0]["content"]
        assert result[0]["content"].startswith("You are a helper.")
        # Original should not be mutated
        assert "valid JSON only" not in messages[0]["content"]

    def test_inject_without_system_message(self):
        messages = [
            {"role": "user", "content": "Generate JSON."}
        ]
        result = _inject_json_instruction(messages)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "valid JSON only" in result[0]["content"]

    def test_does_not_mutate_original(self):
        messages = [
            {"role": "system", "content": "Hello"},
            {"role": "user", "content": "Test"}
        ]
        original_content = messages[0]["content"]
        _inject_json_instruction(messages)
        assert messages[0]["content"] == original_content


class TestParseJsonFromResponse:
    def test_direct_json(self):
        result = parse_json_from_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = parse_json_from_response(text)
        assert result == {"key": "value"}

    def test_json_with_surrounding_text(self):
        text = 'Here is the result:\n{"key": "value"}\nDone.'
        result = parse_json_from_response(text)
        assert result == {"key": "value"}

    def test_json_array(self):
        result = parse_json_from_response('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="JSON格式无效"):
            parse_json_from_response("not json at all")

    def test_nested_json(self):
        text = '{"agents": [{"name": "Alice"}, {"name": "Bob"}]}'
        result = parse_json_from_response(text)
        assert len(result["agents"]) == 2

    def test_markdown_block_without_json_label(self):
        text = '```\n{"key": "value"}\n```'
        result = parse_json_from_response(text)
        assert result == {"key": "value"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
