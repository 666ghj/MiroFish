# F1-1: Correcció graph.py + Projectes llistables i Recovery UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir el `graph.py` trencat (usa accés a objecte però ProjectManager retorna dicts), afegir persistència d'ontologia/graph a BD, i exposar una Recovery UI mínima a la pàgina Home.

**Architecture:** Totes les crides a `project.attribute` es substitueixen per `project["attribute"]`. Les operacions de mutació (`project.status = ...`) es fan acumulant un dict parcial i cridant `ProjectManager.save_project()`. L'ontologia es desa a `OntologyModel` i el graph_id a `GraphModel`. La Recovery UI és el component `HistoryDatabase.vue` existent adaptat per usar `GET /api/graph/project/list` en comptes de `getSimulationHistory`.

**Tech Stack:** Flask/SQLAlchemy (backend), Vue 3 + Axios (frontend), pytest (tests)

---

## Mapa de fitxers

| Fitxer | Acció | Responsabilitat |
|--------|-------|----------------|
| `backend/app/api/graph.py` | Modificar | Fix accés dict; injectar storage; persistir ontologia/graph |
| `backend/app/models/project.py` | Modificar | Afegir `save_ontology()` i `get_ontology()` i `save_graph_record()` i `get_latest_graph_id()` |
| `backend/tests/test_graph_api.py` | Crear | Tests per als endpoints corregits |
| `frontend/src/api/graph.js` | Modificar | Afegir `listProjects()` |
| `frontend/src/components/HistoryDatabase.vue` | Modificar | Usar `listProjects()` en comptes de `getSimulationHistory`; navegar a `/process/:projectId` |

---

## Task 0: Afegir helpers de persistència a ProjectManager

**Files:**
- Modify: `backend/app/models/project.py`

- [ ] **Step 1: Llegir el fitxer actual per orientar-se**

```bash
cat -n backend/app/models/project.py
```

- [ ] **Step 2: Afegir quatre mètodes al `ProjectManager`**

Afegir just abans del mètode `_to_dict` a `backend/app/models/project.py`:

```python
    @classmethod
    def save_ontology(cls, project_id: str, entity_types: list, edge_types: list) -> str:
        """Crea o actualitza el registre d'ontologia. Retorna l'id de l'OntologyModel."""
        from .db_models import OntologyModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(OntologyModel).where(OntologyModel.project_id == project_id).order_by(OntologyModel.version.desc())
            existing = db.execute(stmt).scalars().first()
            if existing:
                existing.entity_types = entity_types
                existing.edge_types = edge_types
                db.commit()
                return existing.id
            else:
                rec = OntologyModel(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    version=1,
                    entity_types=entity_types,
                    edge_types=edge_types,
                )
                db.add(rec)
                db.commit()
                return rec.id

    @classmethod
    def get_ontology(cls, project_id: str) -> Optional[Dict[str, Any]]:
        """Retorna l'ontologia del projecte o None si no existeix."""
        from .db_models import OntologyModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(OntologyModel).where(OntologyModel.project_id == project_id).order_by(OntologyModel.version.desc())
            rec = db.execute(stmt).scalars().first()
            if rec is None:
                return None
            return {"entity_types": rec.entity_types or [], "edge_types": rec.edge_types or []}

    @classmethod
    def save_graph_record(cls, project_id: str, external_id: str, ontology_id: Optional[str] = None) -> str:
        """Crea o actualitza el GraphModel. Retorna l'id del GraphModel."""
        from .db_models import GraphModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(GraphModel).where(GraphModel.project_id == project_id).order_by(GraphModel.created_at.desc())
            existing = db.execute(stmt).scalars().first()
            if existing:
                existing.external_id = external_id
                existing.status = "building"
                if ontology_id:
                    existing.ontology_id = ontology_id
                db.commit()
                return existing.id
            else:
                rec = GraphModel(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    external_id=external_id,
                    ontology_id=ontology_id,
                    status="building",
                    backend=Config.GRAPH_BACKEND,
                )
                db.add(rec)
                db.commit()
                return rec.id

    @classmethod
    def get_latest_graph_external_id(cls, project_id: str) -> Optional[str]:
        """Retorna l'external_id del GraphModel més recent del projecte."""
        from .db_models import GraphModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(GraphModel).where(GraphModel.project_id == project_id).order_by(GraphModel.created_at.desc())
            rec = db.execute(stmt).scalars().first()
            return rec.external_id if rec else None

    @classmethod
    def complete_graph_record(cls, project_id: str, node_count: int, edge_count: int) -> None:
        """Marca el GraphModel com a ready i actualitza comptadors."""
        from .db_models import GraphModel
        from sqlalchemy import select
        with get_session() as db:
            stmt = select(GraphModel).where(GraphModel.project_id == project_id).order_by(GraphModel.created_at.desc())
            rec = db.execute(stmt).scalars().first()
            if rec:
                rec.status = "ready"
                rec.node_count = node_count
                rec.edge_count = edge_count
                db.commit()
```

**Nota**: Cal afegir `from ..config import Config` als imports de `project.py` per a `save_graph_record`.

- [ ] **Step 3: Afegir `graph_id` als camps del `_to_dict`**

A `_to_dict`, substituir la línia:
```python
            "graph_id": None,
```
per:
```python
            "graph_id": cls.get_latest_graph_external_id(proj.id),
```

Però com que `_to_dict` és `@staticmethod`, s'ha de convertir a `@classmethod` o usar una crida directa. La manera més simple és canviar el `_to_dict` a `@classmethod` i passar `cls`:

```python
    @classmethod
    def _to_dict(cls, proj: "ProjectModel") -> Dict[str, Any]:
        from .db_models import GraphModel, OntologyModel
        from sqlalchemy import select
        with get_session() as db:
            graph_stmt = select(GraphModel).where(GraphModel.project_id == proj.id).order_by(GraphModel.created_at.desc())
            graph_rec = db.execute(graph_stmt).scalars().first()
            ont_stmt = select(OntologyModel).where(OntologyModel.project_id == proj.id).order_by(OntologyModel.version.desc())
            ont_rec = db.execute(ont_stmt).scalars().first()
        
        ontology = {"entity_types": ont_rec.entity_types or [], "edge_types": ont_rec.edge_types or []} if ont_rec else None
        graph_external_id = graph_rec.external_id if graph_rec else None
        
        return {
            "id": proj.id,
            "project_id": proj.id,
            "name": proj.name,
            "status": proj.status,
            "analysis_summary": proj.analysis_summary,
            "simulation_requirement": proj.simulation_requirement,
            "chunk_size": proj.chunk_size,
            "chunk_overlap": proj.chunk_overlap,
            "active_task_id": proj.active_task_id,
            "created_at": proj.created_at.isoformat(),
            "updated_at": proj.updated_at.isoformat(),
            "files": [],
            "total_text_length": 0,
            "ontology": ontology,
            "graph_id": graph_external_id,
            "graph_build_task_id": None,
            "error": None,
        }
```

**IMPORTANT**: `_to_dict` és cridat des de dins d'un bloc `with get_session()`. Obrir una nova sessió aniuada falla amb SQLite. Solució: moure la consulta fora, o passar els registres com a paràmetre opcional. La manera correcta és fer una funció `_to_dict_with_related` que pren els registres ja carregats:

```python
    @classmethod
    def _to_dict(cls, proj: "ProjectModel") -> Dict[str, Any]:
        from .db_models import GraphModel, OntologyModel
        from sqlalchemy import select
        graph_external_id = None
        ontology = None
        # Sessions aniuades no funcionen; usem una sessió nova independent
        with get_session() as db2:
            graph_rec = db2.execute(
                select(GraphModel).where(GraphModel.project_id == proj.id).order_by(GraphModel.created_at.desc())
            ).scalars().first()
            ont_rec = db2.execute(
                select(OntologyModel).where(OntologyModel.project_id == proj.id).order_by(OntologyModel.version.desc())
            ).scalars().first()
            if graph_rec:
                graph_external_id = graph_rec.external_id
            if ont_rec:
                ontology = {"entity_types": ont_rec.entity_types or [], "edge_types": ont_rec.edge_types or []}
        return {
            "id": proj.id,
            "project_id": proj.id,
            "name": proj.name,
            "status": proj.status,
            "analysis_summary": proj.analysis_summary,
            "simulation_requirement": proj.simulation_requirement,
            "chunk_size": proj.chunk_size,
            "chunk_overlap": proj.chunk_overlap,
            "active_task_id": proj.active_task_id,
            "created_at": proj.created_at.isoformat(),
            "updated_at": proj.updated_at.isoformat(),
            "files": [],
            "total_text_length": 0,
            "ontology": ontology,
            "graph_id": graph_external_id,
            "graph_build_task_id": None,
            "error": None,
        }
```

**Nota sobre sessions aniuades a SQLite**: SQLAlchemy amb `StaticPool` (test) permet múltiples connexions al mateix fil. En producció (SQLite amb `check_same_thread=False`) una sessió aniuada nova és correcta. Verifiquem que `get_session()` no usa la mateixa connexió però sí el mateix pool.

- [ ] **Step 4: Afegir `Config` als imports de `project.py`**

A la secció d'imports, afegir:
```python
from ..config import Config
```

- [ ] **Step 5: Executar tests existents per verificar no-regression**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/test_project_manager_db.py -v
```

Expected: tots els tests passen.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/project.py
git commit -m "feat(project): add ontology/graph persistence helpers to ProjectManager"
```

---

## Task 1: Corregir `graph.py` — Fase A: Endpoints de projecte i tasca

**Files:**
- Modify: `backend/app/api/graph.py`

Els bugs a corregir en aquesta fase:
- `get_project`: `project.to_dict()` → `project` ja és dict, retornar directament
- `list_projects`: `[p.to_dict() for p in projects]` → `projects` ja és list of dicts
- `reset_project`: accés a `project.ontology`, `project.status = ...`, `project.to_dict()`
- `get_task`/`list_tasks`: `task.to_dict()`, `[t.to_dict() for t in tasks]`
- `delete_project`: cal passar `storage` a `ProjectManager.delete_project`

- [ ] **Step 1: Corregir `get_project` (línia 52)**

Substituir:
```python
    return jsonify({
        "success": True,
        "data": project.to_dict()
    })
```
per:
```python
    return jsonify({
        "success": True,
        "data": project
    })
```

- [ ] **Step 2: Corregir `list_projects` (línia 66)**

Substituir:
```python
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })
```
per:
```python
    return jsonify({
        "success": True,
        "data": projects,
        "count": len(projects)
    })
```

- [ ] **Step 3: Corregir `delete_project` — injectar storage**

La signatura actual és `ProjectManager.delete_project(project_id)`. Cal passar `storage`.

Afegir l'import al top del fitxer:
```python
from ..__init__ import get_storage
```

Substituir:
```python
    success = ProjectManager.delete_project(project_id)
```
per:
```python
    storage = get_storage()
    success = ProjectManager.delete_project(project_id, storage=storage)
```

- [ ] **Step 4: Corregir `reset_project`**

Substituir tot el bloc de l'endpoint `reset_project` (línies 90–118) per:

```python
@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    new_status = ProjectStatus.ONTOLOGY_GENERATED if project.get("ontology") else ProjectStatus.CREATED
    ProjectManager.save_project({
        "id": project_id,
        "status": new_status,
        "active_task_id": None,
    })
    updated = ProjectManager.get_project(project_id)
    
    return jsonify({
        "success": True,
        "message": t('api.projectReset', id=project_id),
        "data": updated
    })
```

- [ ] **Step 5: Corregir `get_task` i `list_tasks`**

Substituir (línies 672–673):
```python
    return jsonify({
        "success": True,
        "data": task.to_dict()
    })
```
per:
```python
    return jsonify({
        "success": True,
        "data": task
    })
```

Substituir (línies 684–686):
```python
    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })
```
per (nota: `t` és la variable de traducció, no shadows):
```python
    return jsonify({
        "success": True,
        "data": tasks,
        "count": len(tasks)
    })
```

- [ ] **Step 6: Executar tests**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/ -v -k "not test_config_graph_backend_default" 2>&1 | tail -20
```

Expected: tots passen excepte el test pre-existent `test_config_graph_backend_default`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/graph.py
git commit -m "fix(graph-api): fix project/task dict access after ProjectManager refactor"
```

---

## Task 2: Corregir `graph.py` — Fase B: Endpoints `generate_ontology` i `import_ontology`

**Files:**
- Modify: `backend/app/api/graph.py`

Bugs a corregir:
- `project.simulation_requirement = ...` → acumular al dict i cridar `save_project`
- `ProjectManager.save_file_to_project(project.project_id, file, file.filename)` → manquen `storage` i crides correctes
- `FileParser.extract_text(file_info["path"])` → el nou `save_file_to_project` no retorna "path", retorna "storage_path". Cal baixar des de StorageService.
- `project.files.append(...)` → no persisteix res; la UI no necessita la llista de fitxers en la resposta immediata
- `ProjectManager.save_extracted_text(project_id, all_text)` → manquen `storage`
- `project.ontology = ...`, `project.analysis_summary = ...`, `project.status = ...` → acumular i cridar `save_project` + `save_ontology`
- `project.total_text_length = ...` → no és un camp del model, és calculat

### Estratègia de refactorització

En lloc d'intentar mutar el dict `project` (que no persisteix), acumulem tots els canvis en variables locals i cridem `save_project()` una sola vegada al final. L'extracció de text usarà `storage.download(storage_path)` per llegir el fitxer pujat.

- [ ] **Step 1: Afegir imports necessaris a `graph.py`**

A la secció d'imports, afegir:
```python
from ..__init__ import get_storage
```

(Si ja s'ha afegit al Task 1, no duplicar.)

- [ ] **Step 2: Reescriure el cos de `generate_ontology`**

Substituir el cos complet de la funció (línies 151–256) per:

```python
@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    try:
        logger.info("=== Starting ontology generation ===")
        storage = get_storage()

        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        
        if not simulation_requirement:
            return jsonify({"success": False, "error": t('api.requireSimulationRequirement')}), 400
        
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({"success": False, "error": t('api.requireFileUpload')}), 400

        project = ProjectManager.create_project(name=project_name, storage=storage)
        project_id = project["project_id"]
        logger.info(f"Project created: {project_id}")

        document_texts = []
        all_text = ""

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                file_info = ProjectManager.save_file_to_project(
                    project_id, file, file.filename, storage
                )
                raw = storage.download(file_info["storage_path"])
                import tempfile, os
                ext = os.path.splitext(file.filename)[1].lower()
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(raw)
                    tmp_path = tmp.name
                try:
                    text = FileParser.extract_text(tmp_path)
                finally:
                    os.unlink(tmp_path)
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file.filename} ===\n{text}"

        if not document_texts:
            ProjectManager.delete_project(project_id, storage=storage)
            return jsonify({"success": False, "error": t('api.noDocProcessed')}), 400

        ProjectManager.save_extracted_text(project_id, all_text, storage)
        logger.info(f"Text extraction complete, total {len(all_text)} characters")

        logger.info("Calling LLM to generate ontology definition...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )

        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])
        analysis_summary = ontology.get("analysis_summary", "")
        logger.info(f"Ontology generation complete: {len(entity_types)} entity types, {len(edge_types)} relationship types")

        ProjectManager.save_ontology(project_id, entity_types, edge_types)
        ProjectManager.save_project({
            "id": project_id,
            "simulation_requirement": simulation_requirement,
            "analysis_summary": analysis_summary,
            "status": ProjectStatus.ONTOLOGY_GENERATED,
        })
        logger.info(f"=== Ontology generation complete === Project ID: {project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "project_name": project_name,
                "ontology": {"entity_types": entity_types, "edge_types": edge_types},
                "analysis_summary": analysis_summary,
                "files": [],
                "total_text_length": len(all_text)
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 3: Reescriure el cos de `import_ontology`**

Substituir el cos complet de la funció `import_ontology` (línies 261–376) per:

```python
@graph_bp.route('/ontology/import', methods=['POST'])
def import_ontology():
    try:
        logger.info("=== Starting ontology import ===")
        storage = get_storage()

        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        ontology_json = request.form.get('ontology', '')

        if not simulation_requirement:
            return jsonify({"success": False, "error": t('api.requireSimulationRequirement')}), 400
        if not ontology_json:
            return jsonify({"success": False, "error": t('api.requireOntologyJson')}), 400
        try:
            ontology = json.loads(ontology_json)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": t('api.invalidOntologyJson')}), 400
        if not isinstance(ontology.get('entity_types'), list) or not isinstance(ontology.get('edge_types'), list):
            return jsonify({"success": False, "error": t('api.invalidOntologyStructure')}), 400

        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({"success": False, "error": t('api.requireFileUpload')}), 400

        project = ProjectManager.create_project(name=project_name, storage=storage)
        project_id = project["project_id"]
        logger.info(f"Project created for import: {project_id}")

        document_texts = []
        all_text = ""

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                file_info = ProjectManager.save_file_to_project(
                    project_id, file, file.filename, storage
                )
                raw = storage.download(file_info["storage_path"])
                import tempfile, os
                ext = os.path.splitext(file.filename)[1].lower()
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(raw)
                    tmp_path = tmp.name
                try:
                    text = FileParser.extract_text(tmp_path)
                finally:
                    os.unlink(tmp_path)
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file.filename} ===\n{text}"

        if not document_texts:
            ProjectManager.delete_project(project_id, storage=storage)
            return jsonify({"success": False, "error": t('api.noDocProcessed')}), 400

        ProjectManager.save_extracted_text(project_id, all_text, storage)

        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])
        analysis_summary = ontology.get("analysis_summary", "")

        ProjectManager.save_ontology(project_id, entity_types, edge_types)
        ProjectManager.save_project({
            "id": project_id,
            "simulation_requirement": simulation_requirement,
            "analysis_summary": analysis_summary,
            "status": ProjectStatus.ONTOLOGY_GENERATED,
        })
        logger.info(f"=== Ontology import complete === Project ID: {project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "project_name": project_name,
                "ontology": {"entity_types": entity_types, "edge_types": edge_types},
                "analysis_summary": analysis_summary,
                "files": [],
                "total_text_length": len(all_text)
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500
```

- [ ] **Step 4: Executar tests**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/ -v -k "not test_config_graph_backend_default" 2>&1 | tail -20
```

Expected: tots passen.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/graph.py
git commit -m "fix(graph-api): rewrite generate_ontology/import_ontology to use dict ProjectManager"
```

---

## Task 3: Corregir `graph.py` — Fase C: Endpoint `build_graph`

**Files:**
- Modify: `backend/app/api/graph.py`

Bugs a corregir:
- `project.status == ProjectStatus.CREATED` → `project["status"] == ProjectStatus.CREATED`
- `project.status == ProjectStatus.GRAPH_BUILDING` → `project["status"] == ...`
- `project.graph_build_task_id` → `project.get("graph_build_task_id")`
- `project.status = ...`, `project.graph_id = None`, etc. → acumular i cridar `save_project`
- `project.name` → `project["name"]`
- `project.chunk_size`, `project.chunk_overlap` → `project.get("chunk_size")`, `project.get("chunk_overlap")`
- `ProjectManager.get_extracted_text(project_id)` → `ProjectManager.get_extracted_text(project_id, storage)`
- `project.ontology` → `project.get("ontology")`
- A la tasca de fons (`build_task`): `project.graph_id = graph_id` → cridar `save_graph_record` + `save_project`
- Al final: `project.status = ProjectStatus.GRAPH_COMPLETED; project.active_task_id = None` → `save_project`
- A l'error: `project.status = ProjectStatus.FAILED; project.error = str(e)` → `save_project`

- [ ] **Step 1: Reescriure el bloc de validació (línies 418–493) dins de `build_graph`**

Substituir des de `# Get project` fins a `# Get configuration` per:

```python
        # Get project
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({"success": False, "error": t('api.projectNotFound', id=project_id)}), 404
        storage = get_storage()

        # Check project status
        force = data.get('force', False)

        if project["status"] == ProjectStatus.CREATED:
            return jsonify({"success": False, "error": t('api.ontologyNotGenerated')}), 400

        if project["status"] == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": t('api.graphBuilding'),
                "task_id": project.get("active_task_id")
            }), 400

        # If force rebuild, reset status
        if force and project["status"] in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            ProjectManager.save_project({"id": project_id, "status": ProjectStatus.ONTOLOGY_GENERATED, "active_task_id": None})
            project = ProjectManager.get_project(project_id)

        # Get configuration
        graph_name = data.get('graph_name', project["name"] or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.get("chunk_size") or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.get("chunk_overlap") or Config.DEFAULT_CHUNK_OVERLAP)
        ProjectManager.save_project({"id": project_id, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap})

        # Get extracted text
        text = ProjectManager.get_extracted_text(project_id, storage)
        if not text:
            return jsonify({"success": False, "error": t('api.textNotFound')}), 400

        # Get ontology
        ontology = project.get("ontology") or ProjectManager.get_ontology(project_id)
        if not ontology:
            return jsonify({"success": False, "error": t('api.ontologyNotFound')}), 400
```

- [ ] **Step 2: Corregir la creació de tasca i l'update de projecte (línies ~485–493)**

Substituir:
```python
        # Update project status
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        project.active_task_id = task_id
        ProjectManager.save_project(project)
```
per:
```python
        # Update project status
        ProjectManager.save_project({
            "id": project_id,
            "status": ProjectStatus.GRAPH_BUILDING,
            "active_task_id": task_id,
        })
```

- [ ] **Step 3: Corregir el cos de `build_task` — update graph_id**

Substituir:
```python
                # Update project graph_id
                project.graph_id = graph_id
                ProjectManager.save_project(project)
```
per:
```python
                # Persist graph record
                ont = ProjectManager.get_ontology(project_id)
                ontology_db_id = None
                if ont:
                    from ..models.db_models import OntologyModel
                    from sqlalchemy import select
                    from ..db import get_session
                    with get_session() as db:
                        rec = db.execute(select(OntologyModel).where(OntologyModel.project_id == project_id).order_by(OntologyModel.version.desc())).scalars().first()
                        ontology_db_id = rec.id if rec else None
                ProjectManager.save_graph_record(project_id, graph_id, ontology_id=ontology_db_id)
```

- [ ] **Step 4: Corregir els `save_project` de la tasca de fons**

Substituir (al bloc de success de build_task):
```python
                # Update project status
                project.status = ProjectStatus.GRAPH_COMPLETED
                project.active_task_id = None
                ProjectManager.save_project(project)
```
per:
```python
                # Update project status
                ProjectManager.complete_graph_record(project_id, node_count, edge_count)
                ProjectManager.save_project({
                    "id": project_id,
                    "status": ProjectStatus.GRAPH_COMPLETED,
                    "active_task_id": None,
                })
```

Substituir (al bloc d'error de build_task):
```python
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                project.active_task_id = None
                ProjectManager.save_project(project)
```
per:
```python
                ProjectManager.save_project({
                    "id": project_id,
                    "status": ProjectStatus.FAILED,
                    "active_task_id": None,
                })
```

- [ ] **Step 5: Corregir el `result` final de la tasca per usar `project_id`**

La variable `project_id` és accessible per closura dins de `build_task`. El `task_manager.update_task(..., result={...})` ja usa `project_id` directament — no cal canvi si l'hem deixat com a variable local.

- [ ] **Step 6: Executar tests**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/ -v -k "not test_config_graph_backend_default" 2>&1 | tail -30
```

Expected: tots passen.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/graph.py backend/app/models/project.py
git commit -m "fix(graph-api): fix build_graph endpoint for dict-based ProjectManager"
```

---

## Task 4: Tests de l'API d'endpoints de projecte

**Files:**
- Create: `backend/tests/test_graph_api_project.py`

Estos tests usen un client Flask de test (`app.test_client()`) per verificar que els endpoints retornen les estructures esperades sense cridar serveis externs.

- [ ] **Step 1: Escriure els tests**

Crear `backend/tests/test_graph_api_project.py`:

```python
"""Tests d'integració per als endpoints de projecte de graph.py."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(in_memory_db):
    """Flask test client amb BD en memòria."""
    from backend.app import create_app
    app = create_app()
    app.config['TESTING'] = True
    # Sobreescriure storage per a tests
    mock_storage = MagicMock()
    mock_storage.exists.return_value = False
    app.extensions['storage'] = mock_storage
    with app.test_client() as c:
        yield c


def test_list_projects_empty(client):
    res = client.get('/api/graph/project/list')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data'] == []
    assert data['count'] == 0


def test_get_project_not_found(client):
    res = client.get('/api/graph/project/nonexistent-id')
    assert res.status_code == 404
    data = res.get_json()
    assert data['success'] is False


def test_create_and_get_project(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="Test Project")
    project_id = proj['project_id']

    res = client.get(f'/api/graph/project/{project_id}')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['name'] == 'Test Project'
    assert data['data']['graph_id'] is None
    assert data['data']['ontology'] is None


def test_list_projects_returns_created(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    ProjectManager.create_project(name="Alpha")
    ProjectManager.create_project(name="Beta")

    res = client.get('/api/graph/project/list')
    assert res.status_code == 200
    data = res.get_json()
    assert data['count'] == 2
    names = [p['name'] for p in data['data']]
    assert 'Alpha' in names
    assert 'Beta' in names


def test_delete_project(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="ToDelete")
    project_id = proj['project_id']

    res = client.delete(f'/api/graph/project/{project_id}')
    assert res.status_code == 200
    assert res.get_json()['success'] is True

    # Verificar que ja no existeix
    res2 = client.get(f'/api/graph/project/{project_id}')
    assert res2.status_code == 404


def test_reset_project(client, in_memory_db):
    from backend.app.models.project import ProjectManager
    proj = ProjectManager.create_project(name="ToReset")
    project_id = proj['project_id']
    ProjectManager.save_project({"id": project_id, "status": "graph_completed"})

    res = client.post(f'/api/graph/project/{project_id}/reset')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    # Sense ontologia, ha de tornar a 'created'
    assert data['data']['status'] == 'created'
```

- [ ] **Step 2: Executar els tests nous**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/test_graph_api_project.py -v 2>&1
```

Expected: tots passen. Si algun falla per la configuració del `create_app` (AUTH_SECRET, etc.), afegir variables d'entorn mínimes al fixture:

```python
import os
os.environ.setdefault('SECRET_KEY', 'test')
os.environ.setdefault('JWT_SECRET_KEY', 'test')
```

- [ ] **Step 3: Executar tots els tests**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/ -v -k "not test_config_graph_backend_default" 2>&1 | tail -30
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_graph_api_project.py
git commit -m "test(graph-api): add integration tests for project CRUD endpoints"
```

---

## Task 5: Frontend — `listProjects()` a `api/graph.js`

**Files:**
- Modify: `frontend/src/api/graph.js`

- [ ] **Step 1: Afegir la funció `listProjects`**

Afegir al final de `frontend/src/api/graph.js`:

```javascript
/**
 * Llista tots els projectes (per a la Recovery UI)
 * @param {Number} limit - Màxim de projectes a retornar (default 50)
 * @returns {Promise}
 */
export function listProjects(limit = 50) {
  return service({
    url: `/api/graph/project/list?limit=${limit}`,
    method: 'get'
  })
}
```

- [ ] **Step 2: Verificar que la funció és importable**

```bash
grep -n "listProjects" /home/ubuntu/dev/MiroFish/frontend/src/api/graph.js
```

Expected: la funció apareix.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/graph.js
git commit -m "feat(frontend-api): add listProjects() to graph API client"
```

---

## Task 6: Frontend — Adaptar `HistoryDatabase.vue` per a Recovery UI

**Files:**
- Modify: `frontend/src/components/HistoryDatabase.vue`

`HistoryDatabase.vue` existeix i mostra projectes des de `getSimulationHistory`. Cal canviar-la per usar `listProjects()` i navegar correctament a `/process/:projectId`.

L'estructura actual del component usa camps de simulació (`simulation_id`, `report_id`, etc.). Ara hem d'adaptar-la per mostrar projectes de MiroFish amb els camps disponibles:
- `project_id` — per navegar a `/process/:projectId`
- `name` — nom del projecte
- `status` — estat (`created`, `ontology_generated`, `graph_building`, `graph_completed`, `failed`)
- `simulation_requirement` — com a descripció
- `created_at` — data de creació
- `ontology` — si `!= null`, hi ha ontologia
- `graph_id` — si `!= null`, hi ha graph

- [ ] **Step 1: Llegir el component actual (primera vegada en la sessió)**

```bash
wc -l /home/ubuntu/dev/MiroFish/frontend/src/components/HistoryDatabase.vue
```

- [ ] **Step 2: Localitzar les crides a `getSimulationHistory`**

```bash
grep -n "getSimulationHistory\|simulation_id\|report_id" /home/ubuntu/dev/MiroFish/frontend/src/components/HistoryDatabase.vue | head -30
```

- [ ] **Step 3: Modificar la importació i la crida de dades**

A la secció `<script setup>`, canviar la importació:

Substituir:
```javascript
import { getSimulationHistory } from '../api/simulation'
```
per:
```javascript
import { listProjects } from '../api/graph'
```

Localitzar la crida `getSimulationHistory(...)` i substituir pel nou patró. Per exemple, si el codi és:
```javascript
const loadHistory = async () => {
  loading.value = true
  try {
    const res = await getSimulationHistory(20)
    if (res.success) {
      projects.value = res.data
    }
  } finally {
    loading.value = false
  }
}
```
Substituir per:
```javascript
const loadHistory = async () => {
  loading.value = true
  try {
    const res = await listProjects(20)
    if (res.success) {
      projects.value = res.data
    }
  } finally {
    loading.value = false
  }
}
```

- [ ] **Step 4: Corregir `navigateToProject` per usar `project_id`**

Localitzar la funció `navigateToProject` i substituir la navegació per:
```javascript
const navigateToProject = (project) => {
  selectedProject.value = project
}
```

(El modal ja existeix — simplement obrim el modal en fer clic, i la navegació efectiva és als botons del modal.)

- [ ] **Step 5: Corregir `goToProject` al modal**

Localitzar `goToProject` i assegurar que navega amb `project_id`:
```javascript
const goToProject = () => {
  if (selectedProject.value?.project_id) {
    router.push({ name: 'Process', params: { projectId: selectedProject.value.project_id } })
    closeModal()
  }
}
```

- [ ] **Step 6: Adaptar els camps de la card al template**

Les cards actuals usen `project.simulation_id`. Hem d'usar `project.id || project.project_id`.

En el template, localitzar totes les referències a `project.simulation_id` i substituir per `project.project_id`:

```bash
grep -n "simulation_id" /home/ubuntu/dev/MiroFish/frontend/src/components/HistoryDatabase.vue
```

Per a cada ocurrència:
- `project.simulation_id` → `project.project_id`
- `formatSimulationId(project.simulation_id)` → `project.name || project.project_id.slice(0, 8)`

Per a les icones d'estat (Step1/Step2/Step4 disponibles):
- `project.project_id` (sempre disponible) → `available`
- simumation disponible: `project.status === 'graph_completed'` o `project.graph_id`
- `project.report_id` → per ara `false` (els informes no estan en scope d'aquest task)

- [ ] **Step 7: Verificar que el component no té errors de lint**

```bash
cd /home/ubuntu/dev/MiroFish && npm run build 2>&1 | tail -20
```

Expected: build successful o errors no relacionats amb HistoryDatabase.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/HistoryDatabase.vue
git commit -m "feat(history): use listProjects API for project recovery in home page"
```

---

## Task 7: Verificació E2E manual

- [ ] **Step 1: Iniciar el servidor de dev**

```bash
cd /home/ubuntu/dev/MiroFish && npm run dev &
```

- [ ] **Step 2: Verificar que el backend arrenca sense errors**

```bash
curl -s http://localhost:5001/api/graph/project/list | python3 -m json.tool
```

Expected: `{"success": true, "data": [...], "count": N}`

- [ ] **Step 3: Verificar que `GET /api/graph/project/list` retorna correctament**

Si hi ha projectes a la BD, han d'aparèixer. Si no, `data: []`.

- [ ] **Step 4: Verificar Recovery UI a la Home**

Obrir http://localhost:3000. Si hi ha projectes a la BD, han d'aparèixer les cards. Fer clic en una card: s'ha d'obrir el modal. Fer clic a "Step1 ◇": ha de navegar a `/process/:projectId`.

- [ ] **Step 5: Aturar el servidor**

```bash
pkill -f "npm run dev" || true
```

---

## Task 8: Tests finals i tag

- [ ] **Step 1: Executar tota la suite**

```bash
cd /home/ubuntu/dev/MiroFish && backend/.venv/bin/pytest backend/tests/ -v -k "not test_config_graph_backend_default" 2>&1 | tail -40
```

Expected: tots passen.

- [ ] **Step 2: Commit final si hi ha canvis pendents**

```bash
git status
```

Si hi ha fitxers modificats no commitejats:
```bash
git add -p
git commit -m "fix(f1-1): remaining fixes from review"
```

- [ ] **Step 3: Tag**

```bash
git tag f1-1-graph-fix-and-recovery-ui
```

---

## Notes d'implementació

### Sessió aniuada a SQLite
`get_session()` usa `sessionmaker` amb `bind=engine`. SQLite accepta múltiples connexions en mode `check_same_thread=False` però cal tenir cura amb transaccions. En els tests (`StaticPool`), totes les connexions comparteixen la mateixa connexió en memòria — obrir una sessió nova dins d'un `with get_session()` és segur perquè SQLite llig l'última transacció comitejada.

### `import tempfile` dins del loop
L'`import` de `tempfile` i `os` dins del loop de fitxers és ineficient però funcional. Millor moure els imports al principi de la funció.

### `project.get("graph_build_task_id")`
El `_to_dict` actual retorna `"graph_build_task_id": None`. La UI de `MainView.vue` ja fa fallback: `active_task_id || graph_build_task_id`. Amb el nou codi, `active_task_id` s'actualitza correctament i `graph_build_task_id` pot romandre `None`.

### HistoryDatabase — camps faltants
`HistoryDatabase.vue` usa `project.files` per mostrar la llista de fitxers. El nou `_to_dict` retorna `"files": []`. Per ara acceptem que les cards no mostrin fitxers (tasca futura: poblar `files` des de `ProjectFileModel`).
