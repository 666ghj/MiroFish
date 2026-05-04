# Fase 0 — Estabilitat del Fork Actual: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patch 7 stability issues: fix JSONL action log data loss, cap edge memory usage, add task recovery after browser refresh, persist upload session state, fix DB connection leaks, prevent LLM tool hallucinations, and handle malformed ontology attributes.

**Architecture:** Pure bug-fix hardening — no new features. Each fix is isolated to its concern. Backend patches are Python/Flask; frontend patches are Vue 3/JS. All behavioral changes have unit tests added first (TDD).

**Tech Stack:** Python 3.11, Flask, Vue 3, pytest, Neo4j (Graphiti backend)

---

## File Map

**Create:**
- `backend/tests/__init__.py` — test package marker
- `backend/tests/test_read_action_log.py` — safe_position tests (PR #460)
- `backend/tests/test_project_task_recovery.py` — active_task_id persistence tests
- `backend/tests/test_ontology_attributes.py` — string attribute normalization tests (PR #581)

**Modify:**
- `backend/app/services/simulation_runner.py` — Fix `_read_action_log` safe_position (PR #460)
- `backend/app/graph/graphiti_backend.py` — Add `max_items` LIMIT to `get_all_edges` (PR #553 equiv)
- `backend/app/models/project.py` — Add `active_task_id: Optional[str]` field
- `backend/app/api/graph.py` — Set/clear `active_task_id` on task lifecycle
- `backend/scripts/run_twitter_simulation.py` — `finally` block for DB connections (PR #578)
- `backend/app/services/report_agent.py` — Strip fabricated `<tool_result>` blocks (PR #559)
- `backend/app/services/graph_builder.py` — Guard string `attr_def` (PR #581)
- `backend/app/services/ontology_generator.py` — Normalize string attributes (PR #581)
- `frontend/src/store/pendingUpload.js` — Persist requirement to sessionStorage
- `frontend/src/views/MainView.vue` — Recovery UI: reconnect active task + friendly file-lost error
- `locales/en.json`, `locales/ca.json`, `locales/es.json`, `locales/zh.json` — New i18n keys

---

## Task 1: Create feature branch

**Files:** none

- [ ] **Step 1: Create and switch to new branch**

```bash
git checkout -b fix/fase0-estabilitat
```

Expected: `Switched to a new branch 'fix/fase0-estabilitat'`

---

## Task 2: PR #460 — Fix `_read_action_log` silent data loss

**Problem:** `for line in f` (Python file iterator) can return partial lines when the file is concurrently written. The reader advances `f.tell()` past the partial data, losing it permanently. The fix: use `readline()` explicitly and only advance `safe_position` when the line ends with `\n`.

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_read_action_log.py`
- Modify: `backend/app/services/simulation_runner.py`

- [ ] **Step 1: Create test package**

Create `backend/tests/__init__.py` as an empty file.

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_read_action_log.py`:

```python
import json
import os
import tempfile
import pytest
from unittest.mock import patch


def _make_state(sim_id="test-sim"):
    from app.services.simulation_manager import SimulationRunState
    return SimulationRunState(simulation_id=sim_id)


def _call_read(path, position, state, platform="twitter"):
    from app.services.simulation_runner import SimulationRunner
    with patch.dict(SimulationRunner._graph_memory_enabled, {}, clear=False):
        return SimulationRunner._read_action_log(path, position, state, platform)


_ACTION = {
    "action_type": "post", "agent_id": 1, "agent_name": "Alice",
    "round": 1, "timestamp": "2026-01-01T00:00:00",
    "action_args": {}, "result": None, "success": True,
}


def test_complete_lines_all_processed():
    """All lines ending with \\n are processed; final position equals file size."""
    state = _make_state()
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write(json.dumps(_ACTION) + '\n')
        f.write(json.dumps({**_ACTION, "agent_id": 2, "agent_name": "Bob"}) + '\n')
        path = f.name
    try:
        new_pos = _call_read(path, 0, state)
        assert len(state.recent_actions) == 2
        assert new_pos == os.path.getsize(path)
    finally:
        os.unlink(path)


def test_partial_last_line_not_processed():
    """Partial last line (no trailing \\n) is NOT processed; position stays before it."""
    state = _make_state("test-partial")
    complete = json.dumps(_ACTION) + '\n'
    partial = '{"action_type": "like", "agent_id": 2'  # no \n — in-progress write

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write(complete)
        f.write(partial)
        path = f.name
    try:
        new_pos = _call_read(path, 0, state)
        assert len(state.recent_actions) == 1
        assert state.recent_actions[0].action_type == 'post'
        # Position must be at end of the complete line, before the partial
        assert new_pos == len(complete.encode('utf-8'))
    finally:
        os.unlink(path)


def test_incremental_reads_pick_up_new_lines():
    """Second read from returned position picks up lines added after first read."""
    state = _make_state("test-incr")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write(json.dumps(_ACTION) + '\n')
        path = f.name
    try:
        pos1 = _call_read(path, 0, state)
        assert len(state.recent_actions) == 1

        with open(path, 'a') as f:
            f.write(json.dumps({**_ACTION, "agent_id": 3, "agent_name": "Charlie"}) + '\n')

        pos2 = _call_read(path, pos1, state)
        assert len(state.recent_actions) == 2
        assert pos2 > pos1
    finally:
        os.unlink(path)


def test_empty_file_returns_zero():
    """Empty file returns position 0 and processes nothing."""
    state = _make_state("test-empty")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        path = f.name
    try:
        new_pos = _call_read(path, 0, state)
        assert new_pos == 0
        assert len(state.recent_actions) == 0
    finally:
        os.unlink(path)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_read_action_log.py -v
```

Expected: 1-4 tests FAIL (current `for line in f` does not use safe_position)

- [ ] **Step 4: Implement fix in `simulation_runner.py`**

In `backend/app/services/simulation_runner.py`, find `_read_action_log`. The outermost `try` block contains a `with open(...)` that has `for line in f:` inside.

Replace this pattern (only the outer loop structure changes; all inner processing is identical):

```python
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            f.seek(position)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        action_data = json.loads(line)
                        # ... (all existing processing) ...
                    except json.JSONDecodeError:
                        pass
            return f.tell()
    except Exception as e:
        logger.warning(f"Failed to read action log: {log_path}, error={e}")
        return position
```

With:

```python
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            f.seek(position)
            safe_position = position
            while True:
                raw_line = f.readline()
                if not raw_line:          # EOF
                    break
                if not raw_line.endswith('\n'):  # Partial line — wait for flush
                    break
                safe_position = f.tell()
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    action_data = json.loads(line)
                    # ... (all existing processing unchanged) ...
                except json.JSONDecodeError:
                    pass
            return safe_position
    except Exception as e:
        logger.warning(f"Failed to read action log: {log_path}, error={e}")
        return position
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_read_action_log.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/tests/__init__.py backend/tests/test_read_action_log.py backend/app/services/simulation_runner.py
git commit -m "fix(simulation): prevent action log data loss from partial JSONL line reads"
```

---

## Task 3: PR #553 equiv — Cap `get_all_edges` memory usage

**Problem:** `get_all_edges` in `graphiti_backend.py` runs an unbounded Cypher query loading all edges into Python RAM. With large graphs this can exhaust server memory.

**Files:**
- Modify: `backend/app/graph/graphiti_backend.py`

- [ ] **Step 1: Add `LIMIT` to Cypher query and `max_items` parameter**

In `backend/app/graph/graphiti_backend.py`, find `get_all_edges` at line ~395:

```python
def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
    results = _run_async(
        self._client.driver.execute_query(
            "MATCH (s)-[r]->(t) WHERE r.group_id = $gid RETURN s, r, t",
            params={"gid": graph_id},
        )
    )
    edges = []
    for record in results.records:
```

Replace with:

```python
def get_all_edges(self, graph_id: str, max_items: int = 5000) -> List[Dict[str, Any]]:
    results = _run_async(
        self._client.driver.execute_query(
            "MATCH (s)-[r]->(t) WHERE r.group_id = $gid RETURN s, r, t LIMIT $limit",
            params={"gid": graph_id, "limit": max_items},
        )
    )
    if len(results.records) >= max_items:
        logger.warning(
            f"get_all_edges: result truncated at {max_items} edges for graph {graph_id}"
        )
    edges = []
    for record in results.records:
```

(All other lines in the method stay unchanged.)

- [ ] **Step 2: Verify syntax**

```bash
cd backend && uv run python -c "from app.graph.graphiti_backend import GraphitiBackend; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/graph/graphiti_backend.py
git commit -m "fix(graph): cap get_all_edges to 5000 edges to prevent unbounded RAM growth"
```

---

## Task 4: Add `active_task_id` persistence (browser-refresh task recovery)

**Problem:** When the user refreshes the browser mid graph-build, `MainView.vue` calls `loadProject()` but has no way to reconnect to the running task because the task_id only lived in the frontend's memory.

**Files:**
- Create: `backend/tests/test_project_task_recovery.py`
- Modify: `backend/app/models/project.py`
- Modify: `backend/app/api/graph.py`
- Modify: `frontend/src/views/MainView.vue`
- Modify: `locales/en.json`, `locales/ca.json`, `locales/es.json`, `locales/zh.json`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_project_task_recovery.py`:

```python
def test_project_serializes_active_task_id():
    """active_task_id is included in Project.to_dict()."""
    from app.models.project import Project, ProjectStatus
    p = Project(
        project_id="proj-1", name="Test",
        status=ProjectStatus.GRAPH_BUILDING,
        created_at="2026-01-01", updated_at="2026-01-01",
        active_task_id="task-abc-123",
    )
    assert p.to_dict()["active_task_id"] == "task-abc-123"


def test_project_deserializes_active_task_id():
    """Project.from_dict() restores active_task_id from JSON."""
    from app.models.project import Project
    data = {
        "project_id": "proj-1", "name": "Test", "status": "graph_building",
        "created_at": "2026-01-01", "updated_at": "2026-01-01",
        "active_task_id": "task-abc-123",
    }
    assert Project.from_dict(data).active_task_id == "task-abc-123"


def test_project_active_task_id_defaults_none():
    """active_task_id defaults to None for projects without it (backward compat)."""
    from app.models.project import Project
    data = {
        "project_id": "proj-1", "name": "Test", "status": "created",
        "created_at": "2026-01-01", "updated_at": "2026-01-01",
    }
    assert Project.from_dict(data).active_task_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_project_task_recovery.py -v
```

Expected: FAIL — `Project` has no `active_task_id` field

- [ ] **Step 3: Add `active_task_id` to `Project` dataclass**

In `backend/app/models/project.py`, find the `@dataclass class Project:` definition.

After the `error: Optional[str] = None` field, add:

```python
    # Active task tracking — persisted so the frontend can reconnect after a page refresh
    active_task_id: Optional[str] = None
```

In `Project.to_dict()`, add to the returned dict (after `"error": self.error`):

```python
            "active_task_id": self.active_task_id,
```

In `Project.from_dict()` (the classmethod that builds a Project from a dict), add:

```python
            active_task_id=data.get("active_task_id"),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_project_task_recovery.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Persist `active_task_id` in the graph build endpoint**

In `backend/app/api/graph.py`, find the graph build endpoint (the one that calls `task_manager.create_task(...)`).

**When the task starts** — find the block that does:
```python
task_id = task_manager.create_task(...)
project.graph_build_task_id = task_id
ProjectManager.save_project(project)
```

Add `project.active_task_id = task_id` before `ProjectManager.save_project(project)`:
```python
task_id = task_manager.create_task(...)
project.graph_build_task_id = task_id
project.active_task_id = task_id          # ← ADD
ProjectManager.save_project(project)
```

**When the task completes** — find the async thread function where the project status is set to `GRAPH_COMPLETED` (or `graph_completed`) and `ProjectManager.save_project(project)` is called. Add before that save:

```python
project.active_task_id = None             # ← ADD (task is done, no recovery needed)
ProjectManager.save_project(project)
```

**When the task fails** — find where status is set to `GRAPH_FAILED` (or similar). Add the same clear:

```python
project.active_task_id = None             # ← ADD
ProjectManager.save_project(project)
```

- [ ] **Step 6: Use `active_task_id` in `MainView.vue` recovery**

In `frontend/src/views/MainView.vue`, find the `loadProject` function. Inside the `if (res.success)` block, find:

```javascript
} else if (res.data.status === 'graph_building' && res.data.graph_build_task_id) {
  currentPhase.value = 1
  startPollingTask(res.data.graph_build_task_id)
  startGraphPolling()
}
```

Replace with:

```javascript
} else if (res.data.status === 'graph_building') {
  const taskId = res.data.active_task_id || res.data.graph_build_task_id
  if (taskId) {
    currentPhase.value = 1
    addLog(t('log.reconnectingToTask', { taskId }))
    startPollingTask(taskId)
    startGraphPolling()
  }
}
```

- [ ] **Step 7: Add i18n key to all locale files**

`locales/en.json` — add inside the `"log"` object (or create it if it doesn't exist):
```json
"reconnectingToTask": "Reconnecting to active task {taskId}…"
```

`locales/ca.json`:
```json
"reconnectingToTask": "Reconnectant a la tasca activa {taskId}…"
```

`locales/es.json`:
```json
"reconnectingToTask": "Reconectando a la tarea activa {taskId}…"
```

`locales/zh.json`:
```json
"reconnectingToTask": "重新连接到活动任务 {taskId}…"
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/project.py backend/app/api/graph.py \
        frontend/src/views/MainView.vue \
        locales/en.json locales/ca.json locales/es.json locales/zh.json \
        backend/tests/test_project_task_recovery.py
git commit -m "feat(recovery): persist active_task_id to project.json for browser-refresh reconnection"
```

---

## Task 5: Fix `pendingUpload` — survive page refresh

**Problem:** `pendingUpload.js` uses a `reactive({})` object that lives only in JavaScript memory. `File` objects cannot be serialized. On refresh, files are lost. We can at least persist `simulationRequirement` (a string) and show a friendly error when files are gone.

**Files:**
- Modify: `frontend/src/store/pendingUpload.js`
- Modify: `frontend/src/views/MainView.vue`
- Modify: all locale files

- [ ] **Step 1: Rewrite `pendingUpload.js` to use sessionStorage for requirement**

Replace the full contents of `frontend/src/store/pendingUpload.js` with:

```javascript
/**
 * Temporary storage for files and simulation requirement.
 * - simulationRequirement: persisted to sessionStorage (survives refresh within the tab)
 * - files: in-memory only (File objects are not JSON-serializable)
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: sessionStorage.getItem('pendingRequirement') || '',
  isPending: sessionStorage.getItem('pendingIsPending') === 'true',
  importOntologyMode: false,
  ontologyFile: null,
})

export function setPendingUpload(files, requirement, importOntologyMode = false, ontologyFile = null) {
  state.files = files
  state.simulationRequirement = requirement
  state.isPending = true
  state.importOntologyMode = importOntologyMode
  state.ontologyFile = ontologyFile
  sessionStorage.setItem('pendingRequirement', requirement)
  sessionStorage.setItem('pendingIsPending', 'true')
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    isPending: state.isPending,
    importOntologyMode: state.importOntologyMode,
    ontologyFile: state.ontologyFile,
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.isPending = false
  state.importOntologyMode = false
  state.ontologyFile = null
  sessionStorage.removeItem('pendingRequirement')
  sessionStorage.removeItem('pendingIsPending')
}

export default state
```

- [ ] **Step 2: Add friendly error in `MainView.vue` when files are lost**

In `frontend/src/views/MainView.vue`, find the function that reads `getPendingUpload()` and uses `pending.files` to start the upload (likely `handleNewProject` or `initProject`). Add a guard at the start of that function:

```javascript
const pending = getPendingUpload()

if (!pending.isPending) {
  return  // Not a new project session, nothing to handle
}

if (pending.files.length === 0) {
  // Files were lost (page refresh). Requirement may still be in sessionStorage
  // but File objects are gone. Show friendly error and redirect.
  error.value = t('error.filesLostAfterRefresh')
  addLog(t('error.filesLostAfterRefresh'))
  clearPendingUpload()
  setTimeout(() => router.push('/'), 3000)
  return
}
// ... existing upload code continues unchanged
```

- [ ] **Step 3: Add i18n keys to locale files**

`locales/en.json`:
```json
"filesLostAfterRefresh": "Files were lost after page refresh. Redirecting to home to re-select files…"
```

`locales/ca.json`:
```json
"filesLostAfterRefresh": "Els fitxers s'han perdut en refrescar la pàgina. Redirigint a l'inici per tornar a seleccionar-los…"
```

`locales/es.json`:
```json
"filesLostAfterRefresh": "Los archivos se perdieron al refrescar la página. Redirigiendo al inicio para volver a seleccionarlos…"
```

`locales/zh.json`:
```json
"filesLostAfterRefresh": "刷新页面后文件丢失，正在跳转到首页重新选择文件…"
```

- [ ] **Step 4: Verify frontend build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: Build succeeds without errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/pendingUpload.js frontend/src/views/MainView.vue \
        locales/en.json locales/ca.json locales/es.json locales/zh.json
git commit -m "fix(frontend): persist upload requirement to sessionStorage; friendly error when files lost on refresh"
```

---

## Task 6: PR #578 — Fix DB connection resource leak

**Problem:** `_get_interview_result` in `run_twitter_simulation.py` opens a SQLite connection but may not close it if an exception is raised before `conn.close()`.

**Files:**
- Modify: `backend/scripts/run_twitter_simulation.py`

- [ ] **Step 1: Add `finally` block to `_get_interview_result`**

In `backend/scripts/run_twitter_simulation.py`, find `_get_interview_result`. It will have a pattern like:

```python
def _get_interview_result(self, agent_id: int) -> Dict[str, Any]:
    conn = None
    try:
        conn = sqlite3.connect(self.db_path)
        # ... cursor and query ...
        return result
    except Exception as e:
        print(f"error: {e}")
        return {}
```

Add a `finally` block:

```python
def _get_interview_result(self, agent_id: int) -> Dict[str, Any]:
    conn = None
    try:
        conn = sqlite3.connect(self.db_path)
        # ... cursor and query ... (unchanged)
        return result
    except Exception as e:
        print(f"error: {e}")
        return {}
    finally:
        if conn:
            conn.close()
```

- [ ] **Step 2: Fix `handle_batch_interview` `agent_id` guard**

In the same file, find `handle_batch_interview`. Find the line that reads `agent_id` from `action_args`:

```python
agent_id = action_args.get("agent_id")
```

Replace with:

```python
agent_id = action_args.get("agent_id") or 0  # guard against None
```

- [ ] **Step 3: Check if `run_reddit_simulation.py` needs the same fix**

```bash
grep -n "conn.close\|sqlite3.connect" /home/ubuntu/dev/MiroFish/backend/scripts/run_reddit_simulation.py 2>/dev/null | head -20
```

If the same pattern exists (sqlite3.connect without a finally), apply the identical fix to `run_reddit_simulation.py`.

- [ ] **Step 4: Verify syntax**

```bash
cd backend && uv run python -c "import scripts.run_twitter_simulation; print('OK')" 2>/dev/null || echo "import as module failed, checking syntax directly" && cd backend && uv run python -m py_compile scripts/run_twitter_simulation.py && echo "Syntax OK"
```

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/run_twitter_simulation.py
git commit -m "fix(simulation): guarantee SQLite connection close with finally block"
```

---

## Task 7: PR #559 — Strip fabricated `<tool_result>` blocks from LLM responses

**Problem:** The LLM sometimes generates its own `<tool_result>` tags in the response body, confusing the ReAct loop and causing hallucinations.

**Files:**
- Modify: `backend/app/services/report_agent.py`

- [ ] **Step 1: Add `_strip_fake_tool_results` static method to `ReportAgent`**

In `backend/app/services/report_agent.py`, verify `import re` is present at the top. If not, add it.

Find the `ReportAgent` class and add this static method near the other helpers:

```python
@staticmethod
def _strip_fake_tool_results(response: str) -> str:
    """Strip <tool_result> blocks fabricated by the LLM to prevent hallucination loops."""
    cleaned = re.sub(r'<tool_result>.*?</tool_result>', '', response, flags=re.DOTALL)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()
```

- [ ] **Step 2: Apply strip wherever assistant response is added to messages**

In `report_agent.py`, search for all occurrences of:
```python
messages.append({"role": "assistant", "content": response})
```

Replace each one with:
```python
messages.append({"role": "assistant", "content": ReportAgent._strip_fake_tool_results(response)})
```

There should be 3–5 occurrences inside `_generate_section_react` and `chat`. Replace all of them.

- [ ] **Step 3: Verify syntax and import**

```bash
cd backend && uv run python -c "from app.services.report_agent import ReportAgent; print(ReportAgent._strip_fake_tool_results('<tool_result>bad</tool_result>clean'))"
```

Expected: `clean`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/report_agent.py
git commit -m "fix(report): strip fabricated tool_result blocks to prevent LLM hallucination loop"
```

---

## Task 8: PR #581 — Handle string attributes in ontology

**Problem:** When the LLM returns ontology attributes as a list of strings (`["name", "age"]`) instead of dicts (`[{"name": "name", "type": "text", ...}]`), both `ontology_generator.py` and `graph_builder.py` crash with `TypeError: string indices must be integers`.

**Files:**
- Create: `backend/tests/test_ontology_attributes.py`
- Modify: `backend/app/services/graph_builder.py`
- Modify: `backend/app/services/ontology_generator.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_ontology_attributes.py`:

```python
def test_graph_builder_normalizes_string_attributes():
    """_normalize_entity_attributes converts strings to dicts without crashing."""
    from app.services.graph_builder import GraphBuilderService

    mixed = ["name", "age", {"name": "email", "type": "text", "description": "Email"}]
    result = GraphBuilderService._normalize_entity_attributes(mixed)

    assert all(isinstance(a, dict) for a in result)
    assert result[0] == {"name": "name", "type": "text", "description": "name"}
    assert result[1] == {"name": "age", "type": "text", "description": "age"}
    assert result[2]["name"] == "email"


def test_graph_builder_normalize_empty():
    """Empty attribute list returns empty list."""
    from app.services.graph_builder import GraphBuilderService
    assert GraphBuilderService._normalize_entity_attributes([]) == []


def test_ontology_generator_normalizes_string_attributes():
    """_normalize_ontology_attributes converts string attrs in entities and edges."""
    from app.services.ontology_generator import OntologyGenerator

    raw = {
        "entities": [{"name": "Person", "description": "A person", "attributes": ["name", "age"]}],
        "edges": [{"name": "KNOWS", "description": "Knows", "attributes": ["since"]}],
    }
    result = OntologyGenerator._normalize_ontology_attributes(raw)

    entity_attrs = result["entities"][0]["attributes"]
    assert all(isinstance(a, dict) for a in entity_attrs)
    assert entity_attrs[0] == {"name": "name", "type": "text", "description": "name"}

    edge_attrs = result["edges"][0]["attributes"]
    assert all(isinstance(a, dict) for a in edge_attrs)
    assert edge_attrs[0] == {"name": "since", "type": "text", "description": "since"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_ontology_attributes.py -v
```

Expected: FAIL — `_normalize_entity_attributes` and `_normalize_ontology_attributes` don't exist yet

- [ ] **Step 3: Add `_normalize_entity_attributes` to `GraphBuilderService`**

In `backend/app/services/graph_builder.py`, find the `GraphBuilderService` class. Add this static method:

```python
@staticmethod
def _normalize_entity_attributes(attributes: list) -> list:
    """Ensure each attribute item is a dict; convert strings to minimal dicts."""
    result = []
    for attr in attributes:
        if isinstance(attr, str):
            result.append({"name": attr, "type": "text", "description": attr})
        elif isinstance(attr, dict):
            result.append(attr)
    return result
```

Find all places in `GraphBuilderService` where `entity_def.get("attributes", [])` (or a similar expression) is iterated with `for attr_def in ...:` and then `attr_def["name"]` is accessed. Replace those loops with:

```python
for attr_def in GraphBuilderService._normalize_entity_attributes(entity_def.get("attributes", [])):
    attr_name = safe_attr_name(attr_def["name"])
    attr_desc = attr_def.get("description", attr_name)
    # ... rest of loop unchanged
```

Apply the same pattern for edge attribute loops if they exist.

- [ ] **Step 4: Add `_normalize_ontology_attributes` to `OntologyGenerator`**

In `backend/app/services/ontology_generator.py`, find the `OntologyGenerator` class. Add this static method:

```python
@staticmethod
def _normalize_ontology_attributes(ontology: dict) -> dict:
    """Normalize string attributes in LLM-generated ontology to dicts (in-place)."""
    for entity in ontology.get("entities", []):
        entity["attributes"] = [
            attr if isinstance(attr, dict)
            else {"name": attr, "type": "text", "description": attr}
            for attr in entity.get("attributes", [])
        ]
    for edge in ontology.get("edges", []):
        edge["attributes"] = [
            attr if isinstance(attr, dict)
            else {"name": attr, "type": "text", "description": attr}
            for attr in edge.get("attributes", [])
        ]
    return ontology
```

Find the method in `OntologyGenerator` that returns the parsed ontology after the LLM call (look for `json.loads(...)` of the LLM response, typically returning a dict with `"entities"` and `"edges"` keys). Call the normalizer before returning:

```python
ontology = OntologyGenerator._normalize_ontology_attributes(ontology)
return ontology
```

- [ ] **Step 5: Run all tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: All tests pass (test_read_action_log × 4, test_project_task_recovery × 3, test_ontology_attributes × 3 = 10 total)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/graph_builder.py backend/app/services/ontology_generator.py \
        backend/tests/test_ontology_attributes.py
git commit -m "fix(ontology): handle string attributes from LLM response to prevent TypeError crash"
```

---

## Task 9: Final verification and push

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: All 10 tests PASS

- [ ] **Step 2: Run frontend build**

```bash
cd /home/ubuntu/dev/MiroFish/frontend && npm run build 2>&1 | tail -15
```

Expected: Build succeeds, no errors

- [ ] **Step 3: Quick smoke-check imports**

```bash
cd backend && uv run python -c "
from app.services.simulation_runner import SimulationRunner
from app.graph.graphiti_backend import GraphitiBackend
from app.models.project import Project
from app.services.report_agent import ReportAgent
from app.services.graph_builder import GraphBuilderService
from app.services.ontology_generator import OntologyGenerator
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 4: Push branch**

```bash
git push -u origin fix/fase0-estabilitat
```

- [ ] **Step 5: Create PR**

```bash
gh pr create \
  --title "fix: Fase 0 — Estabilitat del Fork (7 stability patches)" \
  --base main \
  --body "$(cat <<'EOF'
## Summary

Hardening pass resolving 7 stability issues identified in the enterprise roadmap (2026-04-26):

- **PR #460 equiv** — Fix `_read_action_log` partial JSONL reads; `safe_position` only advances on complete lines ending with `\n`
- **PR #553 equiv** — Cap `get_all_edges` to 5000 items with Cypher `LIMIT` to prevent unbounded RAM growth on large graphs
- **PR #578 equiv** — Guarantee SQLite connection close with `finally` block; guard `agent_id` against None
- **PR #559 equiv** — Strip fabricated `<tool_result>` blocks from LLM responses to prevent ReAct hallucination loops
- **PR #581 equiv** — Normalize string attributes in LLM-generated ontology to prevent `TypeError: string indices must be integers`
- **New** — Persist `active_task_id` to `project.json`; `MainView.vue` reconnects polling after browser refresh
- **New** — Persist upload `simulationRequirement` to `sessionStorage`; friendly redirect error when files are lost on refresh

## Test plan

- [ ] `cd backend && uv run pytest tests/ -v` — 10 tests, all green
- [ ] `cd frontend && npm run build` — no errors
- [ ] Manual: start a graph build → refresh browser mid-build → should show "Reconnecting to active task…" and resume polling
- [ ] Manual: select files on Home → refresh MainView before files upload → should show friendly error and redirect to Home after 3s
- [ ] Manual: start a simulation with large document → server RAM should not spike unboundedly
EOF
)"
```

---

## Self-Review

**Spec coverage check:**

| Roadmap item | Task |
|---|---|
| Integrar PR #460 — Fix data loss action log | Task 2 ✅ |
| Integrar PR #553 — Memory limit per a grafs grans | Task 3 ✅ |
| Fix TaskManager persistence (task_id recovery) | Task 4 ✅ |
| Fix pendingUpload (sessionStorage + friendly error) | Task 5 ✅ |
| Integrar PR #578 — DB resource management | Task 6 ✅ |
| Integrar PR #559 — LLM hallucination fix | Task 7 ✅ |
| Integrar PR #581 — Ontology string attributes fix | Task 8 ✅ |

**No placeholders:** All steps contain complete code or exact shell commands. The only abbreviation is `# ... (existing processing unchanged)` in Task 2 Step 4, which refers to processing code that is genuinely not modified.

**Type consistency:** `active_task_id` is `Optional[str]` throughout (Project dataclass, to_dict, from_dict, JS frontend). `_normalize_entity_attributes` and `_normalize_ontology_attributes` method names are consistent across test file and implementation.
