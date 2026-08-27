# Direct OAuth Provider（实验性）

该旁路服务使用独立的 ChatGPT Device Code OAuth 凭据调用 Codex Responses 后端，仅供 Graphiti 建图使用。它不读取官方 Codex Gateway 的认证卷，也不向宿主机映射端口。

登录：

```bash
docker compose -f docker-compose.production.yml run --rm direct-oauth-gateway .venv/bin/python -m app.login login
```

状态与退出：

```bash
docker compose -f docker-compose.production.yml run --rm direct-oauth-gateway .venv/bin/python -m app.login status
docker compose -f docker-compose.production.yml run --rm direct-oauth-gateway .venv/bin/python -m app.login logout
```

回滚时删除或注释 `GRAPHITI_LLM_*`，Graphiti 会恢复读取 `OPENAI_*`；可停止旁路容器并保留凭据卷。
