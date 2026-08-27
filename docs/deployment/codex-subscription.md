# ChatGPT 订阅 Codex Gateway

MiroFish 可通过内部 Codex Gateway 使用 ChatGPT Plus/Pro 订阅。Gateway 使用官方 `openai-codex` SDK和匹配版本的 Codex app-server runtime；DeepSeek在订阅认证或额度异常时自动回退。

## 安全边界

- Gateway仅在 Docker 内网暴露8080，不映射宿主机端口。
- OAuth凭据由 Codex保存到独立 Docker Volume，MiroFish不读取 Token。
- Embedding继续直连本地 TEI。
- 登录、状态和登出命令只在服务器终端执行。

## 登录

```bash
docker compose -f docker-compose.production.yml exec \
  codex-gateway .venv/bin/python -m app.login login
```

终端会显示 OpenAI官方验证地址和用户码。完成浏览器授权后，检查状态：

```bash
docker compose -f docker-compose.production.yml exec \
  codex-gateway .venv/bin/python -m app.login status
```

状态只显示是否已认证、脱敏邮箱和套餐，不显示 Token。

## 登出

```bash
docker compose -f docker-compose.production.yml exec \
  codex-gateway .venv/bin/python -m app.login logout
```

## 回滚

将文本 LLM配置恢复为 DeepSeek：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_NAME=deepseek-v4-flash
```

重建 backend后可停止 Gateway。不要删除 `codex_auth` volume，除非明确希望清除登录状态。
