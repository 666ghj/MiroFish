# ChatGPT OAuth 页面登录 Implementation Plan

**Goal:** 在模型配置页完成 Direct OAuth Device Code 登录、状态轮询和登出，同时保持 Token 仅由 Gateway 管理。

**Spec:** `docs/superpowers/specs/2026-08-28-chatgpt-oauth-ui-design.md`

1. 为 Direct Gateway 写登录会话状态机和 API 失败测试，覆盖成功、过期、取消和脱敏。
2. 实现后台轮询、单活跃会话和 `/oauth/device/*`、`/oauth/logout` 接口。
3. 为 Backend 增加只传安全字段的 OAuth 代理 Blueprint。
4. 在模型设置页为 OAuth 类型连接增加登录、代码展示、状态轮询和登出。
5. 运行 Gateway/Backend 测试、前端构建并用本地 Docker 做浏览器验证。
