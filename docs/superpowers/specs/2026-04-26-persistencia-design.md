# Disseny: Capa de Persistència MiroFish

## 1. Context i motivació

MiroFish es desplega com a contenidor Docker. Sense volums muntats, tot el que es guarda al filesystem del contenidor (`backend/uploads/`) es perd en cada reinici o redeploy. A més:

- `TaskManager` és 100% in-memory: cada reinici invalida les tasques en curs, impedint recovery de l'usuari
- `ProjectManager` persisteix via JSON a disc: funcional en dev però no en contenidors efímers ni en multi-instància
- No hi ha gestió d'usuaris: tots els projectes són globals i sense propietari
- No hi ha configuració dinàmica: tots els paràmetres d'LLM, límits i features van hard-coded a variables d'entorn

Aquest disseny estableix la capa de persistència completa que farà l'aplicació viable en producció.

---

## 2. Principis de disseny

1. **Abstracció total del backend** — les capes de negoci mai toquen SQL ni fitxers directament; ho fan a través de `StorageService` i sessions SQLAlchemy
2. **Un URL, dos entorns** — `DATABASE_URL` i `STORAGE_TYPE` seleccionen el backend; el codi de negoci no canvia
3. **Paths estables** — els `storage_path` guardats a la BD no depenen del backend de storage; l'adaptador els resol
4. **Dades de simulació OASIS separades** — els fitxers `.db` SQLite del motor OASIS es tracten com a artefactes i es guarden a storage, no a la BD de l'app
5. **Configuració dinàmica per admins** — paràmetres modificables en runtime van a `SystemConfig` a la BD, no a variables d'entorn

---

## 3. Arquitectura general

```
┌─────────────────────────────────────────┐
│  Flask Routes                           │
├─────────────────────────────────────────┤
│  Services (ProjectService, AuthService, │
│  SimulationService, ReportService...)   │
│    → usen StorageService + DB Session   │
├──────────────────┬──────────────────────┤
│  StorageService  │  SQLAlchemy 2.x      │
│  (Protocol)      │  Session Factory     │
├────────┬─────────┼──────────────────────┤
│LocalFS │AzureBlob│  SQLite (dev)        │
│        │  (S3*)  │  PostgreSQL (prod)   │
└────────┴─────────┴──────────────────────┘

* S3: interfície dissenyada, implementació diferida
```

---

## 4. Model de dades (SQLAlchemy 2.x)

### User

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| email | text unique | |
| name | text | |
| password_hash | text | bcrypt |
| role | enum: user\|admin | |
| status | enum: pending\|active\|disabled | |
| created_at | datetime | |
| updated_at | datetime | |

### Project

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| user_id | FK → User | CASCADE delete |
| name | text | |
| status | text | created\|ontology_generated\|graph_building\|graph_completed\|failed |
| analysis_summary | text nullable | resum LLM del document |
| simulation_requirement | text nullable | pregunta de simulació |
| chunk_size | int | default 500 |
| chunk_overlap | int | default 50 |
| active_task_id | FK → Task nullable | ON DELETE SET NULL |
| created_at | datetime | |
| updated_at | datetime | |

### ProjectFile

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| project_id | FK → Project | CASCADE delete |
| original_name | text | nom original del fitxer |
| storage_path | text | path relatiu a StorageService |
| size | int | bytes |
| mime_type | text | |
| file_type | enum: upload\|extracted_text | |
| created_at | datetime | |

### Ontology

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| project_id | FK → Project | CASCADE delete |
| version | int | default 1, incrementa en re-generació |
| entity_types | JSON | llista de {name, description, attributes, examples} |
| edge_types | JSON | llista de {name, source_targets, attributes} |
| created_at | datetime | |

### Graph

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| project_id | FK → Project | CASCADE delete |
| ontology_id | FK → Ontology | quin esquema va usar |
| backend | enum: zep\|graphiti | |
| external_id | text | ID a Zep Cloud o nom del graf Neo4j |
| status | enum: building\|ready\|failed | |
| node_count | int nullable | stats post-build |
| edge_count | int nullable | stats post-build |
| created_at | datetime | |
| updated_at | datetime | |

### Simulation

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| project_id | FK → Project | CASCADE delete |
| graph_id | FK → Graph | quin graf usa |
| status | text | prepared\|running\|completed\|failed |
| platform | enum: twitter\|reddit\|both | |
| config | JSON | time steps, events, agent params |
| profiles_path | text nullable | storage_path al JSON/CSV perfils |
| db_path | text nullable | storage_path al fitxer .db OASIS |
| actions_path | text nullable | storage_path al JSONL accions |
| rounds_total | int nullable | |
| rounds_completed | int | default 0 |
| created_at | datetime | |
| updated_at | datetime | |

### Report

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| project_id | FK → Project | CASCADE delete |
| simulation_id | FK → Simulation | |
| graph_id | FK → Graph | per fer queries Zep durant generació |
| status | text | generating\|completed\|failed |
| outline | JSON nullable | estructura de seccions |
| storage_prefix | text | prefix del directori a storage |
| created_at | datetime | |
| updated_at | datetime | |

### Task

| camp | tipus | notes |
|------|-------|-------|
| id | UUID PK | |
| task_type | text | ontology_generate\|graph_build\|simulation_prepare\|etc. |
| entity_type | text | project\|simulation\|report |
| entity_id | text | UUID de l'entitat relacionada |
| status | enum: pending\|processing\|completed\|failed | |
| progress | int | 0–100 |
| message | text nullable | missatge de progrés |
| result | JSON nullable | resultat final |
| error | text nullable | error si failed |
| created_at | datetime | |
| updated_at | datetime | |

### SystemConfig

| camp | tipus | notes |
|------|-------|-------|
| key | text PK | p.ex. `llm.api_key` |
| value | text | valor serialitzat |
| value_type | enum: string\|int\|float\|bool\|json | per deserialitzar |
| group | enum: llm\|limits\|email\|graph\|features | agrupació UI |
| label | text | text llegible |
| description | text | |
| is_secret | bool | emmascara el valor a la UI |
| updated_at | datetime | |
| updated_by | FK → User nullable | qui va fer el canvi |

#### Claus predefinides per grup

| group | key | secret |
|-------|-----|--------|
| llm | llm.api_key | sí |
| llm | llm.base_url | no |
| llm | llm.model_name | no |
| llm | llm.boost_model_name | no |
| graph | graph.backend | no |
| graph | graph.zep_api_key | sí |
| limits | limits.max_projects_per_user | no |
| limits | limits.max_file_size_mb | no |
| limits | limits.max_simulation_agents | no |
| email | email.sender_address | no |
| email | email.acs_endpoint | no |
| email | email.acs_key | sí |
| features | features.registration_open | no |

### InvitationToken

| camp | tipus | notes |
|------|-------|-------|
| token | text PK | UUID o token segur |
| user_id | FK → User | CASCADE delete |
| expires_at | datetime | TTL 48h |
| used_at | datetime nullable | null = no usat |

### PasswordResetToken

| camp | tipus | notes |
|------|-------|-------|
| token | text PK | |
| user_id | FK → User | CASCADE delete |
| expires_at | datetime | TTL 1h |
| used_at | datetime nullable | |

### Relacions clau

```
User ──1:N──► Project ──1:N──► ProjectFile
                      ──1:N──► Ontology ──1:N──► Graph ──1:N──► Simulation ──1:N──► Report
                      ──1:N──► Task (via entity_id)
```

- `Project.active_task_id` → FK → Task amb `ON DELETE SET NULL`
- Eliminació User → CASCADE elimina tots els seus Projects i descendents
- Eliminació Project → CASCADE elimina Files, Ontologies, Graphs, Simulations, Reports

---

## 5. StorageService (abstracció de fitxers)

### Interfície Protocol (Python)

```python
from typing import IO, Protocol

class StorageService(Protocol):
    def upload(self, path: str, data: bytes | IO, content_type: str) -> None: ...
    def download(self, path: str) -> bytes: ...
    def download_stream(self, path: str) -> IO: ...
    def delete(self, path: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def public_url(self, path: str) -> str | None: ...
```

### Implementacions

| `STORAGE_TYPE` | Classe | Dependència |
|---|---|---|
| `local` | `LocalFSStorage` | stdlib `pathlib` |
| `azure` | `AzureBlobStorage` | `azure-storage-blob` |
| `s3` *(disseny llest, no implementat)* | `S3Storage` | `boto3` |

La selecció es fa a l'inici de l'app via `STORAGE_TYPE`:

```python
def create_storage_service() -> StorageService:
    match os.environ.get("STORAGE_TYPE", "local"):
        case "azure": return AzureBlobStorage(...)
        case "s3":    return S3Storage(...)       # futur
        case _:       return LocalFSStorage(...)
```

### Convenció de paths

Els paths guardats a la BD són relatius i independents del backend:

```
projects/{project_id}/files/{filename}
projects/{project_id}/extracted_text.txt
simulations/{sim_id}/{platform}_simulation.db
simulations/{sim_id}/profiles.json
simulations/{sim_id}/twitter_profiles.csv
simulations/{sim_id}/actions.jsonl
reports/{report_id}/full_report.md
reports/{report_id}/section_{nn}.md
reports/{report_id}/agent_log.jsonl
reports/{report_id}/console_log.txt
```

En canviar de `local` a `azure` (o `s3`), els paths a la BD no canvien — només l'adaptador que els resol.

---

## 6. Autenticació i RBAC

### Mecanisme

- **JWT** via `flask-jwt-extended`
- Access token: 8h, en cookie HTTP-only
- Refresh token: 7 dies, en cookie HTTP-only
- Cap token en `localStorage` (evita XSS)

### Rols i accés

| Rol | Accés |
|-----|-------|
| `user` | Veu i gestiona els seus propis projectes |
| `admin` | Veu tots els projectes + gestió d'usuaris + SystemConfig |

Decoradors Flask:

```python
@require_auth          # qualsevol usuari autenticat
@require_admin         # només admins
@require_project_owner # propietari del projecte o admin
```

### Flux d'invitació

```
Admin crea usuari (status: pending)
  → email amb InvitationToken (TTL 48h)
  → usuari clica l'enllaç, defineix contrasenya
  → status: active
```

### Endpoints d'autenticació

```
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
POST /api/auth/set-password     (invitació + primer login)
POST /api/auth/forgot-password
POST /api/auth/reset-password
```

---

## 7. SystemConfig: resolució de valors

Prioritat descendent (el primer que es trobi guanya):

1. **Variable d'entorn** — sobreescriu tot; útil per secrets en CI/CD
2. **`SystemConfig` a la BD** — configurable per admins via UI en runtime
3. **Valor per defecte al codi** — fallback si no hi ha cap dels anteriors

```python
def get_config(key: str, default=None):
    env_key = key.replace(".", "_").upper()  # llm.api_key → LLM_API_KEY
    if val := os.environ.get(env_key):
        return val
    if row := db.query(SystemConfig).get(key):
        return row.typed_value
    return default
```

---

## 8. Variables d'entorn (infraestructura)

Les variables d'entorn cobreixen exclusivament la infraestructura (no modificables en runtime):

```env
# Base de dades
DATABASE_URL=sqlite:///dev.db
# DATABASE_URL=postgresql://user:pass@host:5432/mirofish

# Storage
STORAGE_TYPE=local
STORAGE_LOCAL_PATH=./uploads
# STORAGE_TYPE=azure
AZURE_STORAGE_CONNECTION_STRING=...
AZURE_STORAGE_CONTAINER=mirofish

# Autenticació
JWT_SECRET=...
JWT_REFRESH_SECRET=...

# Entorn
ENVIRONMENT=development
# ENVIRONMENT=production
```

Paràmetres com `LLM_API_KEY`, `LLM_MODEL_NAME`, `ZEP_API_KEY`, límits i features van a `SystemConfig` (amb fallback a variable d'entorn per compatibilitat).

---

## 9. Fases d'implementació

### Fase 1 — Infraestructura base

**Objectiu:** BD + storage funcionals, `ProjectManager` i `TaskManager` migrats.

- Configurar SQLAlchemy 2.x + Alembic (migració inicial)
- Crear tots els models SQLAlchemy
- Implementar `StorageService` + `LocalFSStorage` + `AzureBlobStorage`
- Migrar `ProjectManager` (JSON → BD)
- Migrar `TaskManager` (memòria → BD)
- Injectar `StorageService` i sessió DB a Flask via app factory

**Verificació:** crear projecte, pujar fitxer, crear task → reiniciar servidor → verificar que tot sobreviu

---

### Fase 2 — Autenticació i multi-usuari

**Objectiu:** login, RBAC i aïllament de dades per usuari.

- Models `User`, `InvitationToken`, `PasswordResetToken`
- JWT via `flask-jwt-extended` (cookies HTTP-only)
- Decoradors `@require_auth`, `@require_admin`, `@require_project_owner`
- Flux invitació + reset contrasenya
- Totes les rutes de `Project` filtrades per `user_id`

**Verificació:** login, accés projecte propi, bloqueig projecte d'altri, flux invitació complet

---

### Fase 3 — Migració pipeline complet

**Objectiu:** les 5 etapes del pipeline usen BD + storage.

- `GraphBuilder` → desa `Ontology` + `Graph` a BD
- `SimulationRunner` → desa `.db` OASIS a `StorageService`, metadades a `Simulation`
- `ReportAgent` → desa seccions a `StorageService`, metadades a `Report`
- `SystemConfig` operatiu (LLM keys, Zep key, límits via BD)

**Verificació:** pipeline end-to-end (upload → ontologia → graf → simulació → report) amb BD + storage

---

### Fase 4 — Hardening producció

**Objectiu:** desplegament estable en contenidor amb PostgreSQL + Azure Blob.

- Configurar PostgreSQL + connection pool (SQLAlchemy `pool_size`, `max_overflow`)
- Configurar Azure Blob Storage
- `.env.dev` i `.env.prod` per entorn
- Health check endpoint (`GET /api/health`) que verifica BD + storage
- Smoke tests en contenidor Docker

**Verificació:** `docker build` + `docker run` sense volums → pipeline complet → reinici contenidor → dades persistides

---

## 10. Verificació end-to-end

```
1. Arrancar en mode dev (SQLite + LocalFS)
2. Crear projecte → verificar fila a BD + fitxer a uploads/
3. Executar pipeline complet → verificar Ontology, Graph, Simulation, Report a BD
4. Reiniciar servidor → verificar que projecte, tasks i fitxers sobreviuen
5. Canviar STORAGE_TYPE=azure → verificar que paths a BD no canvien
6. Canviar DATABASE_URL=postgresql://... + alembic upgrade head → verificar sense errors
7. Reiniciar contenidor sense volum → verificar dades persistides a BD + Azure Blob
```
