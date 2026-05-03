# Spec F2-A: Edició, Regeneració i Clonació d'Agents

**Data:** 2026-05-03  
**Fase:** Fase 2-A del roadmap enterprise (2026-04-26-enterprise-roadmap.md)  
**Estat:** Aprovat per disseny

---

## Context

La Fase 2 del roadmap enterprise té com a objectiu un flux iteratiu:
construir graf → ajustar agents → simular → ajustar → re-simular.

Fins ara, MiroFish genera N agents a partir del graf de forma automàtica i no
permet modificar-los ni reutilitzar-los entre simulacions. L'usuari ha de
reconstruir tot el projecte si vol ajustar qualsevol cosa.

Aquesta spec cobreix:
1. **Selector de nombre d'agents** — triar top-N per connectivitat abans de generar
2. **Edició d'agents individuals** — editar camps LLM-generats d'un agent concret
3. **Regeneració individual** — demanar al LLM que torni a generar un agent concret
4. **Clonació de simulació** — crear una nova simulació dins el mateix projecte
   partint dels agents i config d'una simulació anterior

### Nota sobre l'arquitectura de grafs (F2-D)

El flag `enable_graph_memory_update` resta a `False` (default actual) durant F2-A.
Els reports es basen en el `graph_document` pur. L'arquitectura de múltiples
`group_id` per simulació (F2-D) es resoldrà en una fase posterior: clonar el
`graph_document` → `graph_sim_N` via Neo4j/APOC just abans de llançar cada
simulació (viable perquè Neo4j Aura Cloud inclou APOC de sèrie).

---

## Model de dades

### Canvi a la BD: `parent_simulation_id`

Afegir una columna nullable a la taula `simulations`:

```sql
ALTER TABLE simulations ADD COLUMN parent_simulation_id VARCHAR(64) REFERENCES simulations(simulation_id);
```

- `NULL` → simulació nova (comportament actual)
- Valor → simulació clonada d'una existent

No hi ha canvis a cap altra taula ni model existent.

### Immutabilitat de simulacions completades

Una simulació amb `status IN ('completed', 'running')` no es pot editar.
Una simulació amb `status IN ('created', 'prepared', 'stopped', 'failed')` és editable.

### Camps editables d'un perfil d'agent

Editables (LLM-generats): `name`, `bio`, `persona`, `age`, `gender`, `mbti`,
`country`, `profession`, `interested_topics`, `stance`, `sentiment_bias`, `activity_level`.

Immutables (OASIS els necessita intactes): `user_id`, `source_entity_uuid`, `source_entity_type`.

### Flag de protecció contra sobreescriptura

Cada agent té un flag `manually_edited: bool` (default `False`) a
`reddit_profiles.json` i `simulation_config.json`. Quan el generador inicial
treballa en batch, salta els agents amb `manually_edited: True`.

---

## Subsistema 1: Selector de nombre d'agents (pre-generació)

### Comportament

Abans del botó "Generar agents" al Step 2, el sistema consulta quantes entitats
hi ha disponibles al graf. Mostra el total com a suggeriment (ex: "66 agents
disponibles"). L'usuari pot reduir el número. Si no toca res, el comportament
és idèntic a l'actual (es generen tots).

Si l'usuari redueix a N, el backend selecciona les **top-N entitats per grau de
connectivitat** (nombre d'edges entrants + sortints al graf Zep). Les entitats
més connectades representen els actors amb més relacions al document, i generen
simulacions socialment més riques.

**Mínim recomanat:** 15 agents (mida de batch de generació; per sota, la dinàmica
social és molt pobra). El frontend mostra un avís si l'usuari intenta posar menys de 15.

### Canvis al backend

**`POST /api/simulation/prepare`** — afegir paràmetre opcional:
```json
{ "max_agents": 40 }
```

Si `max_agents` present, `ZepEntityReader` ordena les entitats filtrades per
grau de connectivitat descendent i agafa les primeres N.

Canvis a `oasis_profile_generator.py` / `simulation.py`:
- `ZepEntityReader.get_entities_by_connectivity(graph_id, max_n)` → nova funció
- Ordena per `len(edges)` de cada node retornat per `get_all_edges()`

### Canvis al frontend (Step 2)

Afegir just abans del botó "Generar agents":
- Crida a `GET /api/simulation/entities/{graph_id}` (ja existent) per obtenir el
  total d'entitats disponibles
- Camp numèric amb valor default = total disponible
- Avís visual si valor < 15
- El valor es passa a `POST /api/simulation/prepare` com a `max_agents`

---

## Subsistema 2: Edició d'agents individuals

### Comportament

El modal de visualització d'agents (ja existent a `Step2EnvSetup.vue`) afegeix
un botó "Editar" que converteix els camps en inputs editables. En desar, el
backend actualitza el perfil i marca `manually_edited: True`.

L'edició és possible:
- Durant la generació (altres agents en curs) → l'agent editat queda protegit
- Després de la generació completa
- No és possible si la simulació té `status: running` o `completed`

### Canvis al backend

**`PATCH /api/simulation/{sim_id}/agent/{user_id}`**

```
Body: { camps editables (qualsevol subconjunt) }
```

Acció:
1. Valida que la simulació no és `running` ni `completed`
2. Carrega `reddit_profiles.json` i `simulation_config.json`
3. Localitza l'agent per `user_id`
4. Aplica els canvis + `manually_edited: True`
5. Desa els fitxers atòmicament (backup previ → escriptura → elimina backup si OK, restaura si falla)
6. Retorna el perfil actualitzat

### Canvis al frontend (Step 2)

Al modal d'agent (`Step2EnvSetup.vue`):
- Botó "Editar" → converteix camps en `<input>` / `<textarea>` / `<select>`
- Botó "Desa" → `PATCH` → refrescar el modal amb dades actualitzades
- Botó "Cancel·la" → descarta canvis locals
- Indicador visual "Editat manualment" a la card de l'agent si `manually_edited: True`

---

## Subsistema 3: Regeneració d'agents individuals

### Comportament

Disponible **només** quan la generació inicial ha completat (`status: prepared`).
No disponible si la simulació és `running` o `completed`.

L'usuari pot opcionalment afegir instruccions addicionals per al LLM
(ex: "Fes-lo més escèptic respecte a les polítiques de salut pública").

La regeneració és **asíncrona** (pot trigar 5-15 s). El modal mostra un spinner
mentre el `task_id` associat és en curs. En completar, refrescar automàticament
el modal amb el nou perfil.

### Canvis al backend

**`POST /api/simulation/{sim_id}/agent/{user_id}/regenerate`**

```
Body: { "extra_instructions": "..." }  // opcional
```

Acció:
1. Valida que la simulació és `prepared` (no `running`, no `completed`)
2. Llegeix l'agent actual per obtenir `source_entity_uuid`
3. Consulta Zep per obtenir el context de l'entitat original
4. Crida `OasisProfileGenerator.generate_profile_from_entity()` amb `use_llm=True`
   i `extra_instructions` opcional
5. Actualitza `reddit_profiles.json`, `twitter_profiles.csv` i `simulation_config.json`
6. Retorna `task_id` per polling

**Polling:** reutilitza el mecanisme existent `GET /api/.../task/{task_id}`.

### Canvis al frontend (Step 2)

Al modal d'agent (visible només si `is_preparing === False`):
- Botó "Regenera" → obre un petit camp de text per a instruccions addicionals (opcional)
- Confirmar → `POST .../regenerate` → mostra spinner al modal
- Poll `task_id` cada 2s → en `completed`, refrescar modal
- En `failed`, mostrar missatge d'error

---

## Subsistema 4: Clonació de simulació

### Comportament

Al Step 2, just sobre el botó "Generar agents", un desplegable:
- **"Nova simulació"** (default) → comportament actual, genera des de zero
- **"Des de [nom/data sim anterior]"** → clona agents i config d'una simulació existent

Simulacions clonables: qualsevol simulació del mateix projecte que tingui
agents generats (`status NOT IN ('created')`). Inclou `prepared`, `running`,
`stopped`, `failed`, `completed`.

En triar una simulació font, el Step 2 crida `POST /clone` i **carrega
directament** amb els agents clonats (salta la generació, estat = `prepared`).
L'usuari pot llavors editar agents, regenerar-ne, i llançar la simulació.

### Canvis al backend

**`GET /api/simulation/list?project_id={id}`** — ja existent, retorna les
simulacions del projecte. El frontend filtra les clonables.

**`POST /api/simulation/{sim_id}/clone`**

```
Body: { "project_id": "proj_xxxx" }
```

Acció:
1. Valida que `sim_id` té agents (`status != 'created'`)
2. Crea nova simulació al projecte amb `status: prepared`
3. Guarda `parent_simulation_id = sim_id`
4. Copia fitxers: `reddit_profiles.json`, `twitter_profiles.csv`,
   `simulation_config.json`, `agent_profiles.json`
5. Retorna `new_simulation_id`

### Canvis al frontend (Step 2)

- Desplegable "Nova simulació / Des de..." que carrega les simulacions del projecte
- En seleccionar una simulació font → `POST /clone` → redirigir al Step 2 amb el nou `simulation_id`
- El Step 2 detecta que la simulació ja té estat `prepared` i mostra els agents directament

---

## Ordre d'implementació recomanat

1. `PATCH /agent/{user_id}` + edició modal (menys risc, més valor immediat)
2. Selector de N agents pre-generació (extensió de `/prepare`)
3. `POST /agent/{user_id}/regenerate` + UI polling
4. `POST /clone` + desplegable Step 2 + `parent_simulation_id` a la BD

---

## Verificació end-to-end

### Test 1: Edició d'agent
- Generar agents per a un projecte
- Obrir modal d'un agent → clicar "Editar" → modificar `bio` i `stance`
- Desar → verificar que el modal mostra els valors actualitzats
- Verificar que la card de l'agent mostra l'indicador "Editat manualment"
- Iniciar la preparació d'un altre agent → verificar que l'agent editat NO es sobreescriu

### Test 2: Regeneració individual
- Completar la generació d'agents
- Obrir modal → clicar "Regenera" amb instrucció "Fes-lo més escèptic"
- Verificar spinner mentre processa
- Verificar que el perfil canvia i és coherent amb la instrucció

### Test 3: Selector N agents
- Projecte amb 50 entitats disponibles
- Reduir a 30 → verificar que es generen exactament 30 agents
- Verificar que els 30 corresponen a les entitats més connectades del graf
- No tocar el selector → verificar que es generen els 50 (comportament actual)

### Test 4: Clonació
- Completar una simulació (sim1) dins un projecte
- Al Step 2 del mateix projecte (nova simulació) → seleccionar "Des de sim1"
- Verificar que el Step 2 carrega amb els mateixos agents que sim1
- Editar un agent → llançar simulació
- Verificar que sim1 queda intacta

---

## Dependències i notes futures

- **F2-B** (paràmetres simulació): independent, es pot fer en paral·lel
- **F2-D** (multi-graph per simulació): desbloquejarà `enable_graph_memory_update=True`
  per simulació; la clonació de `graph_document` via Neo4j/APOC és el mecanisme
  previst (viable en Neo4j Aura Cloud que inclou APOC de sèrie)
- **F3** (UI de llistat de simulacions per projecte): el `parent_simulation_id`
  que afegim aquí ja prepara el terreny per a un arbre de versions navegable
