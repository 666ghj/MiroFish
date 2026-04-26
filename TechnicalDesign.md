# Technical Design — MiroFish

## Graph Backend

MiroFish suporta dos backends de knowledge graph, seleccionable via `GRAPH_BACKEND` al `.env`:

| Valor | Backend | Requisits |
|-------|---------|-----------|
| `zep` (per defecte) | Zep Cloud (gestionat) | `ZEP_API_KEY` |
| `graphiti` | Graphiti + Neo4j (self-hosted) | `NEO4J_PASSWORD` + variables LLM |

La selecció es fa via la factoria `backend/app/graph/factory.py` — un singleton que instancia `ZepBackend` o `GraphitiBackend` en funció de `GRAPH_BACKEND`. La validació de configuració és condicionada: si `GRAPH_BACKEND=graphiti`, `ZEP_API_KEY` no és necessari i viceversa.

### Commutació entre backends

Només cal canviar al `.env`:

```env
# Per usar Zep Cloud:
GRAPH_BACKEND=zep
ZEP_API_KEY=z_...

# Per usar Graphiti + Neo4j:
GRAPH_BACKEND=graphiti
NEO4J_URI=bolt://<host>:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<contrasenya>
```

---

## Models LLM

El projecte usa fins a quatre grups de variables LLM, cadascun per a un ús diferent. Totes les variables `LLM_SMALL_*` i `LLM_EMBED_*` fan **fallback** als valors `LLM_*` si no s'estableixen.

### Variables de configuració

```env
# ── Model principal (generatiu, potent) ──────────────────────────────────────
LLM_API_KEY=...
LLM_BASE_URL=https://<recurs>.cognitiveservices.azure.com/openai/deployments/<model>/chat/completions?api-version=2024-05-01-preview
LLM_MODEL_NAME=gpt-5.4

# ── Model petit/ràpid (lightweight, econòmic) ────────────────────────────────
# Fallback a LLM_* si no definit
LLM_SMALL_API_KEY=...
LLM_SMALL_BASE_URL=https://<recurs>.cognitiveservices.azure.com/openai/deployments/<small-model>/chat/completions?api-version=2024-05-01-preview
LLM_SMALL_MODEL_NAME=gpt-5-mini

# ── Model d'embedding (vectorització) ────────────────────────────────────────
# Fallback a LLM_* si no definit. Requerit per Graphiti.
LLM_EMBED_API_KEY=...
LLM_EMBED_BASE_URL=https://<recurs>.services.ai.azure.com/openai/deployments/<embed-model>/embeddings?api-version=2024-05-01-preview
LLM_EMBED_MODEL_NAME=text-embedding-3-large

# ── Model boost (simulació OASIS, opcional) ──────────────────────────────────
# Fallback a LLM_* si no definit
LLM_BOOST_API_KEY=...
LLM_BOOST_BASE_URL=...
LLM_BOOST_MODEL_NAME=gpt-5.4
```

### Mapa d'usos per operació

| Grup de variables | Component | Operació |
|---|---|---|
| `LLM_*` | `OntologyGenerator` | Pas 1 — Anàlisi del document i generació d'ontologia (tipus d'entitat i relació) |
| `LLM_*` | `GraphBuilderService` (mode Zep) | Pas 2 — Extracció d'entitats i relacions del text via Zep SDK |
| `LLM_*` | Graphiti `OpenAIClient` (mode graphiti) | Pas 2 — Extracció d'entitats i relacions del text via graphiti-core |
| `LLM_*` | `OasisProfileGenerator` | Pas 2 — Generació de perfils d'agents OASIS a partir del graf |
| `LLM_*` | `ReportAgent` | Pas 4 — Generació de l'informe analític final (multi-turn, tool use) |
| `LLM_SMALL_*` | Graphiti `OpenAIRerankerClient` | Pas 2 — Reranking de resultats de cerca al graf (mode graphiti) |
| `LLM_SMALL_*` | Graphiti `ModelSize.small` | Pas 2 — Tasques lleugeres internes de graphiti (extracció simplificada) |
| `LLM_EMBED_*` | Graphiti `OpenAIEmbedder` | Pas 2 — Generació de vectors d'embedding per a indexació i cerca semàntica a Neo4j (mode graphiti) |
| `LLM_BOOST_*` | `SimulationRunner` / `run_parallel_simulation.py` | Pas 3 — Decisions d'acció de cada agent durant la simulació OASIS |

### API endpoint usada per cada component

Tots els components del projecte usen **`chat.completions`** o **`embeddings`** — mai `responses` (beta).

| Component | API endpoint | Nota |
|---|---|---|
| `LLMClient` (wrapper projecte) | `chat.completions.create` | Síncrona (`OpenAI`) |
| `OntologyGenerator` | `chat.completions.create` | Via `LLMClient` |
| `OasisProfileGenerator` | `chat.completions.create` | Client intern |
| `SimulationConfigGenerator` | `chat.completions.create` | Client intern |
| `ReportAgent` | `chat.completions.create` | Via `LLMClient` |
| Graphiti `OpenAIGenericClient` | `chat.completions.create` | AsyncOpenAI, injectable |
| Graphiti `OpenAIRerankerClient` | `chat.completions.create` | Amb `logprobs=True` per scoring |
| Graphiti `OpenAIEmbedder` | `embeddings.create` | AsyncOpenAI, injectable |
| OASIS/CAMEL-AI | `chat.completions.create` | Via `ModelFactory` (CAMEL abstraction) |

> **Nota:** graphiti-core inclou també un `OpenAIClient` que usa `responses.parse` (API beta d'OpenAI). MiroFish **no l'usa** — configura `OpenAIGenericClient` que sempre usa `chat.completions`, compatible amb Azure i qualsevol API OpenAI-compatible.

### Notes sobre Azure OpenAI

- `LLM_BASE_URL` accepta la URL completa d'Azure (`/chat/completions?api-version=...`). El codi la processa automàticament: extreu el `api-version` com a `default_query` i retalla el sufix per al SDK.
- El mateix tractament s'aplica a `LLM_EMBED_BASE_URL` (sufix `/embeddings?api-version=...`).
- `LLM_SMALL_BASE_URL` accepta directament la URL base d'Azure AI Foundry (`services.ai.azure.com/api/projects/<proj>/openai/v1/`) sense sufix ni `api-version`.
- `LLM_EMBED_BASE_URL` pot usar el domini `services.ai.azure.com` o `cognitiveservices.azure.com`.

### Recomanació de models (Azure OpenAI)

| Grup | Model recomanat | Motiu |
|------|----------------|-------|
| `LLM_*` | `gpt-5.4` | Raonament complex: ontologia, extracció de graf, informes |
| `LLM_SMALL_*` | `gpt-5-mini` | Tasques lleugeres i econòmiques: reranking, classificació |
| `LLM_EMBED_*` | `text-embedding-3-large` | Màxima qualitat d'embedding semàntic |
| `LLM_BOOST_*` | `gpt-5.4` o `gpt-5-mini` | Simulació: moltes crides curtes, prioritzar velocitat/cost |

---

## Pipeline de 5 passos

```
Pas 1 — Graph Build (ontologia)
  └─ OntologyGenerator  →  LLM_*

Pas 2 — Graph Build (construcció)
  ├─ mode zep:      GraphBuilderService + Zep SDK  →  LLM_*
  └─ mode graphiti: GraphitiBackend
       ├─ extracció:   OpenAIGenericClient  →  LLM_*  (chat.completions)
       ├─ reranking:   OpenAIRerankerClient  →  LLM_SMALL_*
       └─ embedding:   OpenAIEmbedder    →  LLM_EMBED_*

Pas 3 — Simulació OASIS
  └─ SimulationRunner / run_parallel_simulation.py  →  LLM_BOOST_* (o LLM_*)

Pas 4 — Informe
  └─ ReportAgent (multi-turn + tool use)  →  LLM_*

Pas 5 — Interacció live
  └─ Chat amb agents simulats  →  LLM_*
```

---

## Internacionalització (i18n)

- Fitxers de traducció: `/locales/{ca,en,es,zh}.json` — compartits per frontend i backend.
- Instruccions de llengua per al LLM: `/locales/languages.json` (clau `llmInstruction`).
- El frontend injecta el locale actual via header `Accept-Language` a cada petició API.
- El backend detecta el locale a `backend/app/utils/locale.py:get_locale()` i l'usa per:
  - Traduccions de missatges d'error (`t()`)
  - Instruccions d'idioma als prompts LLM (`get_language_instruction()`)
- L'ontologia generada (descripcions, exemples, `analysis_summary`) sortirà en l'idioma de la UI. Els **noms** de tipus d'entitat i relació seguiran PascalCase/UPPER\_SNAKE\_CASE en l'idioma de la UI (p.ex. `AgenciaGovern`, `TREBALLA_PER` en català).
