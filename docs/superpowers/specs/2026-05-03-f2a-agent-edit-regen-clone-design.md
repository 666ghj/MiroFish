# Spec F2-A+B: Agents Configurables i Paràmetres de Simulació

**Data:** 2026-05-03
**Fases:** F2-A i F2-B del roadmap enterprise (2026-04-26-enterprise-roadmap.md)
**Estat:** Aprovat per disseny

---

## Context

La Fase 2 del roadmap enterprise té com a objectiu un flux iteratiu:
construir graf → ajustar agents → simular → ajustar → re-simular.

Fins ara el Step 2 és un pas únic i automàtic: genera perfils d'agents i
config de simulació sense pauses ni possibilitat d'edició. L'usuari ha de
reconstruir tot el projecte si vol ajustar qualsevol cosa.

Aquesta spec cobreix:

1. **Redisseny del flux Step 2** en tres fases amb confirmació explícita
2. **Selector de nombre d'agents** — top-N per connectivitat
3. **Edició, regeneració, creació i eliminació d'agents individuals** (Fase A)
4. **Edició de paràmetres de comportament i simulació** (Fase B)
5. **Clonació de simulació** — reutilitzar agents i config d'una simulació anterior
6. **Aïllament de grafs per simulació** — cada simulació té el seu propi `group_id` Neo4j

---

## Redisseny del flux Step 2

El Step 2 passa de ser un pas únic a tenir tres fases seqüencials:

```
FASE A — Generació i edició de personalitats
  El sistema genera els perfils d'agents (nom, bio, persona, mbti, etc.)
  L'usuari pot retocar, regenerar, crear o eliminar agents.
  → L'usuari prem "Continuar" quan està satisfet

FASE B — Generació i edició de config de comportament
  El sistema genera la config de comportament dels agents restants
  (posts_per_hour, active_hours, etc.) i els paràmetres globals de simulació
  (total_simulation_hours, pesos de plataforma, etc.).
  L'usuari pot editar qualsevol d'aquests paràmetres.
  → L'usuari prem "Iniciar simulació" per passar al Step 3

FASE C — Step 3: Llançament
  (sense canvis respecte a l'actual)
```

**Camps editables per fase:**

- **Fase A** (per agent): `name`, `bio`, `persona`, `age`, `gender`, `mbti`,
  `country`, `profession`, `interested_topics`, `stance`, `sentiment_bias`
- **Fase B** (per agent): `posts_per_hour`, `comments_per_hour`, `active_hours`,
  `response_delay_min`, `response_delay_max`, `activity_level`, `influence_weight`
- **Fase B** (globals simulació): `total_simulation_hours`, `minutes_per_round`,
  `agents_per_hour_min`, `agents_per_hour_max`, `following_probability`, `recsys_type`,
  `recency_weight`, `popularity_weight`, `relevance_weight`, `viral_threshold`,
  `echo_chamber_strength`

---

## Model de dades

### Nou estat de simulació: `profiles_ready`

El cicle d'estats s'amplia:

```
created → preparing → profiles_ready → configuring → prepared → running → completed
                                                                         → stopped
                                                                         → failed
```

- `profiles_ready`: perfils d'agents generats, esperant confirmació de l'usuari per generar config
- `configuring`: generant config de comportament i simulació (async)
- `prepared`: config generada, llest per llançar (estat actual)

### Canvi a la BD: `parent_simulation_id`

```sql
ALTER TABLE simulations
  ADD COLUMN parent_simulation_id VARCHAR(64) REFERENCES simulations(simulation_id);
```

- `NULL` → simulació nova
- Valor → simulació clonada d'una existent

### Canvi a la BD: `graph_id_simulation`

```sql
ALTER TABLE simulations
  ADD COLUMN graph_id_simulation VARCHAR(128);
```

Conté el `group_id` Neo4j exclusiu d'aquesta simulació. `NULL` fins que s'inicia.

### Immutabilitat

- `status IN ('completed', 'running')` → no es pot editar
- `status IN ('created', 'preparing', 'profiles_ready', 'configuring', 'prepared', 'stopped', 'failed')` → editable

### Flag de protecció contra sobreescriptura

Cada agent porta `manually_edited: bool` (default `False`) a `reddit_profiles.json`
i `simulation_config.json`. El generador en batch salta els agents amb
`manually_edited: True`.

---

## Subsistema 1: Selector de nombre d'agents (pre-generació)

### Comportament

Abans d'iniciar la Fase A, el sistema consulta quantes entitats hi ha disponibles
al graf i mostra el total com a suggeriment. L'usuari pot reduir el número.
Si no toca res, el comportament és idèntic a l'actual (es generen tots).

Si l'usuari redueix a N, el backend selecciona les **top-N entitats per grau de
connectivitat** (edges entrants + sortints). Les entitats més connectades generen
simulacions socialment més riques.

**Mínim recomanat:** 15 agents. El frontend mostra un avís si el valor és inferior.

### Canvis al backend

`POST /api/simulation/prepare` — nou paràmetre opcional `max_agents: int`.

Nova funció: `ZepEntityReader.get_entities_by_connectivity(graph_id, max_n)` —
obté totes les entitats, les ordena per nombre d'edges i retorna les top-N.

### Canvis al frontend (Step 2)

Just abans d'iniciar la generació:

- `GET /api/simulation/entities/{graph_id}` per obtenir el total disponible
- Camp numèric amb valor default = total disponible
- Avís visual si valor < 15
- Desplegable "Nova simulació / Des de simulació anterior" (vegeu Subsistema 5)
- El valor es passa a `POST /api/simulation/prepare` com a `max_agents`

---

## Subsistema 2: Fase A — Edició de personalitats d'agents

### Comportament

La Fase A comença quan el primer agent és generat. L'usuari veu les cards
d'agents aparèixer progressivament. En completar-se la generació, apareix el
botó "Continuar →" que activa la Fase B.

Mentre la generació és en curs o un cop completada, l'usuari pot:

- **Editar** qualsevol agent ja generat
- **Regenerar** un agent (un cop la generació completa, `status: profiles_ready`)
- **Crear** un agent nou basat en una entitat del graf
- **Eliminar** un agent

### 2a. Edició d'un agent

**Backend:** `PATCH /api/simulation/{sim_id}/agent/{user_id}`

```json
{ "bio": "...", "stance": "opposing" }
```

Acció:

1. Valida `status NOT IN ('running', 'completed')`
2. Carrega `reddit_profiles.json`
3. Localitza l'agent per `user_id`, aplica canvis + `manually_edited: True`
4. Desa atòmicament (backup → escriptura → elimina backup si OK, restaura si falla)
5. Retorna el perfil actualitzat

**Frontend:** modal d'agent existent amb botó "Editar" que activa mode edició.
Camps editables de Fase A com `<input>` / `<textarea>` / `<select>`.
Botó "Desa" / "Cancel·la". Indicador "Editat manualment" a la card si `manually_edited: True`.

### 2b. Regeneració d'un agent existent

Disponible només quan `status: profiles_ready`.

**Backend:** `POST /api/simulation/{sim_id}/agent/{user_id}/regenerate`

```json
{ "extra_instructions": "..." }
```

Acció:

1. Valida `status: profiles_ready`
2. Llegeix `source_entity_uuid` de l'agent
3. Consulta Zep per obtenir el context de l'entitat original
4. Crida `OasisProfileGenerator.generate_profile_from_entity()` amb `extra_instructions`
5. Actualitza `reddit_profiles.json`
6. Retorna `task_id` per polling

**Frontend:** botó "Regenera" al modal (visible si `status: profiles_ready`),
camp opcional d'instruccions, spinner durant el task, refresc en completar.

### 2c. Creació d'un agent nou

Permet afegir un agent basat en una entitat existent al graf sense agent assignat.

**Backend:** `POST /api/simulation/{sim_id}/agent`

```json
{ "source_entity_uuid": "...", "extra_instructions": "..." }
```

Acció:

1. Valida `status IN ('profiles_ready', 'created')`
2. Valida que l'entitat no té ja un agent assignat
3. Assigna el proper `user_id` disponible (max existent + 1)
4. Consulta Zep per obtenir el context de l'entitat
5. Crida `OasisProfileGenerator.generate_profile_from_entity()` amb `extra_instructions`
6. Afegeix el nou agent a `reddit_profiles.json`
7. Retorna `task_id` per polling

**Frontend:** botó "Afegeix agent" al panell. Flux:

1. Desplegable de tipus d'entitat (basats en l'ontologia del projecte)
2. Llista d'entitats disponibles sense agent assignat
3. Camp d'instruccions opcional
4. Confirmar → spinner → nou agent apareix a les cards en completar

### 2d. Eliminació d'un agent

**Backend:** `DELETE /api/simulation/{sim_id}/agent/{user_id}`

Valida `status NOT IN ('running', 'completed')`. Elimina l'agent de
`reddit_profiles.json`. No reassigna `user_id` dels restants.

**Frontend:** botó "Elimina" al modal amb confirmació explícita.

### 2e. Confirmació de Fase A → Fase B

**Backend:** `POST /api/simulation/{sim_id}/generate-config`

Acció:

1. Valida `status: profiles_ready`
2. Canvia `status → configuring`
3. Llança async la generació de config de comportament i simulació
   (crida `SimulationConfigGenerator` amb els agents que han quedat)
4. En completar, canvia `status → prepared`
5. Retorna `task_id` per polling

**Frontend:** botó "Continuar →" (visible quan `status: profiles_ready`).
En clicar, inicia polling del `task_id`. En `completed`, passa a mostrar la Fase B.

---

## Subsistema 3: Fase B — Edició de paràmetres de comportament i simulació

### Comportament

Un cop la config de comportament és generada (`status: prepared`), el Step 2
mostra una nova secció editable amb:

- Paràmetres globals de simulació
- Paràmetres de comportament per a cada agent

L'usuari pot editar qualsevol valor. En clicar "Iniciar simulació" es passa al Step 3.

### 3a. Edició de paràmetres globals

**Backend:** `PATCH /api/simulation/{sim_id}/config`

```json
{
  "total_simulation_hours": 48,
  "minutes_per_round": 60,
  "agents_per_hour_min": 5,
  "agents_per_hour_max": 20,
  "following_probability": 0.05,
  "recsys_type": "random",
  "twitter_config": {
    "recency_weight": 0.4,
    "popularity_weight": 0.3,
    "relevance_weight": 0.3,
    "viral_threshold": 10,
    "echo_chamber_strength": 0.5
  }
}
```

Acció: valida `status: prepared`, actualitza `simulation_config.json` atòmicament,
retorna la config actualitzada.

**Frontend:** formulari de paràmetres globals amb inputs numèrics i selectors.
Valors actuals carregats de `GET /api/simulation/{sim_id}/config`.

### 3b. Edició de comportament per agent

**Backend:** `PATCH /api/simulation/{sim_id}/agent/{user_id}` (el mateix endpoint
de Subsistema 2a) — ara accepta també els camps de comportament:
`posts_per_hour`, `comments_per_hour`, `active_hours`, `response_delay_min`,
`response_delay_max`, `activity_level`, `influence_weight`.

**Frontend:** cada agent card a la Fase B mostra els seus paràmetres de comportament
editables inline (sense modal), amb inputs numèrics i selector d'hores actives.

---

## Subsistema 4: Clonació de simulació

### Comportament

Al desplegable de pre-generació (Subsistema 1):

- **"Nova simulació"** (default) → genera des de zero
- **"Des de [nom/data sim anterior]"** → clona agents de sim anterior

Simulacions clonables: qualsevol del mateix projecte amb
`status NOT IN ('created')`.

En triar una simulació font, el sistema:

1. Crida `POST /clone` → crea nova simulació amb `status: profiles_ready`
2. Carrega directament la Fase A amb els agents clonats (salta la generació)
3. L'usuari pot editar agents i continuar a Fase B

### Canvis al backend

`POST /api/simulation/{sim_id}/clone`

```json
{ "project_id": "proj_xxxx" }
```

Acció:

1. Valida `status != 'created'`
2. Crea nova simulació amb `status: profiles_ready`
3. Guarda `parent_simulation_id = sim_id`
4. Copia `reddit_profiles.json`, `twitter_profiles.csv`, `agent_profiles.json`
5. **No copia** `simulation_config.json` (es regenerarà a la Fase B)
6. Retorna `new_simulation_id`

---

## Subsistema 5: Aïllament de grafs per simulació

### Problema

Ara `enable_graph_memory_update` és `true` hardcodejat al frontend. Totes les
simulacions escriuen converses al mateix `graph_id` del projecte.
El report de sim2 inclou converses de sim1.

### Solució

Cada simulació té el seu propi `group_id` Neo4j (`graph_id_simulation`), creat
per clonatge APOC de `graph_id_document` just abans de llançar. `graph_id_simulation`
conté una còpia exacta del document original i és on els agents escriuen les
converses. `graph_id_document` queda immutable. El ReportAgent consulta
**únicament** `graph_id_simulation`.

### Flux

**Clonatge APOC** just abans de `POST /api/simulation/start`:

```python
# Clona nodes
await session.run("""
    MATCH (n) WHERE n.group_id = $src
    WITH n, properties(n) AS props
    CREATE (m) SET m = props SET m.group_id = $dst
""", src=graph_id_document, dst=graph_id_simulation)

# Clona relacions
await session.run("""
    MATCH (n)-[r]->(m)
    WHERE n.group_id = $src AND m.group_id = $src
    MATCH (n2 {uuid: n.uuid, group_id: $dst})
    MATCH (m2 {uuid: m.uuid, group_id: $dst})
    CALL apoc.create.relationship(n2, type(r), properties(r), m2) YIELD rel
    SET rel.group_id = $dst
    RETURN rel
""", src=graph_id_document, dst=graph_id_simulation)
```

Neo4j Aura Cloud inclou APOC de sèrie.

### Canvis al backend

**`graphiti_backend.py`** — nova funció `clone_graph(src_group_id, dst_group_id)`
via `execute_query()`.

**`POST /api/simulation/start`** — si `enable_graph_memory_update: true`:

1. Genera `graph_id_simulation = f"mirofish_{sim_id}_sim"`
2. Crida `clone_graph(graph_id_document, graph_id_simulation)`
3. Desa `graph_id_simulation` a la BD
4. Llança la simulació usant `graph_id_simulation`

**`POST /api/report/generate`** — passa `graph_id_simulation` al `ReportAgent`
si existeix; si no, passa `graph_id_document`.

**`DELETE /api/simulation/{sim_id}`** — si existeix `graph_id_simulation`,
esborrar el graf Neo4j associat:

```python
await session.run("""
    MATCH (n) WHERE n.group_id = $gid DETACH DELETE n
""", gid=graph_id_simulation)
```

### Canvis al frontend (Step 3)

Convertir `enable_graph_memory_update` de hardcodejat a checkbox configurable
a la UI del Step 3 (default `true`).

---

## Ordre d'implementació recomanat

1. Nou estat `profiles_ready` a la BD i backend
2. `PATCH /agent/{user_id}` (camps Fase A) + edició modal
3. Botó "Continuar →" + `POST /generate-config` + polling Fase B
4. Selector de N agents pre-generació
5. `DELETE /agent/{user_id}` + botó eliminar modal
6. `POST /agent` (creació) + UI selector d'entitat
7. `POST /agent/{user_id}/regenerate` + UI polling
8. `PATCH /simulation/{sim_id}/config` + formulari Fase B globals
9. `PATCH /agent/{user_id}` (camps comportament Fase B) + edició inline
10. `POST /clone` + desplegable pre-generació + `parent_simulation_id` a la BD
11. Subsistema 5: `clone_graph`, `graph_id_simulation`, `enable_graph_memory_update` configurable

---

## Verificació end-to-end

### Test 1: Flux complet Fase A → B → simulació

- Generar agents → editar bio d'un → clicar "Continuar →"
- Verificar que la config de comportament es genera amb els agents actuals
- Editar `total_simulation_hours` i `posts_per_hour` d'un agent
- Iniciar simulació → verificar que els valors editats s'apliquen

### Test 2: Edició protegida durant generació

- Editar un agent mentre altres es generen
- Verificar que l'agent editat NO es sobreescriu al finalitzar la generació

### Test 3: Regeneració individual

- `status: profiles_ready` → regenerar agent amb instrucció "Fes-lo més escèptic"
- Verificar spinner → perfil canviat coherentment

### Test 4: Creació i eliminació d'agents

- Afegir agent nou (entitat existent sense agent) → verificar a cards
- Eliminar un agent → verificar que desapareix i la config és consistent

### Test 5: Selector N agents

- 50 entitats disponibles → reduir a 30 → verificar 30 agents generats
- Verificar que corresponen a les entitats més connectades
- No tocar → verificar 50 agents (comportament actual)

### Test 6: Clonació

- Completar sim1 → Nova simulació "Des de sim1" al mateix projecte
- Verificar Fase A amb mateixos agents que sim1
- Editar un agent → Continuar → editar config → llançar
- Verificar que sim1 queda intacta

### Test 7: Aïllament de grafs

- Llançar sim1 i sim2 amb `enable_graph_memory_update: true`
- Verificar que el report de sim1 NO inclou converses de sim2 i viceversa
- Esborrar sim2 → verificar que el seu `graph_id_simulation` s'esborra de Neo4j

---

## Dependències i notes futures

- **F3** (UI de llistat de simulacions): `parent_simulation_id` prepara l'arbre de versions
- **Subsistema 5** depèn de Graphiti/Neo4j com a backend actiu (no Zep Cloud);
  verificar configuració de l'entorn abans d'implementar
