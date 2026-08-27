# 历史记录中心设计

## 目标

为 MiroFish-local 增加可持久化的历史记录中心，使用户能在后端重启后继续查看历史项目和全部后台任务，并从项目记录直接返回现有工作流。

本功能只修改和验证本地代码，不部署服务器，不影响 ColoCrossing 上正在运行的任务。

## 用户体验

首页顶部导航增加“历史记录”入口，对应独立路由 `/history`。页面包含两个标签：

- 项目：显示项目名称、创建时间、当前状态、图谱 ID、模拟 ID 和最近更新时间；点击“继续项目”进入 `/process/:projectId`。
- 后台任务：显示任务类型、创建时间、更新时间、状态、进度、状态消息、失败原因和关联项目；支持按全部、运行中、成功、失败、中断筛选，并支持手动刷新。

加载超过短暂等待时展示明确加载状态；接口失败时显示可重试错误；没有数据时显示空状态。状态不只依赖颜色，还必须有文本标签。

首版不提供删除历史、批量清理、重跑任务或恢复中断任务，避免误操作和伪恢复。

## 任务持久化

`TaskManager` 继续提供现有内存查询和更新接口，同时通过独立存储类将任务写入 SQLite：

```text
<UPLOAD_FOLDER>/tasks/tasks.db
```

该目录位于现有 `mirofish_uploads` 数据卷内，无需新增 MySQL 或新 Docker Volume。使用 Python 标准库 `sqlite3`，开启 WAL、5000ms busy timeout 和事务 UPSERT，并为状态、创建时间和任务类型建立索引。

每次创建和更新任务后立即持久化。进程首次获取 `TaskManager` 时加载已有数据。JSON 类型字段以文本列保存并在读取时严格解码，损坏或未知记录应跳过并记录警告，不能阻止后端启动。

首次启动若发现同目录旧 `tasks.json` 且 SQLite 尚无记录，则事务导入后将旧文件重命名为 `tasks.json.migrated`。SQLite 已有数据时不得用旧 JSON 覆盖；损坏 JSON 保持原样并记录错误。

后端重启时，加载到的 `pending` 或 `processing` 任务统一转换为新状态 `interrupted`，消息设为“服务重启，任务已中断”。这一状态只表示历史事实，不尝试恢复线程。

已有 `completed`、`failed`、`interrupted` 任务保持原状态。`cleanup_old_tasks` 删除内存记录后同步持久化文件。

## 任务关联信息

所有新建后台任务应尽量写入统一 metadata：

```json
{
  "project_id": "proj_xxx",
  "graph_id": "mirofish_xxx",
  "simulation_id": "sim_xxx",
  "report_id": "report_xxx"
}
```

字段按任务阶段可选，不要求旧任务补齐不存在的信息。历史任务页面根据 `project_id` 提供“查看项目”入口；没有关联项目的任务只展示详情。

本次覆盖当前通过 `TaskManager.create_task` 创建的建图、模拟、报告等全部后台任务。各调用点只补充已经掌握的关联 ID，不额外查询或推断。

## API

保留现有接口并扩展响应：

- `GET /api/graph/project/list?limit=50`
- `GET /api/graph/tasks`
- `GET /api/graph/task/<task_id>`

`/tasks` 增加可选参数：

- `status`：`pending|processing|completed|failed|interrupted`
- `limit`：默认 100，最大 500

任务响应保持已有字段兼容，只增加 `interrupted` 状态和关联 metadata，不删除或改名现有字段。

## 前端结构

新增：

- `frontend/src/views/HistoryView.vue`：页面布局、标签、筛选、加载和错误状态。
- `frontend/src/components/HistoryProjectList.vue`：项目列表。
- `frontend/src/components/HistoryTaskList.vue`：任务列表。
- `frontend/src/api/history.js`：项目和任务查询。

修改：

- `frontend/src/router/index.js`：注册 `/history`。
- `frontend/src/views/Home.vue`：增加历史记录导航入口。

视觉保持现有 MiroFish 工业控制台风格，使用现有颜色、边框和字体语言；桌面端为信息表格/卡片，窄屏降级为纵向卡片。所有按钮具备键盘焦点和至少 44px 的移动端触控区域。

## 错误处理

- 数据库不存在时自动建表并视为空任务列表。
- 单条 JSON 字段损坏时跳过该条并记录警告。
- 旧 JSON 损坏时保留原文件并记录错误，不阻止 SQLite 初始化。
- 持久化失败时记录错误并让当前任务操作继续保留在内存；API 不暴露文件路径或底层异常。
- 前端请求失败时保留已加载数据并显示重试入口。

## 测试与验收

后端测试覆盖：

- 创建、更新、完成、失败和清理触发持久化。
- 重启加载后运行中任务变为 `interrupted`。
- 原子写入及损坏文件/损坏记录容错。
- 状态和数量过滤。
- metadata 关联字段。

前端验证覆盖：

- API 模块请求参数。
- 前端生产构建通过。
- 浏览器中首页入口、项目/任务切换、筛选、继续项目、空状态、错误状态和窄屏布局正常。
- 浏览器无控制台错误和 Vite 错误覆盖层。

最终只交付本地未提交改动和验证结果，不执行服务器同步、容器重建或部署。
