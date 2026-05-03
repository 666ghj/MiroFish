# F2-A+B: Agents Configurables i Paràmetres de Simulació — Pla d'Implementació

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar el Step 2 en un flux de tres fases interactiu: generació i edició d'agents (Fase A), edició de paràmetres de comportament/simulació (Fase B) i aïllament de grafs per simulació (Subsistema 5).

**Architecture:** El backend afegeix nous endpoints REST a `simulation.py` i nou mètode `clone_graph` a `graphiti_backend.py`. El model de simulació guanya dos nous camps (`parent_simulation_id`, `graph_id_simulation`). El frontend refactoritza `Step2EnvSetup.vue` en dues fases visuals amb confirmació explícita de l'usuari entre elles.

**Tech Stack:** Flask (Python), Vue 3 + Composition API, SQLAlchemy (SQLite), Neo4j/APOC (Graphiti backend), vue-i18n

---

## Mapa de fitxers

### Backend (crear o modificar)

| Fitxer | Acció | Responsabilitat |
|--------|-------|-----------------|
| `backend/app/services/simulation_manager.py` | Modificar | Afegir `PROFILES_READY`, `CONFIGURING` a `SimulationStatus`; afegir `parent_simulation_id`, `graph_id_simulation` a `SimulationState`; mètodes `patch_agent_profile`, `delete_agent_profile`, `generate_config_async`, `clone_simulation` |
| `backend/app/services/zep_entity_reader.py` | Modificar | Afegir `get_entities_by_connectivity(graph_id, max_n)` |
| `backend/app/services/oasis_profile_generator.py` | Modificar | Exposar `generate_profile_from_entity(entity, extra_instructions)` com a mètode públic |
| `backend/app/graph/graphiti_backend.py` | Modificar | Afegir `clone_graph(src_group_id, dst_group_id)` i `delete_graph(group_id)` |
| `backend/app/api/simulation.py` | Modificar | Afegir 7 nous endpoints: PATCH agent, DELETE agent, POST agent, POST agent/regen, POST generate-config, PATCH config, POST clone; modificar POST start per a `graph_id_simulation` |
| `backend/app/api/report.py` | Modificar | Passar `graph_id_simulation` al ReportAgent si existeix |
| `backend/tests/test_simulation_agent_api.py` | Crear | Tests integració dels nous endpoints d'agent |
| `backend/tests/test_simulation_clone.py` | Crear | Tests integració clone i graph isolation |

### Frontend (modificar)

| Fitxer | Acció | Responsabilitat |
|--------|-------|-----------------|
| `frontend/src/components/Step2EnvSetup.vue` | Modificar | Refactoritzar en Fase A + Fase B; selector N agents; modal edició/regeneració/creació/eliminació agent |
| `frontend/src/components/Step3Simulation.vue` | Modificar | `enable_graph_memory_update` com a checkbox (default true) |
| `frontend/src/api/simulation.js` | Modificar | Afegir les 7 noves crides API |
| `locales/en.json` | Modificar | Claus noves per a Fase A/B, errors, confirmacions |
| `locales/zh.json` | Modificar | Traduccions xineses corresponents |

---

## Task 1: Nous estats i camps a `SimulationState`

**Files:**
- Modify: `backend/app/services/simulation_manager.py:25-35` (SimulationStatus enum)
- Modify: `backend/app/services/simulation_manager.py:43-77` (SimulationState dataclass)
- Test: `backend/tests/test_simulation_manager_states.py`

- [ ] **Step 1: Escriure el test que falla**

```python
# backend/tests/test_simulation_manager_states.py
import pytest
from backend.app.services.simulation_manager import SimulationStatus, SimulationState

def test_profiles_ready_status_exists():
    assert SimulationStatus.PROFILES_READY == "profiles_ready"

def test_configuring_status_exists():
    assert SimulationStatus.CONFIGURING == "configuring"

def test_simulation_state_has_parent_id():
    state = SimulationState(simulation_id="sim_x", project_id="p", graph_id="g")
    assert hasattr(state, 'parent_simulation_id')
    assert state.parent_simulation_id is None

def test_simulation_state_has_graph_id_simulation():
    state = SimulationState(simulation_id="sim_x", project_id="p", graph_id="g")
    assert hasattr(state, 'graph_id_simulation')
    assert state.graph_id_simulation is None

def test_to_dict_includes_new_fields():
    state = SimulationState(simulation_id="sim_x", project_id="p", graph_id="g")
    d = state.to_dict()
    assert 'parent_simulation_id' in d
    assert 'graph_id_simulation' in d
```

- [ ] **Step 2: Executar el test per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_manager_states.py -v
```
Expected: FAIL — `SimulationStatus` no té `PROFILES_READY` ni `CONFIGURING`

- [ ] **Step 3: Implementar els canvis a `simulation_manager.py`**

Localitza `class SimulationStatus(str, Enum):` (línia ~25) i afegeix els nous estats:

```python
class SimulationStatus(str, Enum):
    """Simulation status"""
    CREATED = "created"
    PREPARING = "preparing"
    PROFILES_READY = "profiles_ready"   # NEW: agents generated, awaiting user confirmation
    CONFIGURING = "configuring"          # NEW: generating behavior config async
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
```

Localitza `@dataclass\nclass SimulationState:` i afegeix dos nous camps opcionals just després de `error: Optional[str] = None`:

```python
    # New fields for F2-A+B
    parent_simulation_id: Optional[str] = None   # set when cloned from another simulation
    graph_id_simulation: Optional[str] = None    # per-simulation Neo4j group_id (cloned from graph_id_document)
```

Actualitza `to_dict()` i `to_simple_dict()` per incloure els nous camps:

```python
    def to_dict(self) -> Dict[str, Any]:
        return {
            # ... camps existents ...
            "error": self.error,
            "parent_simulation_id": self.parent_simulation_id,
            "graph_id_simulation": self.graph_id_simulation,
        }

    def to_simple_dict(self) -> Dict[str, Any]:
        return {
            # ... camps existents ...
            "error": self.error,
            "parent_simulation_id": self.parent_simulation_id,
            "graph_id_simulation": self.graph_id_simulation,
        }
```

Actualitza `_load_simulation_state()` per llegir els nous camps:

```python
        state = SimulationState(
            # ... camps existents ...
            error=data.get("error"),
            parent_simulation_id=data.get("parent_simulation_id"),
            graph_id_simulation=data.get("graph_id_simulation"),
        )
```

- [ ] **Step 4: Executar el test per verificar que passa**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_manager_states.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/simulation_manager.py backend/tests/test_simulation_manager_states.py
git commit -m "feat(simulation): add profiles_ready/configuring states and parent_simulation_id/graph_id_simulation fields"
```

---

## Task 2: `PATCH /api/simulation/{sim_id}/agent/{user_id}` — edició d'agent

**Files:**
- Modify: `backend/app/api/simulation.py` (afegir ruta)
- Modify: `backend/app/services/simulation_manager.py` (afegir mètode)
- Test: `backend/tests/test_simulation_agent_api.py`

- [ ] **Step 1: Escriure el test que falla**

```python
# backend/tests/test_simulation_agent_api.py
import json
import os
import pytest
from backend.app import create_app

@pytest.fixture
def client():
    app = create_app({'TESTING': True})
    with app.test_client() as c:
        yield c

@pytest.fixture
def sim_with_profiles(tmp_path, monkeypatch):
    """Creates a simulation directory with a minimal state.json and reddit_profiles.json"""
    from backend.app.services.simulation_manager import SimulationManager, SimulationStatus
    monkeypatch.setenv("OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    
    sim_id = "sim_test001"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    
    state = {
        "simulation_id": sim_id,
        "project_id": "proj_test",
        "graph_id": "g1",
        "status": "profiles_ready",
        "entities_count": 2,
        "profiles_count": 2,
        "entity_types": [],
        "config_generated": False,
        "parent_simulation_id": None,
        "graph_id_simulation": None,
    }
    (sim_dir / "state.json").write_text(json.dumps(state))
    
    profiles = [
        {"user_id": 0, "user_name": "alice", "name": "Alice", "bio": "Original bio", "persona": "Curious", "manually_edited": False},
        {"user_id": 1, "user_name": "bob", "name": "Bob", "bio": "Bob bio", "persona": "Bold", "manually_edited": False},
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles))
    return sim_id


def test_patch_agent_updates_bio(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.patch(f"/api/simulation/{sim_id}/agent/0", json={"bio": "Updated bio"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["bio"] == "Updated bio"
    assert data["data"]["manually_edited"] is True

def test_patch_agent_sets_manually_edited(client, sim_with_profiles):
    sim_id = sim_with_profiles
    client.patch(f"/api/simulation/{sim_id}/agent/0", json={"bio": "New bio"})
    # Re-read profiles file
    import json as _json
    from pathlib import Path
    import os
    sim_dir = Path(os.environ["OASIS_SIMULATION_DATA_DIR"]) / sim_id
    profiles = _json.loads((sim_dir / "reddit_profiles.json").read_text())
    assert profiles[0]["manually_edited"] is True
    assert profiles[1]["manually_edited"] is False  # untouched

def test_patch_agent_not_found(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.patch(f"/api/simulation/{sim_id}/agent/99", json={"bio": "x"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py::test_patch_agent_updates_bio -v
```
Expected: FAIL — endpoint no existeix (404)

- [ ] **Step 3: Afegir `patch_agent_profile()` a `SimulationManager`**

Al final de la classe `SimulationManager` (al fitxer `simulation_manager.py`), afegeix:

```python
    def patch_agent_profile(self, simulation_id: str, user_id: int, fields: dict) -> dict:
        """
        Update an agent's profile fields and set manually_edited=True.
        Raises ValueError if simulation not found, agent not found, or status is immutable.
        Uses atomic write: backup → write → delete backup on success, restore on failure.
        """
        state = self.get_simulation(simulation_id)
        if not state:
            raise ValueError(f"Simulation {simulation_id} not found")
        
        immutable = {SimulationStatus.RUNNING, SimulationStatus.COMPLETED}
        if state.status in immutable:
            raise PermissionError(f"Cannot edit agent while simulation is {state.status.value}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        backup_file = profiles_file + ".bak"

        if not os.path.exists(profiles_file):
            raise FileNotFoundError(f"reddit_profiles.json not found for {simulation_id}")

        with open(profiles_file, 'r', encoding='utf-8') as f:
            profiles = json.load(f)

        # Find the agent
        target = next((p for p in profiles if p.get("user_id") == user_id), None)
        if target is None:
            raise LookupError(f"Agent user_id={user_id} not found in simulation {simulation_id}")

        # Apply allowed Fase A fields
        allowed = {
            "name", "bio", "persona", "age", "gender", "mbti",
            "country", "profession", "interested_topics", "stance", "sentiment_bias",
            # Fase B behavior fields
            "posts_per_hour", "comments_per_hour", "active_hours",
            "response_delay_min", "response_delay_max", "activity_level", "influence_weight",
        }
        for k, v in fields.items():
            if k in allowed:
                target[k] = v
        target["manually_edited"] = True

        # Atomic write
        import shutil
        shutil.copy2(profiles_file, backup_file)
        try:
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
            os.remove(backup_file)
        except Exception:
            shutil.copy2(backup_file, profiles_file)
            os.remove(backup_file)
            raise

        return target
```

- [ ] **Step 4: Afegir l'endpoint `PATCH /<sim_id>/agent/<user_id>` a `simulation.py`**

A la secció `# ============== Simulation management endpoints ==============` de `simulation.py`, afegeix just abans del tancament del fitxer:

```python
# ============== F2-A: Agent CRUD endpoints ==============

@simulation_bp.route('/<simulation_id>/agent/<int:user_id>', methods=['PATCH'])
def patch_agent(simulation_id: str, user_id: int):
    """Update an agent profile (Fase A/B fields). Sets manually_edited=True."""
    try:
        fields = request.get_json() or {}
        if not fields:
            return jsonify({"success": False, "error": t('api.requireFields')}), 400
        
        manager = SimulationManager()
        try:
            updated = manager.patch_agent_profile(simulation_id, user_id, fields)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except PermissionError as e:
            return jsonify({"success": False, "error": str(e)}), 403
        except LookupError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        
        return jsonify({"success": True, "data": updated})
    except Exception as e:
        logger.error(f"patch_agent failed: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 5: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py -v
```
Expected: PASS (3 tests nous)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/simulation.py backend/app/services/simulation_manager.py backend/tests/test_simulation_agent_api.py
git commit -m "feat(simulation): add PATCH /simulation/{id}/agent/{user_id} endpoint"
```

---

## Task 3: `DELETE /api/simulation/{sim_id}/agent/{user_id}` — eliminació d'agent

**Files:**
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/services/simulation_manager.py`
- Test: `backend/tests/test_simulation_agent_api.py` (ampliar)

- [ ] **Step 1: Afegir test que falla**

Afegeix a `backend/tests/test_simulation_agent_api.py`:

```python
def test_delete_agent_removes_from_profiles(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.delete(f"/api/simulation/{sim_id}/agent/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    # Verify file
    import json as _json
    from pathlib import Path
    import os
    sim_dir = Path(os.environ["OASIS_SIMULATION_DATA_DIR"]) / sim_id
    profiles = _json.loads((sim_dir / "reddit_profiles.json").read_text())
    assert all(p["user_id"] != 1 for p in profiles)
    assert len(profiles) == 1

def test_delete_agent_not_found(client, sim_with_profiles):
    sim_id = sim_with_profiles
    resp = client.delete(f"/api/simulation/{sim_id}/agent/99")
    assert resp.status_code == 404
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py::test_delete_agent_removes_from_profiles -v
```
Expected: FAIL — endpoint no existeix

- [ ] **Step 3: Afegir `delete_agent_profile()` a `SimulationManager`**

```python
    def delete_agent_profile(self, simulation_id: str, user_id: int) -> None:
        """Remove an agent from reddit_profiles.json. Atomic write."""
        state = self.get_simulation(simulation_id)
        if not state:
            raise ValueError(f"Simulation {simulation_id} not found")
        
        immutable = {SimulationStatus.RUNNING, SimulationStatus.COMPLETED}
        if state.status in immutable:
            raise PermissionError(f"Cannot delete agent while simulation is {state.status.value}")

        sim_dir = self._get_simulation_dir(simulation_id)
        profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        backup_file = profiles_file + ".bak"

        with open(profiles_file, 'r', encoding='utf-8') as f:
            profiles = json.load(f)

        original_len = len(profiles)
        profiles = [p for p in profiles if p.get("user_id") != user_id]
        if len(profiles) == original_len:
            raise LookupError(f"Agent user_id={user_id} not found")

        import shutil
        shutil.copy2(profiles_file, backup_file)
        try:
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)
            os.remove(backup_file)
        except Exception:
            shutil.copy2(backup_file, profiles_file)
            os.remove(backup_file)
            raise
```

- [ ] **Step 4: Afegir l'endpoint `DELETE /<sim_id>/agent/<user_id>` a `simulation.py`**

```python
@simulation_bp.route('/<simulation_id>/agent/<int:user_id>', methods=['DELETE'])
def delete_agent(simulation_id: str, user_id: int):
    """Remove an agent from the simulation (Fase A only)."""
    try:
        manager = SimulationManager()
        try:
            manager.delete_agent_profile(simulation_id, user_id)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except PermissionError as e:
            return jsonify({"success": False, "error": str(e)}), 403
        except LookupError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        
        return jsonify({"success": True, "data": {"deleted_user_id": user_id}})
    except Exception as e:
        logger.error(f"delete_agent failed: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 5: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py -v
```
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/simulation.py backend/app/services/simulation_manager.py backend/tests/test_simulation_agent_api.py
git commit -m "feat(simulation): add DELETE /simulation/{id}/agent/{user_id} endpoint"
```

---

## Task 4: `POST /api/simulation/{sim_id}/generate-config` — transició Fase A → B

**Files:**
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/services/simulation_manager.py`
- Test: `backend/tests/test_simulation_agent_api.py` (ampliar)

- [ ] **Step 1: Afegir test que falla**

```python
def test_generate_config_changes_status_to_configuring(client, sim_with_profiles, monkeypatch):
    sim_id = sim_with_profiles
    # Mock SimulationConfigGenerator to avoid LLM calls
    import backend.app.services.simulation_manager as sm_module
    called = []
    def fake_generate(self, *a, **kw):
        called.append(True)
        return type('SP', (), {'to_dict': lambda s: {}})()
    monkeypatch.setattr(
        "backend.app.services.simulation_config_generator.SimulationConfigGenerator.generate_simulation_parameters",
        fake_generate
    )
    resp = client.post(f"/api/simulation/{sim_id}/generate-config", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py::test_generate_config_changes_status_to_configuring -v
```
Expected: FAIL — endpoint no existeix

- [ ] **Step 3: Afegir l'endpoint `POST /<sim_id>/generate-config` a `simulation.py`**

```python
@simulation_bp.route('/<simulation_id>/generate-config', methods=['POST'])
def generate_config(simulation_id: str):
    """
    Transition from Fase A to Fase B.
    Validates status=profiles_ready, changes to configuring, starts async config generation.
    Returns task_id for polling.
    """
    import threading
    from ..models.task import TaskManager, TaskStatus
    from ..services.simulation_config_generator import SimulationConfigGenerator
    
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({"success": False, "error": t('api.simulationNotFound', id=simulation_id)}), 404
        
        if state.status != SimulationStatus.PROFILES_READY:
            return jsonify({
                "success": False,
                "error": t('api.requireProfilesReady', status=state.status.value)
            }), 400

        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({"success": False, "error": t('api.projectNotFound', id=state.project_id)}), 404

        simulation_requirement = project.get("simulation_requirement") or ""
        document_text = ProjectManager.get_extracted_text(state.project_id, get_storage()) or ""

        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="generate_config",
            metadata={"simulation_id": simulation_id}
        )

        state.status = SimulationStatus.CONFIGURING
        manager._save_simulation_state(state)

        current_locale = get_locale()

        def run_generate_config():
            set_locale(current_locale)
            try:
                task_manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=0,
                                         message=t('progress.generatingSimConfig'))
                
                # Load current profiles (respects manually_edited agents)
                sim_dir = manager._get_simulation_dir(simulation_id)
                profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)

                from ..services.zep_entity_reader import ZepEntityReader, EntityNode
                entity_nodes = []
                reader = ZepEntityReader()
                for p in profiles:
                    uuid_ = p.get("source_entity_uuid")
                    if uuid_:
                        try:
                            entity = reader.get_entity_with_context(state.graph_id, uuid_)
                            if entity:
                                entity_nodes.append(entity)
                        except Exception:
                            pass

                gen = SimulationConfigGenerator(graph_id=state.graph_id)
                params = gen.generate_simulation_parameters(
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    entities=entity_nodes,
                )

                config_data = params.to_dict() if hasattr(params, 'to_dict') else {}
                config_file = os.path.join(sim_dir, "simulation_config.json")
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=2)

                # Update state.json
                state2 = manager.get_simulation(simulation_id)
                if state2:
                    state2.status = SimulationStatus.READY
                    state2.config_generated = True
                    manager._save_simulation_state(state2)

                task_manager.complete_task(task_id, result={"status": "prepared"})
            except Exception as e:
                logger.error(f"generate_config failed: {e}")
                task_manager.fail_task(task_id, str(e))
                state2 = manager.get_simulation(simulation_id)
                if state2:
                    state2.status = SimulationStatus.PROFILES_READY
                    manager._save_simulation_state(state2)

        threading.Thread(target=run_generate_config, daemon=True).start()

        return jsonify({"success": True, "data": {"simulation_id": simulation_id, "task_id": task_id}})
    except Exception as e:
        logger.error(f"generate_config endpoint error: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 4: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py -v
```
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/simulation.py backend/tests/test_simulation_agent_api.py
git commit -m "feat(simulation): add POST /simulation/{id}/generate-config for Fase A→B transition"
```

---

## Task 5: `PATCH /api/simulation/{sim_id}/config` — edició paràmetres globals (Fase B)

**Files:**
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/services/simulation_manager.py`
- Test: `backend/tests/test_simulation_agent_api.py` (ampliar)

- [ ] **Step 1: Afegir test que falla**

Afegeix a `backend/tests/test_simulation_agent_api.py`:

```python
@pytest.fixture
def sim_prepared(tmp_path, monkeypatch):
    """Creates a simulation with status=ready and a simulation_config.json"""
    monkeypatch.setenv("OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    sim_id = "sim_prepared001"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    state = {
        "simulation_id": sim_id, "project_id": "p", "graph_id": "g",
        "status": "ready", "entities_count": 1, "profiles_count": 1,
        "entity_types": [], "config_generated": True,
        "parent_simulation_id": None, "graph_id_simulation": None,
    }
    (sim_dir / "state.json").write_text(json.dumps(state))
    config = {"time_config": {"total_simulation_hours": 24, "minutes_per_round": 60}, "agent_configs": []}
    (sim_dir / "simulation_config.json").write_text(json.dumps(config))
    return sim_id

def test_patch_config_updates_total_hours(client, sim_prepared):
    sim_id = sim_prepared
    resp = client.patch(f"/api/simulation/{sim_id}/config",
                        json={"total_simulation_hours": 48})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["time_config"]["total_simulation_hours"] == 48
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py::test_patch_config_updates_total_hours -v
```
Expected: FAIL

- [ ] **Step 3: Afegir `patch_simulation_config()` a `SimulationManager`**

```python
    def patch_simulation_config(self, simulation_id: str, fields: dict) -> dict:
        """
        Update top-level simulation config fields.
        Supported: total_simulation_hours, minutes_per_round, agents_per_hour_min,
        agents_per_hour_max, following_probability, recsys_type,
        twitter_config (dict merged), reddit_config (dict merged).
        Atomic write.
        """
        state = self.get_simulation(simulation_id)
        if not state:
            raise ValueError(f"Simulation {simulation_id} not found")

        immutable = {SimulationStatus.RUNNING, SimulationStatus.COMPLETED}
        if state.status in immutable:
            raise PermissionError(f"Cannot edit config while simulation is {state.status.value}")

        sim_dir = self._get_simulation_dir(simulation_id)
        config_file = os.path.join(sim_dir, "simulation_config.json")
        backup_file = config_file + ".bak"

        if not os.path.exists(config_file):
            raise FileNotFoundError("simulation_config.json not found")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # time_config fields
        time_fields = {"total_simulation_hours", "minutes_per_round",
                       "agents_per_hour_min", "agents_per_hour_max"}
        time_config = config.setdefault("time_config", {})
        for k in time_fields:
            if k in fields:
                time_config[k] = fields[k]

        # top-level fields
        for k in ("following_probability", "recsys_type"):
            if k in fields:
                config[k] = fields[k]

        # nested config merge (twitter_config, reddit_config)
        for nested in ("twitter_config", "reddit_config"):
            if nested in fields and isinstance(fields[nested], dict):
                config.setdefault(nested, {}).update(fields[nested])

        import shutil
        shutil.copy2(config_file, backup_file)
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            os.remove(backup_file)
        except Exception:
            shutil.copy2(backup_file, config_file)
            os.remove(backup_file)
            raise

        return config
```

- [ ] **Step 4: Afegir l'endpoint `PATCH /<sim_id>/config` a `simulation.py`**

```python
@simulation_bp.route('/<simulation_id>/config', methods=['PATCH'])
def patch_simulation_config(simulation_id: str):
    """Update simulation global config parameters (Fase B)."""
    try:
        fields = request.get_json() or {}
        if not fields:
            return jsonify({"success": False, "error": t('api.requireFields')}), 400
        
        manager = SimulationManager()
        try:
            updated = manager.patch_simulation_config(simulation_id, fields)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except PermissionError as e:
            return jsonify({"success": False, "error": str(e)}), 403
        except FileNotFoundError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        
        return jsonify({"success": True, "data": updated})
    except Exception as e:
        logger.error(f"patch_simulation_config failed: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 5: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py -v
```
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/simulation.py backend/app/services/simulation_manager.py backend/tests/test_simulation_agent_api.py
git commit -m "feat(simulation): add PATCH /simulation/{id}/config for Fase B global params"
```

---

## Task 6: `POST /api/simulation/{sim_id}/clone` — clonació de simulació

**Files:**
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/services/simulation_manager.py`
- Test: `backend/tests/test_simulation_clone.py`

- [ ] **Step 1: Escriure el test que falla**

```python
# backend/tests/test_simulation_clone.py
import json
import pytest
from pathlib import Path

@pytest.fixture
def client():
    from backend.app import create_app
    app = create_app({'TESTING': True})
    with app.test_client() as c:
        yield c

@pytest.fixture
def completed_sim(tmp_path, monkeypatch):
    monkeypatch.setenv("OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    sim_id = "sim_src001"
    sim_dir = tmp_path / sim_id
    sim_dir.mkdir()
    state = {
        "simulation_id": sim_id, "project_id": "proj_src", "graph_id": "g1",
        "status": "completed", "entities_count": 2, "profiles_count": 2,
        "entity_types": [], "config_generated": True,
        "parent_simulation_id": None, "graph_id_simulation": None,
    }
    (sim_dir / "state.json").write_text(json.dumps(state))
    profiles = [
        {"user_id": 0, "name": "Alice", "bio": "Bio A", "manually_edited": False},
        {"user_id": 1, "name": "Bob", "bio": "Bio B", "manually_edited": True},
    ]
    (sim_dir / "reddit_profiles.json").write_text(json.dumps(profiles))
    (sim_dir / "twitter_profiles.csv").write_text("user_id,name\n0,Alice\n1,Bob\n")
    (sim_dir / "agent_profiles.json").write_text(json.dumps(profiles))
    (sim_dir / "simulation_config.json").write_text(json.dumps({"time_config": {}}))
    return sim_id

def test_clone_creates_new_simulation(client, completed_sim, monkeypatch):
    src_id = completed_sim
    # Mock ProjectManager to return a minimal project
    import backend.app.models.project as pm_module
    monkeypatch.setattr(pm_module.ProjectManager, "get_project",
                        staticmethod(lambda pid: {"project_id": pid, "graph_id": "g1"}))
    
    resp = client.post(f"/api/simulation/{src_id}/clone", json={"project_id": "proj_src"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "new_simulation_id" in data["data"]
    assert data["data"]["parent_simulation_id"] == src_id

def test_clone_copies_profiles_not_config(client, completed_sim, monkeypatch):
    src_id = completed_sim
    import backend.app.models.project as pm_module
    monkeypatch.setattr(pm_module.ProjectManager, "get_project",
                        staticmethod(lambda pid: {"project_id": pid, "graph_id": "g1"}))
    import os
    sim_data_dir = os.environ["OASIS_SIMULATION_DATA_DIR"]
    
    resp = client.post(f"/api/simulation/{src_id}/clone", json={"project_id": "proj_src"})
    new_sim_id = resp.get_json()["data"]["new_simulation_id"]
    
    new_dir = Path(sim_data_dir) / new_sim_id
    assert (new_dir / "reddit_profiles.json").exists()
    assert (new_dir / "twitter_profiles.csv").exists()
    # simulation_config.json must NOT be copied
    assert not (new_dir / "simulation_config.json").exists()

def test_clone_status_is_profiles_ready(client, completed_sim, monkeypatch):
    src_id = completed_sim
    import backend.app.models.project as pm_module
    monkeypatch.setattr(pm_module.ProjectManager, "get_project",
                        staticmethod(lambda pid: {"project_id": pid, "graph_id": "g1"}))
    import os, json as _json
    sim_data_dir = os.environ["OASIS_SIMULATION_DATA_DIR"]
    
    resp = client.post(f"/api/simulation/{src_id}/clone", json={"project_id": "proj_src"})
    new_sim_id = resp.get_json()["data"]["new_simulation_id"]
    new_state = _json.loads((Path(sim_data_dir) / new_sim_id / "state.json").read_text())
    assert new_state["status"] == "profiles_ready"
    assert new_state["parent_simulation_id"] == src_id
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_clone.py -v
```
Expected: FAIL — endpoint no existeix

- [ ] **Step 3: Afegir `clone_simulation()` a `SimulationManager`**

```python
    def clone_simulation(self, source_simulation_id: str, project_id: str) -> SimulationState:
        """
        Clone an existing simulation: copy agent profile files, set status=profiles_ready,
        record parent_simulation_id. Does NOT copy simulation_config.json.
        """
        source_state = self.get_simulation(source_simulation_id)
        if not source_state:
            raise ValueError(f"Source simulation {source_simulation_id} not found")
        
        if source_state.status == SimulationStatus.CREATED:
            raise ValueError("Cannot clone a simulation in 'created' status (no profiles yet)")

        import uuid
        new_sim_id = f"sim_{uuid.uuid4().hex[:12]}"
        new_state = SimulationState(
            simulation_id=new_sim_id,
            project_id=project_id,
            graph_id=source_state.graph_id,
            enable_twitter=source_state.enable_twitter,
            enable_reddit=source_state.enable_reddit,
            status=SimulationStatus.PROFILES_READY,
            entities_count=source_state.entities_count,
            profiles_count=source_state.profiles_count,
            entity_types=source_state.entity_types,
            config_generated=False,
            parent_simulation_id=source_simulation_id,
        )

        src_dir = self._get_simulation_dir(source_simulation_id)
        dst_dir = self._get_simulation_dir(new_sim_id)

        # Copy profile files only (not simulation_config.json)
        for fname in ("reddit_profiles.json", "twitter_profiles.csv", "agent_profiles.json"):
            src_file = os.path.join(src_dir, fname)
            if os.path.exists(src_file):
                import shutil
                shutil.copy2(src_file, os.path.join(dst_dir, fname))

        self._save_simulation_state(new_state)
        logger.info(f"Cloned simulation {source_simulation_id} -> {new_sim_id} (project={project_id})")
        return new_state
```

- [ ] **Step 4: Afegir l'endpoint `POST /<sim_id>/clone` a `simulation.py`**

```python
@simulation_bp.route('/<simulation_id>/clone', methods=['POST'])
def clone_simulation(simulation_id: str):
    """Clone a simulation: copy agent profiles, set status=profiles_ready."""
    try:
        data = request.get_json() or {}
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({"success": False, "error": t('api.requireProjectId')}), 400
        
        manager = SimulationManager()
        try:
            new_state = manager.clone_simulation(simulation_id, project_id)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        
        return jsonify({
            "success": True,
            "data": {
                "new_simulation_id": new_state.simulation_id,
                "parent_simulation_id": simulation_id,
                "status": new_state.status.value,
            }
        })
    except Exception as e:
        logger.error(f"clone_simulation failed: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 5: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_clone.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/simulation.py backend/app/services/simulation_manager.py backend/tests/test_simulation_clone.py
git commit -m "feat(simulation): add POST /simulation/{id}/clone endpoint with parent_simulation_id"
```

---

## Task 7: Selector de N agents i `prepare` amb `max_agents`

**Files:**
- Modify: `backend/app/services/zep_entity_reader.py`
- Modify: `backend/app/api/simulation.py` (`prepare_simulation`)
- Modify: `backend/app/services/simulation_manager.py` (`prepare_simulation`)
- Test: `backend/tests/test_zep_entity_reader.py` (nou)

- [ ] **Step 1: Escriure el test que falla**

```python
# backend/tests/test_zep_entity_reader.py
import pytest
from unittest.mock import patch, MagicMock
from backend.app.services.zep_entity_reader import ZepEntityReader, EntityNode

def _make_entity(uuid, name, edge_count):
    e = EntityNode(uuid=uuid, name=name, labels=["Person", "Entity"], summary="", attributes={})
    e.related_edges = [{}] * edge_count  # simulate edge_count edges
    return e

def test_get_entities_by_connectivity_returns_top_n():
    reader = ZepEntityReader.__new__(ZepEntityReader)
    entities = [
        _make_entity("u1", "Alice", 10),
        _make_entity("u2", "Bob", 3),
        _make_entity("u3", "Carol", 7),
        _make_entity("u4", "Dave", 1),
        _make_entity("u5", "Eve", 5),
    ]
    
    with patch.object(reader, 'filter_defined_entities') as mock_filter:
        from backend.app.services.zep_entity_reader import FilteredEntities
        mock_filter.return_value = FilteredEntities(
            entities=entities, entity_types=set(), total_count=5, filtered_count=5
        )
        result = reader.get_entities_by_connectivity(graph_id="g1", max_n=3)
    
    assert len(result) == 3
    assert result[0].name == "Alice"   # 10 edges — top
    assert result[1].name == "Carol"   # 7 edges
    assert result[2].name == "Eve"     # 5 edges

def test_get_entities_by_connectivity_no_limit():
    reader = ZepEntityReader.__new__(ZepEntityReader)
    entities = [_make_entity(f"u{i}", f"E{i}", i) for i in range(5)]
    with patch.object(reader, 'filter_defined_entities') as mock_filter:
        from backend.app.services.zep_entity_reader import FilteredEntities
        mock_filter.return_value = FilteredEntities(
            entities=entities, entity_types=set(), total_count=5, filtered_count=5
        )
        result = reader.get_entities_by_connectivity(graph_id="g1", max_n=None)
    assert len(result) == 5
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_zep_entity_reader.py -v
```
Expected: FAIL — mètode no existeix

- [ ] **Step 3: Afegir `get_entities_by_connectivity` a `ZepEntityReader`**

Al final de la classe `ZepEntityReader` (a `zep_entity_reader.py`), afegeix:

```python
    def get_entities_by_connectivity(
        self,
        graph_id: str,
        max_n: Optional[int] = None,
        defined_entity_types: Optional[List[str]] = None,
    ) -> List[EntityNode]:
        """
        Return entities sorted by edge degree (descending), optionally capped at max_n.
        Most-connected entities generate richer simulations.
        """
        filtered = self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=defined_entity_types,
            enrich_with_edges=True,
        )
        entities = sorted(
            filtered.entities,
            key=lambda e: len(e.related_edges),
            reverse=True,
        )
        if max_n is not None and max_n > 0:
            entities = entities[:max_n]
        return entities
```

- [ ] **Step 4: Afegir `max_agents` a `POST /api/simulation/prepare`**

Localitza el paràmetre `entity_types_list = data.get('entity_types')` a la funció `prepare_simulation()` i afegeix just a sota:

```python
        max_agents = data.get('max_agents')  # optional: limit to top-N most-connected entities
```

Localitza la crida a `manager.prepare_simulation(` i afegeix el paràmetre `max_agents=max_agents` a la llista d'arguments.

- [ ] **Step 5: Afegir `max_agents` a `SimulationManager.prepare_simulation()`**

Localitza la signatura de `def prepare_simulation(` a `simulation_manager.py` i afegeix `max_agents: Optional[int] = None` als paràmetres. Dins del cos, just abans de la lectura d'entitats, afegeix:

```python
        if max_agents and max_agents > 0:
            logger.info(f"Limiting entities to top-{max_agents} by connectivity")
            entities = reader.get_entities_by_connectivity(
                graph_id=state.graph_id,
                max_n=max_agents,
                defined_entity_types=defined_entity_types,
            )
            # Wrap into FilteredEntities for downstream code
            from .zep_entity_reader import FilteredEntities
            filtered_entities = FilteredEntities(
                entities=entities,
                entity_types={e.get_entity_type() for e in entities if e.get_entity_type()},
                total_count=len(entities),
                filtered_count=len(entities),
            )
        else:
            filtered_entities = reader.filter_defined_entities(...)  # existing call
```

*Nota: el codi existent a `prepare_simulation` fa la crida a `filter_defined_entities`; cal envolicar-la en un `else` o substituir-la pel bloc anterior.*

- [ ] **Step 6: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_zep_entity_reader.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/zep_entity_reader.py backend/app/api/simulation.py backend/app/services/simulation_manager.py backend/tests/test_zep_entity_reader.py
git commit -m "feat(simulation): add max_agents selector via top-N connectivity in prepare"
```

---

## Task 8: `POST /api/simulation/{sim_id}/agent` — creació d'agent

**Files:**
- Modify: `backend/app/api/simulation.py`
- Modify: `backend/app/services/simulation_manager.py`
- Test: `backend/tests/test_simulation_agent_api.py` (ampliar)

- [ ] **Step 1: Afegir test que falla**

```python
def test_create_agent_adds_to_profiles(client, sim_with_profiles, monkeypatch):
    sim_id = sim_with_profiles
    
    # Mock the entity reader and profile generator
    import backend.app.services.simulation_manager as sm_module
    from backend.app.services.zep_entity_reader import EntityNode
    
    fake_entity = EntityNode(
        uuid="uuid_carol", name="Carol", labels=["Person", "Entity"],
        summary="Carol is a scientist", attributes={}
    )
    
    def fake_get_entity(self, graph_id, uuid_):
        return fake_entity
    
    monkeypatch.setattr(
        "backend.app.services.zep_entity_reader.ZepEntityReader.get_entity_with_context",
        fake_get_entity
    )
    
    # Mock profile generator
    from backend.app.services.oasis_profile_generator import OasisAgentProfile
    fake_profile = OasisAgentProfile(user_id=99, user_name="carol", name="Carol",
                                      bio="Carol bio", persona="Scientist",
                                      source_entity_uuid="uuid_carol")
    
    monkeypatch.setattr(
        "backend.app.services.oasis_profile_generator.OasisProfileGenerator.generate_profile_from_entity",
        lambda self, entity, extra_instructions=None: fake_profile
    )
    
    resp = client.post(f"/api/simulation/{sim_id}/agent",
                       json={"source_entity_uuid": "uuid_carol", "extra_instructions": "Make her skeptical"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py::test_create_agent_adds_to_profiles -v
```
Expected: FAIL — endpoint no existeix

- [ ] **Step 3: Exposar `generate_profile_from_entity` a `OasisProfileGenerator`**

Obre `backend/app/services/oasis_profile_generator.py`. Localitza el mètode que genera un perfil per a una entitat (probablement privat o part d'un loop). Afegeix/verifica un mètode públic:

```python
    def generate_profile_from_entity(
        self,
        entity: 'EntityNode',
        extra_instructions: Optional[str] = None,
    ) -> 'OasisAgentProfile':
        """
        Generate a single OasisAgentProfile from an EntityNode.
        Calls the same LLM logic as the batch generator.
        If extra_instructions is provided, appends them to the generation prompt.
        """
        # Delegate to the existing single-entity generation logic.
        # The existing code typically calls _generate_profile_with_llm or similar.
        # Pass extra_instructions as part of the context.
        return self._generate_single_profile(entity, extra_instructions=extra_instructions)
```

*Nota: si el mètode intern té un nom diferent, renomena la crida. Inspeccioneu el codi existent i ajusteu.*

- [ ] **Step 4: Afegir l'endpoint `POST /<sim_id>/agent` a `simulation.py`**

```python
@simulation_bp.route('/<simulation_id>/agent', methods=['POST'])
def create_agent(simulation_id: str):
    """
    Create a new agent from an existing graph entity (Fase A).
    Returns task_id for polling (generation is async).
    """
    import threading
    from ..models.task import TaskManager, TaskStatus
    from ..services.zep_entity_reader import ZepEntityReader
    from ..services.oasis_profile_generator import OasisProfileGenerator

    try:
        data = request.get_json() or {}
        source_entity_uuid = data.get('source_entity_uuid')
        extra_instructions = data.get('extra_instructions', '')

        if not source_entity_uuid:
            return jsonify({"success": False, "error": t('api.requireEntityUuid')}), 400

        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if not state:
            return jsonify({"success": False, "error": t('api.simulationNotFound', id=simulation_id)}), 404

        allowed_statuses = {SimulationStatus.PROFILES_READY, SimulationStatus.CREATED}
        if state.status not in allowed_statuses:
            return jsonify({
                "success": False,
                "error": t('api.cannotCreateAgentInStatus', status=state.status.value)
            }), 400

        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="create_agent",
            metadata={"simulation_id": simulation_id, "source_entity_uuid": source_entity_uuid}
        )

        current_locale = get_locale()

        def run_create_agent():
            set_locale(current_locale)
            try:
                task_manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=0,
                                         message="Generating new agent profile...")
                reader = ZepEntityReader()
                entity = reader.get_entity_with_context(state.graph_id, source_entity_uuid)
                if not entity:
                    task_manager.fail_task(task_id, f"Entity {source_entity_uuid} not found in graph")
                    return

                # Load existing profiles to check for duplicates and get next user_id
                sim_dir = manager._get_simulation_dir(simulation_id)
                profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)

                # Check entity not already assigned
                if any(p.get("source_entity_uuid") == source_entity_uuid for p in profiles):
                    task_manager.fail_task(task_id, "Entity already has an agent assigned")
                    return

                next_user_id = max((p.get("user_id", 0) for p in profiles), default=-1) + 1

                gen = OasisProfileGenerator(graph_id=state.graph_id)
                profile = gen.generate_profile_from_entity(entity, extra_instructions=extra_instructions)
                profile.user_id = next_user_id

                profile_dict = profile.to_reddit_format()
                profile_dict["source_entity_uuid"] = source_entity_uuid
                profile_dict["manually_edited"] = False

                profiles.append(profile_dict)
                import shutil
                backup = profiles_file + ".bak"
                shutil.copy2(profiles_file, backup)
                try:
                    with open(profiles_file, 'w', encoding='utf-8') as f:
                        json.dump(profiles, f, ensure_ascii=False, indent=2)
                    os.remove(backup)
                except Exception:
                    shutil.copy2(backup, profiles_file)
                    os.remove(backup)
                    raise

                task_manager.complete_task(task_id, result=profile_dict)
            except Exception as e:
                logger.error(f"create_agent background failed: {e}")
                task_manager.fail_task(task_id, str(e))

        threading.Thread(target=run_create_agent, daemon=True).start()

        return jsonify({"success": True, "data": {"simulation_id": simulation_id, "task_id": task_id}})
    except Exception as e:
        logger.error(f"create_agent endpoint error: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 5: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py -v
```
Expected: PASS (8+ tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/simulation.py backend/app/services/oasis_profile_generator.py backend/tests/test_simulation_agent_api.py
git commit -m "feat(simulation): add POST /simulation/{id}/agent for new agent creation"
```

---

## Task 9: `POST /api/simulation/{sim_id}/agent/{user_id}/regenerate` — regeneració d'agent

**Files:**
- Modify: `backend/app/api/simulation.py`
- Test: `backend/tests/test_simulation_agent_api.py` (ampliar)

- [ ] **Step 1: Afegir test que falla**

```python
def test_regenerate_agent_returns_task_id(client, sim_with_profiles, monkeypatch):
    sim_id = sim_with_profiles
    from backend.app.services.zep_entity_reader import EntityNode
    fake_entity = EntityNode(uuid="uuid_alice", name="Alice", labels=["Entity"], summary="", attributes={})
    monkeypatch.setattr(
        "backend.app.services.zep_entity_reader.ZepEntityReader.get_entity_with_context",
        lambda self, g, u: fake_entity
    )
    from backend.app.services.oasis_profile_generator import OasisAgentProfile
    fake_profile = OasisAgentProfile(user_id=0, user_name="alice2", name="Alice2",
                                      bio="New bio", persona="Skeptic",
                                      source_entity_uuid="uuid_alice")
    monkeypatch.setattr(
        "backend.app.services.oasis_profile_generator.OasisProfileGenerator.generate_profile_from_entity",
        lambda self, entity, extra_instructions=None: fake_profile
    )
    
    # Need source_entity_uuid in profile
    import json as _j
    from pathlib import Path
    import os
    sim_dir = Path(os.environ["OASIS_SIMULATION_DATA_DIR"]) / sim_id
    profiles = _j.loads((sim_dir / "reddit_profiles.json").read_text())
    profiles[0]["source_entity_uuid"] = "uuid_alice"
    (sim_dir / "reddit_profiles.json").write_text(_j.dumps(profiles))
    
    resp = client.post(f"/api/simulation/{sim_id}/agent/0/regenerate",
                       json={"extra_instructions": "Make her skeptical"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert "task_id" in data["data"]
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py::test_regenerate_agent_returns_task_id -v
```
Expected: FAIL

- [ ] **Step 3: Afegir l'endpoint `POST /<sim_id>/agent/<user_id>/regenerate` a `simulation.py`**

```python
@simulation_bp.route('/<simulation_id>/agent/<int:user_id>/regenerate', methods=['POST'])
def regenerate_agent(simulation_id: str, user_id: int):
    """
    Regenerate a single agent's personality profile.
    Only available when status=profiles_ready.
    Returns task_id for polling.
    """
    import threading
    from ..models.task import TaskManager, TaskStatus
    from ..services.zep_entity_reader import ZepEntityReader
    from ..services.oasis_profile_generator import OasisProfileGenerator

    try:
        data = request.get_json() or {}
        extra_instructions = data.get('extra_instructions', '')

        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if not state:
            return jsonify({"success": False, "error": t('api.simulationNotFound', id=simulation_id)}), 404

        if state.status != SimulationStatus.PROFILES_READY:
            return jsonify({
                "success": False,
                "error": t('api.regenerateRequiresProfilesReady', status=state.status.value)
            }), 400

        # Verify agent exists and has source_entity_uuid
        sim_dir = manager._get_simulation_dir(simulation_id)
        profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        with open(profiles_file, 'r', encoding='utf-8') as f:
            profiles = json.load(f)

        target = next((p for p in profiles if p.get("user_id") == user_id), None)
        if not target:
            return jsonify({"success": False, "error": t('api.agentNotFound', user_id=user_id)}), 404

        source_entity_uuid = target.get("source_entity_uuid")
        if not source_entity_uuid:
            return jsonify({"success": False, "error": t('api.agentNoSourceEntity')}), 400

        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="regenerate_agent",
            metadata={"simulation_id": simulation_id, "user_id": user_id}
        )
        current_locale = get_locale()

        def run_regenerate():
            set_locale(current_locale)
            try:
                task_manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=0,
                                         message="Regenerating agent profile...")
                reader = ZepEntityReader()
                entity = reader.get_entity_with_context(state.graph_id, source_entity_uuid)
                if not entity:
                    task_manager.fail_task(task_id, f"Entity {source_entity_uuid} not found")
                    return

                gen = OasisProfileGenerator(graph_id=state.graph_id)
                new_profile = gen.generate_profile_from_entity(entity, extra_instructions=extra_instructions)
                new_profile_dict = new_profile.to_reddit_format()
                new_profile_dict["user_id"] = user_id
                new_profile_dict["source_entity_uuid"] = source_entity_uuid
                new_profile_dict["manually_edited"] = False  # freshly regenerated

                # Reload and update profiles
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    current_profiles = json.load(f)
                for i, p in enumerate(current_profiles):
                    if p.get("user_id") == user_id:
                        current_profiles[i] = new_profile_dict
                        break

                import shutil
                backup = profiles_file + ".bak"
                shutil.copy2(profiles_file, backup)
                try:
                    with open(profiles_file, 'w', encoding='utf-8') as f:
                        json.dump(current_profiles, f, ensure_ascii=False, indent=2)
                    os.remove(backup)
                except Exception:
                    shutil.copy2(backup, profiles_file)
                    os.remove(backup)
                    raise

                task_manager.complete_task(task_id, result=new_profile_dict)
            except Exception as e:
                logger.error(f"regenerate_agent background failed: {e}")
                task_manager.fail_task(task_id, str(e))

        threading.Thread(target=run_regenerate, daemon=True).start()

        return jsonify({"success": True, "data": {"simulation_id": simulation_id, "task_id": task_id}})
    except Exception as e:
        logger.error(f"regenerate_agent endpoint error: {e}")
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 4: Executar els tests**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_simulation_agent_api.py -v
```
Expected: PASS (9+ tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/simulation.py backend/tests/test_simulation_agent_api.py
git commit -m "feat(simulation): add POST /simulation/{id}/agent/{user_id}/regenerate"
```

---

## Task 10: Subsistema 5 — `clone_graph` i `delete_graph` a `GraphitiBackend`

**Files:**
- Modify: `backend/app/graph/graphiti_backend.py`
- Test: `backend/tests/test_graph_clone.py` (nou)

**Nota prèvia:** Aquest task requereix Neo4j/Graphiti actiu. Si l'entorn de test no té Neo4j, els tests han d'usar mocks del driver Neo4j.

- [ ] **Step 1: Escriure el test que falla**

```python
# backend/tests/test_graph_clone.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

def test_clone_graph_executes_two_queries(monkeypatch):
    """clone_graph should run exactly 2 Cypher queries: one for nodes, one for relationships."""
    from backend.app.graph.graphiti_backend import GraphitiBackend
    
    backend = GraphitiBackend.__new__(GraphitiBackend)
    
    executed_queries = []
    async def fake_execute_query(query, parameters=None, **kwargs):
        executed_queries.append(query)
        return []
    
    with patch.object(backend, '_execute_neo4j_query', new=fake_execute_query):
        import asyncio
        # Use the sync wrapper _run_async if available, or run directly
        backend._run_sync(backend.clone_graph("src_group", "dst_group"))
    
    assert len(executed_queries) == 2
    assert "group_id" in executed_queries[0].lower() or "group_id" in executed_queries[1].lower()

def test_delete_graph_executes_detach_delete(monkeypatch):
    """delete_graph should run a DETACH DELETE query."""
    from backend.app.graph.graphiti_backend import GraphitiBackend
    
    backend = GraphitiBackend.__new__(GraphitiBackend)
    
    executed_queries = []
    async def fake_execute_query(query, parameters=None, **kwargs):
        executed_queries.append(query)
        return []
    
    with patch.object(backend, '_execute_neo4j_query', new=fake_execute_query):
        backend._run_sync(backend.delete_graph("group_to_delete"))
    
    assert any("DETACH DELETE" in q for q in executed_queries)
```

- [ ] **Step 2: Executar per verificar que falla**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_graph_clone.py -v
```
Expected: FAIL — mètodes no existeixen

- [ ] **Step 3: Afegir `clone_graph`, `delete_graph` i `_run_sync` a `GraphitiBackend`**

Al final de la classe `GraphitiBackend` (a `graphiti_backend.py`), afegeix:

```python
    def _run_sync(self, coro):
        """Run an async coroutine synchronously (convenience wrapper for tests and sync callers)."""
        return _run_async(coro)

    async def _execute_neo4j_query(self, query: str, parameters: dict = None):
        """Execute a raw Cypher query against Neo4j using the Graphiti driver."""
        # Access the underlying Neo4j driver via graphiti's internal driver
        driver = self._client.driver
        async with driver.session() as session:
            result = await session.run(query, parameters or {})
            return await result.data()

    async def clone_graph(self, src_group_id: str, dst_group_id: str) -> None:
        """
        Clone all nodes and relationships from src_group_id to dst_group_id.
        Uses APOC for relationship cloning (available on Neo4j Aura Cloud by default).
        """
        logger.info(f"Cloning graph: {src_group_id} -> {dst_group_id}")

        # Step 1: Clone nodes
        clone_nodes_query = """
            MATCH (n) WHERE n.group_id = $src
            WITH n, properties(n) AS props
            CREATE (m) SET m = props SET m.group_id = $dst
        """
        await self._execute_neo4j_query(clone_nodes_query, {"src": src_group_id, "dst": dst_group_id})

        # Step 2: Clone relationships (requires APOC)
        clone_rels_query = """
            MATCH (n)-[r]->(m)
            WHERE n.group_id = $src AND m.group_id = $src
            MATCH (n2 {uuid: n.uuid, group_id: $dst})
            MATCH (m2 {uuid: m.uuid, group_id: $dst})
            CALL apoc.create.relationship(n2, type(r), properties(r), m2) YIELD rel
            SET rel.group_id = $dst
            RETURN rel
        """
        await self._execute_neo4j_query(clone_rels_query, {"src": src_group_id, "dst": dst_group_id})
        logger.info(f"Graph cloned successfully: {src_group_id} -> {dst_group_id}")

    async def delete_graph(self, group_id: str) -> None:
        """Delete all nodes (and their relationships) for a given group_id."""
        logger.info(f"Deleting graph: {group_id}")
        delete_query = """
            MATCH (n) WHERE n.group_id = $gid DETACH DELETE n
        """
        await self._execute_neo4j_query(delete_query, {"gid": group_id})
        logger.info(f"Graph deleted: {group_id}")
```

- [ ] **Step 4: Executar els tests (amb mocks)**

```bash
cd /home/ubuntu/dev/MiroFish && python -m pytest backend/tests/test_graph_clone.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/graphiti_backend.py backend/tests/test_graph_clone.py
git commit -m "feat(graph): add clone_graph and delete_graph to GraphitiBackend via APOC"
```

---

## Task 11: Integrar `clone_graph` a `POST /start` i `graph_id_simulation` al report

**Files:**
- Modify: `backend/app/api/simulation.py` (funció `start_simulation`)
- Modify: `backend/app/api/report.py`
- Test: `backend/tests/test_simulation_clone.py` (ampliar)

- [ ] **Step 1: Afegir test que falla**

```python
# Afegeix a backend/tests/test_simulation_clone.py
def test_start_simulation_sets_graph_id_simulation(client, sim_prepared_ready, monkeypatch):
    """When enable_graph_memory_update=true, start should clone graph and save graph_id_simulation."""
    sim_id = sim_prepared_ready  # fixture amb status=ready
    
    from backend.app.graph import factory as graph_factory
    mock_backend = MagicMock()
    mock_backend.clone_graph = AsyncMock(return_value=None)
    monkeypatch.setattr(graph_factory, "get_graph_backend", lambda: mock_backend)
    
    # Also mock SimulationRunner.start_simulation
    import backend.app.services.simulation_runner as runner_module
    fake_run_state = MagicMock()
    fake_run_state.to_dict.return_value = {"runner_status": "running"}
    monkeypatch.setattr(runner_module.SimulationRunner, "start_simulation",
                        staticmethod(lambda **kw: fake_run_state))
    
    import backend.app.models.project as pm_module
    monkeypatch.setattr(pm_module.ProjectManager, "get_project",
                        staticmethod(lambda pid: {"project_id": pid, "graph_id": "g1"}))
    
    resp = client.post("/api/simulation/start", json={
        "simulation_id": sim_id,
        "enable_graph_memory_update": True,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    # graph_id_simulation should be in response or saved to state
    # At minimum, clone_graph should have been called
    mock_backend.clone_graph.assert_called_once()
```

*(Nota: afegir el fixture `sim_prepared_ready` similar a `completed_sim` però amb `status=ready` i `config_generated=True`)*

- [ ] **Step 2: Modificar `start_simulation()` a `simulation.py`**

Just abans de la crida `run_state = SimulationRunner.start_simulation(...)`, afegeix el bloc de clonació de graf:

```python
        # Clone graph for per-simulation isolation (if graph memory update is enabled)
        if enable_graph_memory_update and graph_id:
            try:
                graph_id_sim = f"mirofish_{simulation_id}_sim"
                from ..graph import get_graph_backend
                graph_backend = get_graph_backend()
                if hasattr(graph_backend, 'clone_graph'):
                    _run_async_if_needed(graph_backend.clone_graph(graph_id, graph_id_sim))
                    # Save graph_id_simulation to state
                    state.graph_id_simulation = graph_id_sim
                    manager._save_simulation_state(state)
                    graph_id = graph_id_sim  # simulations write to the cloned graph
                    logger.info(f"Graph cloned for simulation: {graph_id_sim}")
            except Exception as e:
                logger.warning(f"Graph cloning failed (simulation will use shared graph): {e}")
```

Afegeix la funció helper al mòdul (fora de qualsevol classe):

```python
def _run_async_if_needed(coro):
    """Run a coroutine synchronously from a sync Flask context."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)
```

- [ ] **Step 3: Modificar `report.py` per passar `graph_id_simulation`**

Localitza la funció que crida `ReportAgent` a `report.py`. Abans de la crida, afegeix:

```python
        # Use per-simulation graph if available, else fall back to document graph
        effective_graph_id = sim_state.graph_id_simulation or sim_state.graph_id
        # Pass effective_graph_id to ReportAgent instead of the original graph_id
```

*(El canvi exacte depèn de com `report.py` instancia `ReportAgent` — cal llegir la signatura del constructor de `ReportAgent` i adaptar.)*

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/simulation.py backend/app/api/report.py
git commit -m "feat(simulation): clone graph on start when enable_graph_memory_update=true, pass graph_id_simulation to report"
```

---

## Task 12: Afegir 7 noves crides a `frontend/src/api/simulation.js`

**Files:**
- Modify: `frontend/src/api/simulation.js`

- [ ] **Step 1: Afegir les noves funcions al final del fitxer**

```javascript
/**
 * Update an agent's profile fields (Fase A/B)
 * @param {string} simulationId
 * @param {number} userId
 * @param {Object} fields - partial profile fields to update
 */
export const patchAgent = (simulationId, userId, fields) => {
  return service.patch(`/api/simulation/${simulationId}/agent/${userId}`, fields)
}

/**
 * Delete an agent from a simulation
 * @param {string} simulationId
 * @param {number} userId
 */
export const deleteAgent = (simulationId, userId) => {
  return service.delete(`/api/simulation/${simulationId}/agent/${userId}`)
}

/**
 * Create a new agent from an existing graph entity
 * @param {string} simulationId
 * @param {Object} data - { source_entity_uuid, extra_instructions? }
 */
export const createAgent = (simulationId, data) => {
  return requestWithRetry(() => service.post(`/api/simulation/${simulationId}/agent`, data), 3, 1000)
}

/**
 * Regenerate an agent's personality profile
 * @param {string} simulationId
 * @param {number} userId
 * @param {Object} data - { extra_instructions? }
 */
export const regenerateAgent = (simulationId, userId, data = {}) => {
  return requestWithRetry(() => service.post(`/api/simulation/${simulationId}/agent/${userId}/regenerate`, data), 3, 1000)
}

/**
 * Trigger Fase A → Fase B transition (generate behavior config)
 * @param {string} simulationId
 */
export const generateConfig = (simulationId) => {
  return requestWithRetry(() => service.post(`/api/simulation/${simulationId}/generate-config`, {}), 3, 1000)
}

/**
 * Update simulation global config parameters (Fase B)
 * @param {string} simulationId
 * @param {Object} fields - partial config fields
 */
export const patchSimulationConfig = (simulationId, fields) => {
  return service.patch(`/api/simulation/${simulationId}/config`, fields)
}

/**
 * Clone a simulation (copy agent profiles, set status=profiles_ready)
 * @param {string} simulationId - source simulation ID
 * @param {string} projectId
 */
export const cloneSimulation = (simulationId, projectId) => {
  return requestWithRetry(() => service.post(`/api/simulation/${simulationId}/clone`, { project_id: projectId }), 3, 1000)
}
```

- [ ] **Step 2: Verificar sintaxi**

```bash
cd /home/ubuntu/dev/MiroFish/frontend && node --input-type=module < /dev/null || npx eslint src/api/simulation.js --no-eslintrc --rule '{}' 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/simulation.js
git commit -m "feat(frontend-api): add 7 new simulation API calls for F2-A+B"
```

---

## Task 13: Traduccions noves per a F2-A+B

**Files:**
- Modify: `locales/en.json`
- Modify: `locales/zh.json`

- [ ] **Step 1: Afegir claus a `locales/en.json`**

Localitza la secció `"step2"` i afegeix les noves claus:

```json
"step2": {
  "...claus existents...",
  "agentCount": "Number of Agents",
  "agentCountHint": "Select entities by graph connectivity (most connected first)",
  "agentCountWarning": "Fewer than 15 agents may produce less rich simulations",
  "phaseATitle": "Agent Personalities",
  "phaseASubtitle": "Review and edit generated agent profiles",
  "continueToPhaseB": "Continue →",
  "phaseBTitle": "Simulation Parameters",
  "phaseBSubtitle": "Edit behavior parameters and simulation settings",
  "launchSimulation": "Launch Simulation",
  "editAgent": "Edit",
  "deleteAgent": "Delete",
  "deleteAgentConfirm": "Delete this agent? This cannot be undone.",
  "regenerateAgent": "Regenerate",
  "regenerateAgentHint": "Extra instructions (optional)",
  "createAgent": "Add Agent",
  "createAgentTitle": "Add New Agent",
  "selectEntityType": "Entity Type",
  "selectEntity": "Select Entity",
  "extraInstructions": "Extra Instructions (optional)",
  "manuallyEditedBadge": "Edited",
  "generatingConfig": "Generating behavior config...",
  "cloneFrom": "Clone from previous simulation",
  "newSimulation": "New simulation",
  "simulationSource": "Simulation Source",
  "behaviorParams": "Behavior Parameters",
  "globalParams": "Global Parameters",
  "totalHours": "Total Hours",
  "minutesPerRound": "Minutes per Round",
  "followingProbability": "Following Probability",
  "recsysType": "Recommendation System"
}
```

Afegeix a la secció `"api"`:

```json
"api": {
  "...claus existents...",
  "requireFields": "No fields provided",
  "requireEntityUuid": "source_entity_uuid is required",
  "requireProfilesReady": "Simulation must be in profiles_ready status (current: {status})",
  "requireAgentId": "agent user_id is required",
  "agentNotFound": "Agent user_id={user_id} not found",
  "agentNoSourceEntity": "Agent has no source_entity_uuid — cannot regenerate",
  "cannotCreateAgentInStatus": "Cannot create agent when simulation status is {status}",
  "regenerateRequiresProfilesReady": "Regenerate requires profiles_ready status (current: {status})"
}
```

- [ ] **Step 2: Afegir les mateixes claus a `locales/zh.json`**

Afegeix les traduccions corresponents a les mateixes seccions:

```json
"step2": {
  "...claus existents...",
  "agentCount": "智能体数量",
  "agentCountHint": "按图谱连接度排序（连接最多的优先）",
  "agentCountWarning": "少于15个智能体可能导致模拟不够丰富",
  "phaseATitle": "智能体个性",
  "phaseASubtitle": "查看并编辑生成的智能体档案",
  "continueToPhaseB": "继续 →",
  "phaseBTitle": "模拟参数",
  "phaseBSubtitle": "编辑行为参数和模拟设置",
  "launchSimulation": "启动模拟",
  "editAgent": "编辑",
  "deleteAgent": "删除",
  "deleteAgentConfirm": "删除此智能体？此操作不可撤销。",
  "regenerateAgent": "重新生成",
  "regenerateAgentHint": "额外说明（可选）",
  "createAgent": "添加智能体",
  "createAgentTitle": "添加新智能体",
  "selectEntityType": "实体类型",
  "selectEntity": "选择实体",
  "extraInstructions": "额外说明（可选）",
  "manuallyEditedBadge": "已编辑",
  "generatingConfig": "正在生成行为配置...",
  "cloneFrom": "从已有模拟克隆",
  "newSimulation": "新模拟",
  "simulationSource": "模拟来源",
  "behaviorParams": "行为参数",
  "globalParams": "全局参数",
  "totalHours": "总小时数",
  "minutesPerRound": "每轮分钟数",
  "followingProbability": "关注概率",
  "recsysType": "推荐系统类型"
}
```

```json
"api": {
  "...claus existents...",
  "requireFields": "未提供字段",
  "requireEntityUuid": "需要 source_entity_uuid",
  "requireProfilesReady": "模拟必须处于 profiles_ready 状态（当前：{status}）",
  "requireAgentId": "需要 agent user_id",
  "agentNotFound": "未找到 user_id={user_id} 的智能体",
  "agentNoSourceEntity": "智能体没有 source_entity_uuid，无法重新生成",
  "cannotCreateAgentInStatus": "模拟状态为 {status} 时无法创建智能体",
  "regenerateRequiresProfilesReady": "重新生成需要 profiles_ready 状态（当前：{status}）"
}
```

- [ ] **Step 3: Commit**

```bash
git add locales/en.json locales/zh.json
git commit -m "feat(i18n): add F2-A+B translation keys for en and zh"
```

---

## Task 14: Frontend — Fase A: modal d'edició i control de generació

**Files:**
- Modify: `frontend/src/components/Step2EnvSetup.vue`

Aquesta és la tasca de frontend més gran. Cal refactoritzar el component existent per suportar les dues fases. El principi és: **canviar el mínim possible del flux existent** i afegir les pantalles de Fase A/B al damunt.

- [ ] **Step 1: Afegir refs de fase i modal a la secció `<script setup>`**

Localitza el bloc de refs de `Step2EnvSetup.vue` i afegeix:

```javascript
import { patchAgent, deleteAgent, regenerateAgent, generateConfig } from '../api/simulation'

// Fase A/B state
const currentPhase = ref('generating') // 'generating' | 'phase_a' | 'phase_b'
const agentModalOpen = ref(false)
const agentModalMode = ref('view')    // 'view' | 'edit' | 'regen'
const selectedAgent = ref(null)
const editForm = ref({})
const regenInstructions = ref('')
const regenLoading = ref(false)
const editLoading = ref(false)
const deleteConfirmAgent = ref(null)
const generateConfigLoading = ref(false)
const generateConfigTaskId = ref(null)
```

- [ ] **Step 2: Detectar la transició a `phase_a` quan la generació es completa**

Localitza el codi que processa la fi de la generació (`status === 'ready'` o `config_generated === true`) i afegeix:

```javascript
// Quan la generació de perfils s'acaba (status = profiles_ready)
// canvia a la fase A en lloc d'anar directament a "prepared"
if (data.status === 'profiles_ready' || (data.status === 'preparing' && profilesGenerated)) {
  currentPhase.value = 'phase_a'
}
```

Nota: cal ajustar el backend per retornar `profiles_ready` al final de la generació de perfils (abans de generar la config). Això implica modificar `SimulationManager.prepare_simulation()` per aturar-se a `profiles_ready` en lloc de continuar amb la config.

- [ ] **Step 3: Afegir funcions `openAgentModal`, `saveAgent`, `confirmDelete`, `doRegenerate`**

```javascript
const openAgentModal = (agent, mode = 'view') => {
  selectedAgent.value = agent
  agentModalMode.value = mode
  editForm.value = { ...agent }
  regenInstructions.value = ''
  agentModalOpen.value = true
}

const closeAgentModal = () => {
  agentModalOpen.value = false
  selectedAgent.value = null
}

const saveAgent = async () => {
  if (!selectedAgent.value || !simulationId.value) return
  editLoading.value = true
  try {
    const res = await patchAgent(simulationId.value, selectedAgent.value.user_id, editForm.value)
    if (res.data.success) {
      // Update agent in local profiles list
      const idx = profiles.value.findIndex(p => p.user_id === selectedAgent.value.user_id)
      if (idx !== -1) profiles.value[idx] = res.data.data
      closeAgentModal()
    }
  } finally {
    editLoading.value = false
  }
}

const confirmDeleteAgent = async (agent) => {
  if (!confirm(t('step2.deleteAgentConfirm'))) return
  const res = await deleteAgent(simulationId.value, agent.user_id)
  if (res.data.success) {
    profiles.value = profiles.value.filter(p => p.user_id !== agent.user_id)
  }
}

const doRegenerate = async () => {
  if (!selectedAgent.value) return
  regenLoading.value = true
  try {
    const res = await regenerateAgent(simulationId.value, selectedAgent.value.user_id, {
      extra_instructions: regenInstructions.value
    })
    if (res.data.success) {
      // Poll task until complete, then refresh profiles
      await pollTaskUntilDone(res.data.data.task_id, () => refreshProfiles())
      closeAgentModal()
    }
  } finally {
    regenLoading.value = false
  }
}

const continueToPhaseB = async () => {
  generateConfigLoading.value = true
  try {
    const res = await generateConfig(simulationId.value)
    if (res.data.success) {
      generateConfigTaskId.value = res.data.data.task_id
      // Poll until task completes → then switch to phase_b
      await pollTaskUntilDone(res.data.data.task_id, () => {
        currentPhase.value = 'phase_b'
      })
    }
  } finally {
    generateConfigLoading.value = false
  }
}
```

Helper de polling (si no existeix ja al component):

```javascript
const pollTaskUntilDone = async (taskId, onComplete, intervalMs = 2000) => {
  const { getPrepareStatus } = await import('../api/simulation')
  return new Promise((resolve) => {
    const interval = setInterval(async () => {
      try {
        const res = await getPrepareStatus({ task_id: taskId })
        const status = res.data?.data?.status
        if (status === 'completed') {
          clearInterval(interval)
          onComplete && onComplete(res.data?.data?.result)
          resolve()
        } else if (status === 'failed') {
          clearInterval(interval)
          resolve()
        }
      } catch {
        clearInterval(interval)
        resolve()
      }
    }, intervalMs)
  })
}
```

- [ ] **Step 4: Afegir el botó "Continuar →" al template**

Localitza la secció on es mostren les cards d'agents (dins la condició de generació completa) i afegeix just a sota:

```vue
<!-- Fase A: botó de continuació -->
<div v-if="currentPhase === 'phase_a'" class="phase-a-footer">
  <button 
    class="continue-btn" 
    :disabled="generateConfigLoading"
    @click="continueToPhaseB"
  >
    <span v-if="generateConfigLoading">{{ $t('step2.generatingConfig') }}</span>
    <span v-else>{{ $t('step2.continueToPhaseB') }}</span>
  </button>
</div>
```

- [ ] **Step 5: Afegir el modal d'edició d'agent al template**

```vue
<!-- Agent edit/regen modal -->
<div v-if="agentModalOpen" class="agent-modal-overlay" @click.self="closeAgentModal">
  <div class="agent-modal">
    <div class="modal-header">
      <span class="modal-title">{{ selectedAgent?.name }}</span>
      <span v-if="selectedAgent?.manually_edited" class="edited-badge">{{ $t('step2.manuallyEditedBadge') }}</span>
      <button class="modal-close" @click="closeAgentModal">✕</button>
    </div>
    
    <div v-if="agentModalMode === 'edit'" class="modal-body">
      <div class="field-group" v-for="field in ['name', 'bio', 'persona', 'age', 'gender', 'mbti', 'country', 'profession', 'stance']" :key="field">
        <label>{{ field }}</label>
        <textarea v-if="['bio', 'persona'].includes(field)" v-model="editForm[field]" rows="3" />
        <input v-else v-model="editForm[field]" />
      </div>
      <div class="modal-actions">
        <button class="btn-secondary" @click="closeAgentModal">{{ $t('common.cancel') }}</button>
        <button class="btn-primary" :disabled="editLoading" @click="saveAgent">{{ $t('common.save') }}</button>
      </div>
    </div>
    
    <div v-else-if="agentModalMode === 'regen'" class="modal-body">
      <p>{{ $t('step2.regenerateAgentHint') }}</p>
      <textarea v-model="regenInstructions" rows="3" :placeholder="$t('step2.extraInstructions')" />
      <div class="modal-actions">
        <button class="btn-secondary" @click="closeAgentModal">{{ $t('common.cancel') }}</button>
        <button class="btn-primary" :disabled="regenLoading" @click="doRegenerate">{{ $t('step2.regenerateAgent') }}</button>
      </div>
    </div>
    
    <div v-else class="modal-body modal-view">
      <p><strong>Bio:</strong> {{ selectedAgent?.bio }}</p>
      <p><strong>Persona:</strong> {{ selectedAgent?.persona }}</p>
      <div class="modal-actions">
        <button class="btn-secondary" @click="agentModalMode = 'regen'">{{ $t('step2.regenerateAgent') }}</button>
        <button class="btn-danger" @click="confirmDeleteAgent(selectedAgent); closeAgentModal()">{{ $t('step2.deleteAgent') }}</button>
        <button class="btn-primary" @click="agentModalMode = 'edit'">{{ $t('step2.editAgent') }}</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Afegir indicador `manually_edited` a les cards d'agent**

Localitza el template de cada card d'agent i afegeix:

```vue
<span v-if="agent.manually_edited" class="manually-edited-badge">{{ $t('step2.manuallyEditedBadge') }}</span>
```

I afegeix un botó d'acció a cada card:

```vue
<button class="agent-action-btn" @click="openAgentModal(agent)">···</button>
```

- [ ] **Step 7: Afegir CSS nou**

```css
.phase-a-footer {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0;
  border-top: 1px solid #EAEAEA;
  margin-top: 16px;
}

.continue-btn {
  padding: 10px 24px;
  background: #000;
  color: #FFF;
  border: none;
  border-radius: 6px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
}

.continue-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.agent-modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}

.agent-modal {
  background: #FFF; border-radius: 12px; padding: 24px;
  width: 560px; max-height: 80vh; overflow-y: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
}

.modal-header {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 16px;
}

.modal-title { font-weight: 700; font-size: 18px; flex: 1; }

.edited-badge, .manually-edited-badge {
  background: #FFF3CD; color: #856404;
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;
}

.modal-close { background: none; border: none; cursor: pointer; font-size: 18px; }

.modal-body .field-group { margin-bottom: 12px; }
.modal-body label { display: block; font-size: 12px; font-weight: 600; color: #666; margin-bottom: 4px; text-transform: uppercase; }
.modal-body input, .modal-body textarea {
  width: 100%; padding: 8px 12px; border: 1px solid #E0E0E0;
  border-radius: 6px; font-size: 14px; resize: vertical;
}

.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
.btn-primary { padding: 8px 16px; background: #000; color: #FFF; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
.btn-secondary { padding: 8px 16px; background: #F5F5F5; color: #333; border: 1px solid #DDD; border-radius: 6px; cursor: pointer; font-weight: 600; }
.btn-danger { padding: 8px 16px; background: #FFF; color: #D32F2F; border: 1px solid #FFCDD2; border-radius: 6px; cursor: pointer; font-weight: 600; }
.btn-primary:disabled, .btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }

.agent-action-btn { background: none; border: none; cursor: pointer; padding: 4px 8px; font-size: 18px; color: #666; }
.agent-action-btn:hover { color: #000; }
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Step2EnvSetup.vue
git commit -m "feat(step2): add Fase A agent edit/delete/regen modal and continue button"
```

---

## Task 15: Frontend — Fase B: formulari de paràmetres i `enable_graph_memory_update` checkbox

**Files:**
- Modify: `frontend/src/components/Step2EnvSetup.vue`
- Modify: `frontend/src/components/Step3Simulation.vue`

- [ ] **Step 1: Afegir refs de Fase B**

```javascript
import { patchSimulationConfig, getSimulationConfig } from '../api/simulation'

const phaseBConfig = ref(null)  // loaded from GET /config after phase_b transition
const phaseBLoading = ref(false)
const phaseBSaving = ref(false)
const configForm = ref({})      // global params form
```

- [ ] **Step 2: Carregar la config quan es transiciona a `phase_b`**

Modifica `continueToPhaseB` per carregar la config un cop el task és complet:

```javascript
const continueToPhaseB = async () => {
  generateConfigLoading.value = true
  try {
    const res = await generateConfig(simulationId.value)
    if (res.data.success) {
      await pollTaskUntilDone(res.data.data.task_id, async () => {
        // Load config for Fase B display
        const configRes = await getSimulationConfig(simulationId.value)
        if (configRes.data.success) {
          phaseBConfig.value = configRes.data.data
          const tc = phaseBConfig.value?.time_config || {}
          configForm.value = {
            total_simulation_hours: tc.total_simulation_hours ?? 24,
            minutes_per_round: tc.minutes_per_round ?? 60,
            following_probability: phaseBConfig.value?.following_probability ?? 0.05,
            recsys_type: phaseBConfig.value?.recsys_type ?? 'random',
          }
        }
        currentPhase.value = 'phase_b'
      })
    }
  } finally {
    generateConfigLoading.value = false
  }
}
```

- [ ] **Step 3: Afegir `saveGlobalConfig` i `launchSimulation`**

```javascript
const saveGlobalConfig = async () => {
  phaseBSaving.value = true
  try {
    await patchSimulationConfig(simulationId.value, configForm.value)
  } finally {
    phaseBSaving.value = false
  }
}

const launchSimulation = async () => {
  // Save config before launching
  await saveGlobalConfig()
  // Navigate to Step 3 (same as existing flow)
  emit('go-step3', simulationId.value)
}
```

- [ ] **Step 4: Afegir la secció de Fase B al template**

Just sota la secció de Fase A (o condicionalment quan `currentPhase === 'phase_b'`):

```vue
<!-- Fase B: Global parameters form -->
<div v-if="currentPhase === 'phase_b'" class="phase-b-section">
  <h3>{{ $t('step2.phaseBTitle') }}</h3>
  <p class="section-subtitle">{{ $t('step2.phaseBSubtitle') }}</p>
  
  <div class="config-form">
    <div class="config-field">
      <label>{{ $t('step2.totalHours') }}</label>
      <input type="number" v-model.number="configForm.total_simulation_hours" min="1" max="720" />
    </div>
    <div class="config-field">
      <label>{{ $t('step2.minutesPerRound') }}</label>
      <input type="number" v-model.number="configForm.minutes_per_round" min="1" max="1440" />
    </div>
    <div class="config-field">
      <label>{{ $t('step2.followingProbability') }}</label>
      <input type="number" v-model.number="configForm.following_probability" min="0" max="1" step="0.01" />
    </div>
    <div class="config-field">
      <label>{{ $t('step2.recsysType') }}</label>
      <select v-model="configForm.recsys_type">
        <option value="random">Random</option>
        <option value="interest">Interest-based</option>
        <option value="twhin">TWHIN</option>
      </select>
    </div>
  </div>

  <div class="phase-b-footer">
    <button class="btn-secondary" @click="currentPhase = 'phase_a'">← Back</button>
    <button class="continue-btn" :disabled="phaseBSaving" @click="launchSimulation">
      {{ $t('step2.launchSimulation') }}
    </button>
  </div>
</div>
```

- [ ] **Step 5: Convertir `enable_graph_memory_update` a checkbox a `Step3Simulation.vue`**

Localitza la línia `enable_graph_memory_update: true` (hardcoded) a `Step3Simulation.vue:402` i substitueix per un ref reactiu:

```javascript
const enableGraphMemoryUpdate = ref(true)  // afegir als refs existents
```

Localitza la crida a `startSimulation` i canvia el paràmetre:

```javascript
enable_graph_memory_update: enableGraphMemoryUpdate.value  // era: true
```

Afegeix el checkbox al template, a la secció de configuració del Step 3:

```vue
<div class="option-row">
  <label class="toggle-label">
    <input type="checkbox" v-model="enableGraphMemoryUpdate" />
    <span>Graph Memory Update</span>
    <span class="hint">Update agent conversations to graph in real time (needed for report analysis)</span>
  </label>
</div>
```

- [ ] **Step 6: Afegir CSS per Fase B**

```css
.phase-b-section { padding: 16px 0; }
.config-form { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0; }
.config-field label { display: block; font-size: 12px; font-weight: 600; color: #666; margin-bottom: 4px; text-transform: uppercase; }
.config-field input, .config-field select { width: 100%; padding: 8px 12px; border: 1px solid #E0E0E0; border-radius: 6px; font-size: 14px; }
.phase-b-footer { display: flex; justify-content: space-between; padding-top: 16px; border-top: 1px solid #EAEAEA; }

.option-row { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
.toggle-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; }
.toggle-label .hint { color: #999; font-size: 12px; }
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Step2EnvSetup.vue frontend/src/components/Step3Simulation.vue
git commit -m "feat(step2): add Fase B config form and launch button; Step3 enable_graph_memory_update checkbox"
```

---

## Verificació end-to-end

Seguir els tests manuals de la spec:

- [ ] **Test 1 (flux complet)**: Generar agents → editar bio → "Continuar →" → verificar config → editar `total_simulation_hours` → llançar
- [ ] **Test 2 (protecció de sobreescriptura)**: Editar agent durant generació → verificar que no es sobreescriu
- [ ] **Test 3 (regeneració individual)**: `profiles_ready` → regenerar amb instrucció → spinner → perfil canviat
- [ ] **Test 4 (crear i eliminar)**: Afegir agent nou → verificar a cards → eliminar → verificar que desapareix
- [ ] **Test 5 (selector N)**: 50 entitats → reduir a 30 → verificar 30 agents generats
- [ ] **Test 6 (clonació)**: Completar sim1 → clonar al mateix projecte → editar un agent → llançar sim2 → sim1 intacta
- [ ] **Test 7 (aïllament grafs)**: Sim1 + sim2 amb `enable_graph_memory_update=true` → reports aïllats; esborrar sim2 → `graph_id_simulation` esborrat de Neo4j

---

## Notes d'implementació

1. **Ordre de tasques**: Les Tasks 1-9 (backend) i 12-13 (API/i18n) es poden fer en un bloc; les Tasks 14-15 (frontend Vue) en un segon bloc.

2. **`prepare_simulation` i `profiles_ready`**: El canvi més crític és que `SimulationManager.prepare_simulation()` ara ha d'aturar-se a `profiles_ready` en lloc de continuar amb `generate_simulation_config`. La config es generarà a `generate-config` quan l'usuari premi "Continuar →". Si `max_agents` no es toca, el comportament és idèntic a l'actual (totes les entitats, generació completa automàtica).

3. **Compatibilitat enrere**: Les simulacions existents amb `status: ready` funcionen exactament igual: l'endpoint `POST /start` les accepta sense canvis.

4. **Subsistema 5 (clone_graph)**: Requereix Graphiti/Neo4j actiu. Si el backend és Zep, la crida a `clone_graph` no existirà al backend i la simulació usarà el `graph_id` compartit (comportament actual). El `hasattr(graph_backend, 'clone_graph')` al Task 11 n'és el guard.
