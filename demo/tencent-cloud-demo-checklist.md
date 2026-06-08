# Foresight 现场 Demo 腾讯云部署检查

用途：保证「先见之明」可被远程浏览器打开，并能稳定进入宁波银行缓存回放案例。

## 本地检查

```bash
cd "/Users/liyizhouai/Desktop/openclaw/vibe coding/Foresight先见之明"
npm run backend
cd frontend && npm run dev -- --host 0.0.0.0 --port 4190
```

检查：

- 首页：http://localhost:4190/
- 同域 API：http://localhost:4190/api/simulation/history?limit=1
- 回放页：http://localhost:4190/simulation/sim_nb_hnw_ai_case/replay

## 腾讯云双域名部署

如果继续使用：

- 前端：https://foresight.yizhou.chat
- 后端：https://api.foresight.yizhou.chat

前端构建必须显式指定 API 地址：

```bash
cd frontend
VITE_API_BASE_URL=https://api.foresight.yizhou.chat npm run build
```

否则默认会走同域 `/api`。

## 腾讯云同域部署

如果希望远程讲课时只打开一个域名，推荐 Nginx 规则：

```nginx
location / {
    try_files $uri $uri/ /index.html;
}

location /api/ {
    proxy_pass http://127.0.0.1:5001/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

同域部署时，前端无需设置 `VITE_API_BASE_URL`。

## 现场必验路径

1. 打开首页，滚动到「推演记录」。
2. 点击「宁波银行高净值客户AI理财组合推介」卡片。
3. 页面保持在首页，并弹出历史项目回溯弹窗。
4. 弹窗里确认四个入口都可见：`查看回放`、`图谱构建`、`环境搭建`、`分析报告`。
5. `图谱构建` 进入 `/process/proj_nb_hnw_ai_case`。
6. `环境搭建` 进入 `/simulation/sim_nb_hnw_ai_case`。
7. `分析报告` 进入 `/report/report_nb_hnw_ai_case`。
8. `查看回放` 可作为补充入口进入 `/simulation/sim_nb_hnw_ai_case/replay`。

## 关键稳定性说明

- 缓存回放案例不触发 ReportAgent 生成。
- 缓存回放案例不依赖远端 Neo4j/Bolt。
- 宁波银行案例的项目、图谱、环境配置和报告日志都由后端内置缓存提供，腾讯云部署时不依赖 `uploads/` 目录同步。
- 默认 API 已改为同域访问；双域名部署时用 `VITE_API_BASE_URL` 覆盖。
