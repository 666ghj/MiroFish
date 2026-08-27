# 历史记录中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加跨后端重启保留的全部后台任务历史，并提供可从首页进入的项目/任务历史页面。

**Architecture:** `TaskStore` 负责 JSON 反序列化和原子写入，`TaskManager` 保持现有内存 API 并在每次状态变化后同步存储。前端新增独立历史页面，通过现有项目接口和增强后的任务接口加载数据，不引入数据库或新的服务依赖。

**Tech Stack:** Python 3.11、Flask、pytest、Vue 3、Vue Router、Axios、Vite

**Spec:** `docs/superpowers/specs/2026-08-27-history-center-design.md`

## Global Constraints

- 只修改和验证本地代码，不连接、同步、重建或部署 ColoCrossing 服务器。
- 未经用户明确授权不得提交或推送 Git。
- 保持现有 `/api/graph/task/<task_id>` 和 `/api/graph/tasks` 响应字段兼容。
- 不增加 MySQL、Docker Volume 或新的前端依赖。
- 首版不支持删除历史、重跑任务或恢复中断任务。

---

### Task 1: 任务 SQLite 存储

**Files:**
- Create: `backend/app/models/task_store.py`
- Create: `backend/tests/test_task_store.py`

**Interfaces:**
- Produces: `TaskStore(path: str)`
- Produces: `TaskStore.load() -> list[dict]`
- Produces: `TaskStore.save(records: list[dict]) -> None`

- [ ] **Step 1: 写失败测试**

覆盖 SQLite 自动建表、WAL、索引、事务 UPSERT、JSON 字段解码、旧 JSON 迁移和损坏旧文件保留。

- [ ] **Step 2: 运行 RED**

Run: `python3 -m pytest backend/tests/test_task_store.py -v`

- [ ] **Step 3: 实现最小存储类**

使用标准库 `sqlite3`、WAL、busy timeout、事务 UPSERT 和索引；记录日志但不向调用者暴露路径。

- [ ] **Step 4: 运行 GREEN**

Run: `python3 -m pytest backend/tests/test_task_store.py -v`

### Task 2: TaskManager 持久化与中断状态

**Files:**
- Modify: `backend/app/models/task.py`
- Create: `backend/tests/test_task_persistence.py`

**Interfaces:**
- Adds: `TaskStatus.INTERRUPTED = "interrupted"`
- Preserves: `TaskManager.create_task/get_task/update_task/complete_task/fail_task/list_tasks/cleanup_old_tasks`
- Adds: `TaskManager.configure_store(path: str | None) -> None`，仅供启动配置和测试隔离。
- Changes: `list_tasks(task_type=None, status=None, limit=None) -> list[dict]`

- [ ] **Step 1: 写序列化和重启失败测试**

创建任务并更新后重新初始化 manager，断言 completed 保持、processing 转 interrupted，metadata 不丢失。

- [ ] **Step 2: 写过滤和清理失败测试**

断言 status、limit 生效，cleanup 后文件同步。

- [ ] **Step 3: 运行 RED**

Run: `python3 -m pytest backend/tests/test_task_persistence.py -v`

- [ ] **Step 4: 实现持久化管理**

默认路径为 `os.path.join(Config.UPLOAD_FOLDER, "tasks", "tasks.db")`；加载时逐条校验必需字段、ISO 时间与 JSON 列；每次变更调用事务保存。

- [ ] **Step 5: 运行 GREEN 和后端回归**

Run: `python3 -m pytest backend/tests/test_task_persistence.py backend/tests -v`

### Task 3: API 过滤与任务关联信息

**Files:**
- Modify: `backend/app/api/graph.py`
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/api/report.py`
- Modify: `backend/app/services/graph_builder.py`
- Create: `backend/tests/test_history_api_contract.py`

**Interfaces:**
- Consumes: `TaskManager.list_tasks(status, limit)`
- Produces: `GET /api/graph/tasks?status=<status>&limit=<n>`
- Produces metadata keys: `project_id`、`graph_id`、`simulation_id`、`report_id` when available.

- [ ] **Step 1: 写 API 失败测试**

断言非法 status 返回 400，limit 限制在 1..500，合法筛选传给 manager，响应结构保持 `success/data/count`。

- [ ] **Step 2: 运行 RED**

Run: `python3 -m pytest backend/tests/test_history_api_contract.py -v`

- [ ] **Step 3: 实现 API 与 metadata**

建图任务创建时写 `project_id`；其余调用点只加入当前作用域内已有 ID，不新增查询。

- [ ] **Step 4: 运行 GREEN 和后端回归**

Run: `python3 -m pytest backend/tests -v`

### Task 4: 历史记录页面与导航

**Files:**
- Create: `frontend/src/api/history.js`
- Create: `frontend/src/views/HistoryView.vue`
- Create: `frontend/src/components/HistoryProjectList.vue`
- Create: `frontend/src/components/HistoryTaskList.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/views/Home.vue`

**Interfaces:**
- Produces: `getHistoryProjects(limit = 50)`
- Produces: `getHistoryTasks({status, limit} = {})`
- Produces route: `/history`

- [ ] **Step 1: 实现 API 薄封装**

项目调用 `/api/graph/project/list`，任务调用 `/api/graph/tasks`，只传非空查询参数。

- [ ] **Step 2: 实现项目列表**

显示名称、状态、时间和关联 ID；继续按钮调用 router push 到 `/process/:projectId`；移动端转卡片布局。

- [ ] **Step 3: 实现任务列表**

状态映射覆盖 pending、processing、completed、failed、interrupted；显示进度、消息、错误和关联项目入口。

- [ ] **Step 4: 实现页面状态和首页入口**

标签切换、状态筛选、刷新、加载、错误重试、空状态；注册路由并在首页顶部导航增加入口。

- [ ] **Step 5: 前端构建**

Run: `npm --prefix frontend run build`

### Task 5: 本地端到端验证

**Files:**
- No production file changes expected.

**Interfaces:**
- Verifies: persisted task API → history page → project navigation.

- [ ] **Step 1: 全量静态验证**

Run: `python3 -m pytest backend/tests -v && npm --prefix frontend run build && git diff --check`

- [ ] **Step 2: 启动本地后端和前端**

使用临时上传目录，注入项目/任务夹具；后端监听本地端口，Vite 使用本地 API 地址。

- [ ] **Step 3: 浏览器验证**

检查首页历史入口、项目/任务标签、状态筛选、继续项目、空/错误状态、桌面与移动宽度、无错误覆盖层和控制台异常。

- [ ] **Step 4: 停止本地进程并确认服务器未受影响**

只清理本次启动的本地进程和临时目录；不执行 SSH、rsync、Docker Compose 或部署命令。
