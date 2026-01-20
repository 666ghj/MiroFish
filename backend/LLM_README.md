# LLM Client 配置与使用指南

本项目后端支持 **OpenAI** 和 **Anthropic (Claude)** 两种主流 LLM 提供商。可以根据需求在配置文件中灵活切换。

## 1. 依赖安装

项目使用 `uv` 进行依赖管理。如果您尚未安装 `anthropic` SDK，请运行以下命令：

```bash
cd backend
# 如果需要使用代理 (例如本地 7897 端口)
export https_proxy=http://127.0.0.1:7897 http_proxy=http://127.0.0.1:7897

# 添加依赖
uv add anthropic
```

## 2. 环境配置 (.env)

在项目根目录的 `.env` 文件中，通过设置 `LLM_PROVIDER` 来切换后端。

### 选项 A: 使用 OpenAI (默认)

```ini
# 指定提供商 (可省略，默认为 openai)
LLM_PROVIDER=openai

# OpenAI 配置
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1  # 可选，支持第三方转发
LLM_MODEL_NAME=gpt-5              # 可选
```

### 选项 B: 使用 Anthropic (Claude)

```ini
# 指定提供商
LLM_PROVIDER=anthropic

# Anthropic 配置
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_MODEL_NAME=claude-3-7-sonnet  # 可选
```

## 3. 代码使用示例

`LLMClient` 封装了底层的调用差异，对外提供统一的接口。

```python
from app.utils.llm_client import LLMClient

# 初始化客户端 (自动读取 Config 配置)
client = LLMClient()

# 1. 普通对话
messages = [
    {"role": "system", "content": "你是一个有用的助手。"},
    {"role": "user", "content": "你好，请介绍一下自己。"}
]
response = client.chat(messages)
print(response)

# 2. JSON 模式
# 注意：对于 Claude，我们会自动在 Prompt 中注入 JSON 格式要求，并尝试解析返回的 Markdown 代码块
json_messages = [
    {"role": "user", "content": "生成一个包含 name 和 age 的 JSON 对象"}
]
json_response = client.chat_json(json_messages)
print(json_response)
# 输出: {'name': 'Example', 'age': 30}
```

## 4. 注意事项

- **JSON 模式差异**：
    - **OpenAI**: 使用原生 `response_format={"type": "json_object"}`，非常稳定。
    - **Anthropic**: 通过 System Prompt 注入 `"Please output valid JSON only."` 并解析返回文本中的 JSON。虽然 Claude 模型遵循指令能力很强，但在极端情况下仍可能输出非 JSON 内容，客户端已包含基本的 Markdown 清洗逻辑。
- **System Prompt**：
    - 代码会自动提取 `messages` 列表中 `role="system"` 的消息，并将其正确适配到 OpenAI 的 `messages` 列表或 Anthropic 的顶层 `system` 参数中。
