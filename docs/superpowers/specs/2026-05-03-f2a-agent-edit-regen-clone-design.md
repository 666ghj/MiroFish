# Spec F2-A: Edició, Regeneració, Creació i Clonació d'Agents

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
3. **Regeneració, creació i eliminació d'agents individuals** — regenerar un agent, crear-ne un de nou basat en una entitat del graf, o eliminar-ne un
4. **Clonació de simulació** — crear una nova simulació dins el mateix projecte partint dels agents i config d'una simulació anterior
5. **Aïllament de grafs per simulació** (ex F2-D) — cada simulació escriu les converses al seu propi `group_id` Neo4j via clonatge APOC

---

## Model de dades

### Canvi a la BD: `parent_simulation_id`

Afegir una columna nullable a la taula `simulations`:

```sql
ALTER TABLE simulations
  ADD COLUMN parent_simulation_id VARCHAR(64) REFERENCES simulations(simulation_id);
```

- `NULL` → simulació nova (comportament actual)
- Valor → simulació clonada d'una existent

No hi ha canvis a cap altra taula ni model existent.

### Canvi a la BD: `graph_id_simulation`

Afegir una columna nullable a la taula `simulations`:

```sql
ALTER TABLE simulations
  ADD COLUMN graph_id_simulation VARCHAR(128);
```

Conté el `group_id` Neo4j exclusiu d'aquesta simulació (creat per clonatge APOC
just abans de llançar). `NULL` fins que la simulació s'inicia.

### Immutabilitat de simulacions completades

- `status IN ('completed', 'running')` → no es pot editar
- `status IN ('created', 'prepared', 'stopped', 'failed')` → editable

### Camps editables d'un perfil d'agent

Editables (LLM-generats): `name`, `bio`, `persona`, `age`, `gender`, `mbti`,
`country`, `profession`, `interested_topics`, `stance`, `sentiment_bias`,
`activity_level`.

Immutables (OASIS els necessita intactes): `user_id`, `source_entity_uuid`,
`source_entity_type`.

### Flag de protecció contra sobreescriptura

Cada agent porta un flag `manually_edited: bool` (default `False`) a
`reddit_profiles.json` i `simulation_config.json`. El generador en batch salta
els agents amb `manually_edited: True`.

---

## Subsistema 1: Selector de nombre d'agents (pre-generació)

### Comportament

Abans del botó "Generar agents" al Step 2, el sistema consulta quantes entitats
hi ha disponibles al graf i mostra el total com a suggeriment (ex: "66 agents
disponibles"). L'usuari pot reduir el número. Si no toca res, el comportament
és idèntic a l'actual.

Si l'usuari redueix a N, el backend selecciona les **top-N entitats per grau de
connectivitat** (edges entrants + sortints al graf Zep). Les entitats més
connectades representen els actors amb més relacions al document i generen
simulacions socialment més riques.

**Mínim recomanat:** 15 agents. El frontend mostra un avís si el valor és inferior.

### Canvis al backend

`POST /api/simulation/prepare` — nou paràmetre opcional:

```json
{ "max_agents": 40 }
```

Si `max_agents` és present, `ZepEntityReader` ordena les entitats filtrades per
grau de connectivitat descendent i agafa les primeres N.

Nova funció: `ZepEntityReader.get_entities_by_connectivity(graph_id, max_n)` —
obté totes les entitats, les ordena per `len(edges)` i retorna les top-N.

### Canvis al frontend (Step 2)

Just abans del botó "Generar agents":

- Crida a `GET /api/simulation/entities/{graph_id}` (ja existent) per obtenir el total
- Camp numèric amb valor default = total disponible
- Avís visual si valor < 15
- El valor es passa a `POST /api/simulation/prepare` com a `max_agents`

---

## Subsistema 2: Edició d'agents individuals

### Comportament

El modal de visualització d'agents (ja existent a `Step2EnvSetup.vue`) afegeix
un botó "Editar" que converteix els camps en inputs editables. En desar, el
backend actualitza el perfil i marca `manually_edited: True`.

L'edició és possible durant la generació (l'agent editat queda protegit) i
després de la generació completa. No és possible si `status: running` o `completed`.

### Canvis al backend

`PATCH /api/simulation/{sim_id}/agent/{user_id}`

```json
{ "bio": "...", "stance": "opposing" }
```

Acció:

1. Valida que la simulació no és `running` ni `completed`
2. Carrega `reddit_profiles.json` i `simulation_config.json`
3. Localitza l'agent per `user_id`
4. Aplica els canvis + `manually_edited: True`
5. Desa atòmicament (backup → escriptura → elimina backup si OK, restaura si falla)
6. Retorna el perfil actualitzat

### Canvis al frontend (Step 2)

Al modal d'agent (`Step2EnvSetup.vue`):

- Botó "Editar" → converteix camps en `<input>` / `<textarea>` / `<select>`
- Botó "Desa" → `PATCH` → refrescar el modal
- Botó "Cancel·la" → descarta canvis locals
- Indicador visual "Editat manualment" a la card si `manually_edited: True`

---

## Subsistema 3: Regeneració, creació i eliminació d'agents individuals

### 3a. Regeneració d'un agent existent

Disponible **només** quan `status: prepared`. No disponible si `running` o `completed`.

L'usuari pot afegir instruccions opcionals per al LLM (ex: "Fes-lo més escèptic").
La regeneració és asíncrona (5-15 s). El modal mostra un spinner mentre el
`task_id` és en curs i es refrescar en completar.

**Backend:** `POST /api/simulation/{sim_id}/agent/{user_id}/regenerate`

```json
{ "extra_instructions": "..." }
```

Acció:

1. Valida `status: prepared`
2. Llegeix `source_entity_uuid` de l'agent actual
3. Consulta Zep per obtenir el context de l'entitat original
4. Crida `OasisProfileGenerator.generate_profile_from_entity()` amb `extra_instructions`
5. Actualitza `reddit_profiles.json`, `twitter_profiles.csv` i `simulation_config.json`
6. Retorna `task_id` per polling (reutilitza `GET /api/.../task/{task_id}`)

**Frontend:** botó "Regenera" al modal (visible si `is_preparing === False`),
camp de text opcional per a instruccions, spinner durant el task, refresc en completar.

### 3b. Creació d'un agent nou

Permet afegir un agent basat en una **entitat existent al graf** que no té agent
assignat (entitat sense `user_id` a `agent_profiles.json`). L'usuari tria el tipus
d'entitat (en base a l'ontologia del projecte), selecciona una entitat concreta, i
opcionalment afegeix un prompt que guia la generació del perfil.

**Backend:** `POST /api/simulation/{sim_id}/agent`

```json
{
  "source_entity_uuid": "uuid-de-lentitat",
  "extra_instructions": "..."
}
```

Acció:

1. Valida que `status IN ('prepared', 'created')` i que l'entitat no té ja un agent
2. Assigna el proper `user_id` disponible (max existent + 1)
3. Consulta Zep per obtenir el context de l'entitat
4. Crida `OasisProfileGenerator.generate_profile_from_entity()` amb `extra_instructions`
5. Afegeix el nou agent a `reddit_profiles.json`, `twitter_profiles.csv` i `simulation_config.json`
6. Retorna `task_id` per polling

**Frontend:** botó "Afegeix agent" al panell d'agents (visible si `status: prepared`).
Flux:

1. Desplegable de tipus d'entitat (basats en l'ontologia del projecte)
2. Llista d'entitats disponibles d'aquell tipus sense agent assignat
3. Camp de text opcional per a instruccions addicionals
4. Confirmar → spinner → nou agent apareix a les cards en completar

### 3c. Eliminació d'un agent

Permet eliminar un agent si la simulació és `prepared`. No és possible si
`running` o `completed`.

**Backend:** `DELETE /api/simulation/{sim_id}/agent/{user_id}`

Acció: elimina l'agent de `reddit_profiles.json`, `twitter_profiles.csv` i
`simulation_config.json`. No reassigna `user_id` dels agents restants
(OASIS treballa amb IDs fixos).

**Frontend:** botó "Elimina" al modal d'agent, amb confirmació explícita.

---

## Subsistema 4: Clonació de simulació

### Comportament

Al Step 2, just sobre el botó "Generar agents", un desplegable:

- **"Nova simulació"** (default) → comportament actual, genera des de zero
- **"Des de [nom/data sim anterior]"** → clona agents i config d'una simulació existent

Simulacions clonables: qualsevol del mateix projecte amb `status != 'created'`
(inclou `prepared`, `running`, `stopped`, `failed`, `completed`).

En triar una simulació font, el Step 2 crida `POST /clone` i carrega
directament amb els agents clonats (salta la generació, `status: prepared`).

### Canvis al backend

`GET /api/simulation/list?project_id={id}` — ja existent; el frontend filtra les clonables.

`POST /api/simulation/{sim_id}/clone`

```json
{ "project_id": "proj_xxxx" }
```

Acció:

1. Valida que `sim_id` té agents (`status != 'created'`)
2. Crea nova simulació al projecte amb `status: prepared`
3. Guarda `parent_simulation_id = sim_id`
4. Copia fitxers: `reddit_profiles.json`, `twitter_profiles.csv`, `simulation_config.json`, `agent_profiles.json`
5. Retorna `new_simulation_id`

### Canvis al frontend (Step 2)

- Desplegable que carrega les simulacions clonables del projecte
- En seleccionar → `POST /clone` → redirigir al Step 2 amb el nou `simulation_id`
- Step 2 detecta `status: prepared` i mostra els agents directament

---

## Subsistema 5: Aïllament de grafs per simulació (ex F2-D)

### Problema

Actualment `enable_graph_memory_update` és `true` al frontend (hardcodejat a
`Step3Simulation.vue:402`), cosa que fa que totes les simulacions escriguin les
seves converses al mateix `graph_id` del projecte. El resultat del report de
sim2 inclou converses de sim1.

### Solució

Cada simulació té el seu propi `group_id` Neo4j (`graph_id_simulation`), creat
per clonatge APOC de `graph_id_document` just abans de llançar la simulació.
`graph_id_simulation` conté una còpia exacta del document original, i és on els
agents escriuen les seves converses. `graph_id_document` queda immutable i serveix
de font per a futurs clonatges.

El ReportAgent consulta **únicament** `graph_id_simulation`.

### Flux

1. **Clonatge APOC** (just abans de `POST /api/simulation/start`):

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

Neo4j Aura Cloud inclou APOC de sèrie, per tant no cal cap dependència addicional.

2. **Llançament de simulació**: `enable_graph_memory_update: true` usant `graph_id_simulation`.
   Els agents escriuen converses a `graph_id_simulation`, que ja conté el contingut del document.

3. **Report**: `ReportAgent` rep i consulta únicament `graph_id_simulation`.
   No cal fusionar grafs ni canviar `ZepToolsService`.

### Canvis al backend

**`graphiti_backend.py`** — nova funció `clone_graph(src_group_id, dst_group_id)` que
executa les dues queries APOC via `execute_query()`.

**`POST /api/simulation/start`** — si `enable_graph_memory_update: true`:

1. Genera `graph_id_simulation = f"mirofish_{sim_id}_sim"`
2. Crida `clone_graph(graph_id_document, graph_id_simulation)`
3. Desa `graph_id_simulation` a la BD
4. Llança la simulació usant `graph_id_simulation`

**`POST /api/report/generate`** — passa `graph_id_simulation` al `ReportAgent`
si existeix; si no (simulació sense graph update), passa `graph_id_document` com ara.

### Canvis al frontend (Step 3)

Eliminar el hardcodejat `enable_graph_memory_update: true` i convertir-ho en
una opció configurable a la UI de Step 3 (checkbox "Actualitza el graf amb les
converses de la simulació", default `true`).

---

## Ordre d'implementació recomanat

1. `PATCH /agent/{user_id}` + edició modal
2. Selector de N agents pre-generació
3. `DELETE /agent/{user_id}` + botó eliminar modal
4. `POST /agent` (creació) + UI selector d'entitat
5. `POST /agent/{user_id}/regenerate` + UI polling
6. `POST /clone` + desplegable Step 2 + `parent_simulation_id` a la BD
7. Subsistema 5 (aïllament de grafs): `clone_graph`, `search_graph_multi`, `graph_id_simulation` a BD

---

## Verificació end-to-end

### Test 1: Edició d'agent

- Generar agents → obrir modal → modificar `bio` i `stance` → desar
- Verificar modal actualitzat i card amb indicador "Editat manualment"
- Iniciar generació d'un altre agent → verificar que l'agent editat no es sobreescriu

### Test 2: Regeneració individual

- Completar generació → obrir modal → "Regenera" amb instrucció "Fes-lo més escèptic"
- Verificar spinner → perfil canviat coherentment amb la instrucció

### Test 3: Creació d'agent nou

- Projecte amb entitats sense agent → clicar "Afegeix agent"
- Triar tipus d'entitat → seleccionar entitat → afegir instruccions → confirmar
- Verificar que el nou agent apareix a les cards i és coherent amb l'entitat

### Test 4: Eliminació d'agent

- Modal d'un agent → "Elimina" → confirmació → agent desapareix de les cards
- Verificar que la simulació segueix consistent

### Test 5: Selector N agents

- 50 entitats disponibles → reduir a 30 → verificar exactament 30 agents generats
- Verificar que corresponen a les entitats més connectades
- No tocar → verificar 50 agents (comportament actual)

### Test 6: Clonació

- Completar sim1 → Step 2 del mateix projecte → "Des de sim1"
- Verificar que Step 2 carrega amb els mateixos agents que sim1
- Editar un agent → llançar simulació → verificar que sim1 queda intacta

### Test 7: Aïllament de grafs

- Llançar sim1 amb `enable_graph_memory_update: true` → completar
- Llançar sim2 amb `enable_graph_memory_update: true` → completar
- Verificar que el report de sim1 NO inclou converses de sim2 i viceversa
- Verificar que ambdós reports inclouen les entitats del `graph_document`

---

## Dependències i notes futures

- **F2-B** (paràmetres simulació): independent, es pot fer en paral·lel
- **F3** (UI de llistat de simulacions): `parent_simulation_id` prepara l'arbre de versions
- **Subsistema 5** depèn de Graphiti/Neo4j com a backend actiu (no Zep Cloud);
  verificar configuració de l'entorn abans d'implementar
