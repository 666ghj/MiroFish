# 模型配置中心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在页面中配置 Embedding、高能力线上、高吞吐本地三种模型，并让 MiroFish 按运行阶段使用项目级不可变模型快照。

**Architecture:** SQLite 存储 Provider、草稿、不可变版本、项目快照和测试记录，独立凭据主密钥加密 API Key。`ModelRouter` 将业务阶段映射到三个角色并负责环境变量兼容与有限回退；前端通过 `/api/settings/models` 完成连接管理、测试和应用。

**Tech Stack:** Python 3.11、Flask、sqlite3、cryptography、pytest、Vue 3、Vue Router、Axios、Vite

**Spec:** `docs/superpowers/specs/2026-08-27-model-configuration-design.md`

## Global Constraints

- 只修改和验证本地代码，不部署服务器。
- 未经用户明确授权不得提交或推送。
- OAuth Token 继续由 Gateway 保存，MiroFish 不读取 OAuth 明文 Token。
- API Key 不得出现在 API 读取响应、日志、任务 metadata 或测试记录。
- Embedding 不允许自动换模型；高能力模型不自动降级。
- 尚未应用页面配置时继续兼容现有环境变量。

---

### Task 1: SQLite 配置仓库与凭据加密

**Files:**
- Create: `backend/app/models/model_config.py`
- Create: `backend/app/services/credential_cipher.py`
- Create: `backend/app/services/model_config_store.py`
- Create: `backend/tests/test_model_config_store.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `ModelRole`、`ConnectionType`、`ModelConnection`、`RoleAssignment`、`ConfigVersion`
- Produces: `CredentialCipher.encrypt/decrypt/mask`
- Produces: `ModelConfigStore` connection/draft/version/snapshot/test-run methods.

- [ ] **Step 1:** 写主密钥权限、加密往返、脱敏和数据库不含明文 Key 的失败测试。
- [ ] **Step 2:** 写连接 CRUD、依赖删除保护、三角色草稿、不可变版本和项目快照失败测试。
- [ ] **Step 3:** 运行 `python3 -m pytest backend/tests/test_model_config_store.py -v` 验证 RED。
- [ ] **Step 4:** 使用 Fernet、SQLite 事务、外键和索引实现最小存储层。
- [ ] **Step 5:** 运行同一测试验证 GREEN。

### Task 2: 环境迁移、校验、连接测试与配置应用

**Files:**
- Create: `backend/app/services/model_config_service.py`
- Create: `backend/app/services/model_connection_tester.py`
- Create: `backend/tests/test_model_config_service.py`

**Interfaces:**
- Produces: `ModelConfigService.initialize_from_environment()`
- Produces: `save_draft/get_draft/test_connection/apply_draft/get_active_version/get_or_create_project_snapshot`
- Produces: `ModelConnectionTester.test_text/test_structured/test_throughput/test_embedding/test_account`

- [ ] **Step 1:** 写 `LLM_*`、`GRAPHITI_LLM_*`、`GRAPHITI_EMBEDDING_*` 一次性迁移失败测试。
- [ ] **Step 2:** 写角色/连接类型兼容、数值范围、测试过期和应用失败测试。
- [ ] **Step 3:** 写项目快照并发唯一性测试。
- [ ] **Step 4:** 运行测试验证 RED。
- [ ] **Step 5:** 实现服务和安全测试结果持久化，运行测试验证 GREEN。

### Task 3: 模型设置 API

**Files:**
- Create: `backend/app/api/model_settings.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/__init__.py`
- Create: `backend/tests/test_model_settings_api.py`

**Interfaces:**
- Produces: `/api/settings/models/connections`
- Produces: `/api/settings/models/draft`
- Produces: `/api/settings/models/test`
- Produces: `/api/settings/models/apply`
- Produces: `/api/settings/models/active`
- Produces: `/api/settings/models/versions`
- Produces: `/api/settings/models/projects/<project_id>/snapshot`

- [ ] **Step 1:** 写连接 CRUD、Key 不可回读、依赖删除、草稿和应用契约失败测试。
- [ ] **Step 2:** 实现 Blueprint、请求校验和安全错误响应。
- [ ] **Step 3:** 运行 API 测试和后端回归。

### Task 4: ModelRouter 与业务阶段接入

**Files:**
- Create: `backend/app/services/model_router.py`
- Modify: `backend/app/utils/llm_client.py`
- Modify: `backend/app/services/ontology_generator.py`
- Modify: `backend/app/services/oasis_profile_generator.py`
- Modify: `backend/app/services/simulation_config_generator.py`
- Modify: `backend/app/services/report_agent.py`
- Modify: `backend/app/services/zep_tools.py`
- Modify: `backend/app/services/zep_graphiti_impl.py`
- Modify: `backend/app/services/simulation_runner.py`
- Create: `backend/tests/test_model_router.py`
- Create: `backend/tests/test_model_stage_mapping.py`

**Interfaces:**
- Produces: `ModelRouter.get_text_client(role, project_id)`、`get_embedder(project_id)`、`build_simulation_environment(project_id)`
- Maps: ontology/profile/config/report → high capability; Graphiti/runtime simulation → high throughput; vector operations → embedding.

- [ ] **Step 1:** 写所有阶段映射失败测试。
- [ ] **Step 2:** 写高吞吐有限回退与禁止其他角色降级失败测试。
- [ ] **Step 3:** 写模拟子进程只获得高吞吐凭据失败测试。
- [ ] **Step 4:** 实现 Router 和兼容环境变量回退。
- [ ] **Step 5:** 逐一改造业务构造点并运行后端全量回归。

### Task 5: 模型配置页面

**Files:**
- Create: `frontend/src/api/modelSettings.js`
- Create: `frontend/src/views/ModelSettingsView.vue`
- Create: `frontend/src/components/ModelRoleCard.vue`
- Create: `frontend/src/components/ModelConnectionList.vue`
- Create: `frontend/src/components/ModelConnectionDialog.vue`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/views/Home.vue`

**Interfaces:**
- Produces route: `/settings/models`
- Consumes model settings API.

- [ ] **Step 1:** 实现 API 客户端和安全写入契约。
- [ ] **Step 2:** 实现三角色概览、草稿编辑和高级参数折叠。
- [ ] **Step 3:** 实现 Provider 新增、编辑、测试、禁用和删除保护。
- [ ] **Step 4:** 实现测试后应用、Embedding 警告、加载/错误/空状态和移动布局。
- [ ] **Step 5:** 注册路由和首页入口，运行前端生产构建。

### Task 6: 本地端到端验证

**Files:**
- No production file changes expected.

- [ ] **Step 1:** 运行后端、Gateway 测试、前端构建和 `git diff --check`。
- [ ] **Step 2:** 使用临时 SQLite、Provider 夹具和本地 Vite 启动完整设置流程。
- [ ] **Step 3:** 浏览器验证连接、三角色、测试、应用、脱敏、删除保护和移动端布局。
- [ ] **Step 4:** 扫描日志、API 和 Git diff，确认无明文凭据。
- [ ] **Step 5:** 关闭本地进程，不执行 SSH、rsync、Docker Compose 或部署。
