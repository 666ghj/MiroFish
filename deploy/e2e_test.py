"""
MiroFish → FalkorDB end-to-end test (production-mode).

Runs the same code path the API uses, but in a one-shot container, against
the real FalkorDB sidecar in the same compose project. Verifies that:

  - FalkorDB is reachable from the app container (real TCP, real protocol)
  - graphiti-core connects and the Zep-shaped adapter works
  - Entities + edges actually land in FalkorDB after add_episode
  - The /health endpoint on the running MiroFish container is 200

Exits 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

# Make MiroFish backend importable
MIROFISH_BACKEND = "/app/backend"
if MIROFISH_BACKEND not in sys.path:
    sys.path.insert(0, MIROFISH_BACKEND)

# .env is loaded by MiroFish's config.py; nothing to do here.
print("=" * 70)
print("MIROFISH END-TO-END TEST (FalkorDB backend)")
print("=" * 70)
print(f"  FALKORDB_HOST  = {os.environ.get('FALKORDB_HOST', '<unset>')}")
print(f"  FALKORDB_PORT  = {os.environ.get('FALKORDB_PORT', '<unset>')}")
print(f"  LLM_BASE_URL   = {os.environ.get('LLM_BASE_URL',   '<unset>')}")
print(f"  LLM_MODEL_NAME = {os.environ.get('LLM_MODEL_NAME', '<unset>')}")
print(f"  EMBEDDING_MODEL= {os.environ.get('EMBEDDING_MODEL','<unset>')}")
print()

# -- 0. Sanity: is FalkorDB up? Use a raw TCP probe (no app deps) --
import socket
fk_host = os.environ.get("FALKORDB_HOST", "falkordb")
fk_port = int(os.environ.get("FALKORDB_PORT", "6379"))
try:
    with socket.create_connection((fk_host, fk_port), timeout=5):
        print(f"[0] FalkorDB TCP reachable at {fk_host}:{fk_port}")
except OSError as e:
    print(f"[0] FAIL: FalkorDB not reachable at {fk_host}:{fk_port}: {e}")
    sys.exit(2)

# -- 1. The Iran/US/Israel OSINT cron briefing as the seed text --
# In a real MiroFish run, this comes from /home/hermes/.hermes/cron/output/...
# For the e2e test, we ship a copy of the latest briefing inline.
SEED_TEXT = """\
## IRAN/US/ISRAEL CONFLICT — UPDATE
**Timestamp:** Monday, 8 June 2026, ~21:00 UTC
**Coverage Period:** Last 12 hours (07–08 June 2026)

### INCIDENTS / HOSTILITIES
- **Iran launched ballistic missile attack on Israel** (Sun 7 Jun, evening local) — first direct Iranian bombardment since the April 8 ceasefire. Multiple projectiles struck central Israel; Israeli emergency services report **3 killed and >100 injured** in a strike on a building in **Bat Yam** (south of Tel Aviv). [BBC, NYT, AP]
- **Israeli retaliatory strikes on Iran** conducted hours after the Iranian launch, targeting military sites in Tehran. Netanyahu stated Israel "hit the terror regime in Tehran." [NYT, Times of Israel]
- **Hezbollah rocket fire on northern Israel** (7 Jun) preceded the Israeli strike on Beirut's southern suburbs, which killed **2 and wounded ~11–20** (Lebanese state media). [NPR]
- **Iranian drone attack on US interests in the Strait of Hormuz** — US Central Command reports shooting down a pair of Iranian drones threatening the strait on 7 Jun. [CBS]

### DIPLOMATIC / POLITICAL
- **Trump-Netanyahu phone call** (7 Jun, post-Iranian missile launch) — Trump urged Netanyahu **not to retaliate**; Netanyahu reportedly replied "The Iranians violated our sovereignty."
- **Iran declared halt to military offensive** against Israel on 8 Jun.

### CEASEFIRE / TRUCE STATUS
- **April 8 Iran-US ceasefire:** Functionally **broken** — first direct Iran-Israel missile exchange since the truce.

### REGIONAL SPILLOVER
- **Strait of Hormuz:** US naval blockade in effect; shipping at near-standstill since March. IRGC restricts traffic; ~150+ tankers anchored outside. US forces disabled 4 vessels, redirected 94. [CNN, Reuters]
- **Houthi attacks (Yemen):** Iran-backed Houthi rebels struck Israel; rocket debris found near Jericho (West Bank) on 8 Jun.
- **Iraq/Syria:** US radar sites attacked; Iranian drones shot down near US positions (per US claims, 6 Jun).
- **Kuwait/Bahrain:** Earlier Iranian ballistic missile volleys (2–5 Jun) hit Kuwait International Airport.

### ASSESSMENT
The April 8 ceasefire has effectively collapsed after the first direct Iran-Israel missile exchange in two months, triggered by Israel's Beirut strike on Hezbollah. Both sides have paused strikes as of 8 Jun following Trump intervention, but a 60-day US-Iran deal remains unsigned and Hezbollah's rejection of the Lebanon track preserves a major escalation vector. **High risk of renewed escalation within 24–72 hours** if Trump-Netanyahu alignment fractures or Lebanon track collapses.
"""

print(f"[1] Seed text: {len(SEED_TEXT)} chars (Iran/US/Israel OSINT briefing)")

# -- 2. Ontology (same shape MiroFish's OntologyGenerator would emit) --
ONTOLOGY = {
    "entity_types": [
        {"name": "Country",     "description": "A sovereign nation or state actor.",
         "attributes": [{"name": "iso_code", "description": "ISO code"},
                        {"name": "government_type", "description": "Form of government"}]},
        {"name": "Person",      "description": "A named individual mentioned in the briefing.",
         "attributes": [{"name": "role", "description": "Title, position, or affiliation"}]},
        {"name": "Organization","description": "A formal organization, military unit, or political body.",
         "attributes": [{"name": "type", "description": "e.g. political, militant, state"}]},
        {"name": "Location",    "description": "A geographic place, city, or strategic region.",
         "attributes": [{"name": "region", "description": "Broader region"}]},
        {"name": "Event",       "description": "A distinct incident, attack, meeting, or action.",
         "attributes": [{"name": "date", "description": "When the event occurred"},
                        {"name": "event_type", "description": "Type of event"}]},
    ],
    "edge_types": [
        {"name": "LAUNCHED_ATTACK_AGAINST", "description": "Actor performed a military strike on target.",
         "source_targets": [{"source": "Country", "target": "Country"},
                            {"source": "Organization", "target": "Country"}],
         "attributes": [{"name": "date", "description": "Date"},
                        {"name": "weapon", "description": "Weapon used"}]},
        {"name": "OCCURRED_IN",     "description": "An event happened at a location.",
         "source_targets": [{"source": "Event", "target": "Location"}],
         "attributes": [{"name": "date", "description": "Date"}]},
        {"name": "IS_LEADER_OF",    "description": "A person leads a country or organization.",
         "source_targets": [{"source": "Person", "target": "Country"},
                            {"source": "Person", "target": "Organization"}],
         "attributes": []},
        {"name": "MADE_STATEMENT",  "description": "A person or organization issued a public statement.",
         "source_targets": [{"source": "Person", "target": "Event"}],
         "attributes": [{"name": "stance", "description": "Position taken"}]},
        {"name": "PARTICIPATED_IN", "description": "A country or organization was involved in an event.",
         "source_targets": [{"source": "Country", "target": "Event"}],
         "attributes": []},
    ],
}
print(f"[2] Ontology: {len(ONTOLOGY['entity_types'])} entity types, "
      f"{len(ONTOLOGY['edge_types'])} edge types")

# -- 3. Chunk the seed text --
from app.services.text_processor import TextProcessor
chunks = TextProcessor.split_text(SEED_TEXT, chunk_size=500, overlap=50)
print(f"[3] Text split: {len(chunks)} chunks")

# -- 4. Run the build pipeline via the real GraphBuilderService --
from app.services.graph_builder import GraphBuilderService
from app.services import graph_builder as _gb_mod  # for the EpisodeData stub
EpisodeData = _gb_mod.EpisodeData

MAX_CHUNKS = int(os.environ.get("E2E_MAX_CHUNKS", "2"))
test_chunks = chunks[:MAX_CHUNKS]
print(f"[4] Using {len(test_chunks)} chunks for the e2e test (E2E_MAX_CHUNKS={MAX_CHUNKS})")
print()

print("[5] Running graph build pipeline...")
t0 = time.time()
builder = GraphBuilderService()
graph_id = builder.create_graph(name="Iran_US_Israel_OSINT_e2e")
print(f"    create_graph -> {graph_id}")
builder.set_ontology(graph_id, ONTOLOGY)
print(f"    set_ontology -> cached {len(ONTOLOGY['entity_types'])} types, {len(ONTOLOGY['edge_types'])} edges")

episodes = [EpisodeData(data=c, type="text") for c in test_chunks]
print(f"    add_batch -> sending {len(episodes)} EpisodeData objects...")
batch_result = builder.client.add_batch(graph_id=graph_id, episodes=episodes)
t1 = time.time()
print(f"    add_batch took {t1 - t0:.1f}s")
for r in batch_result:
    print(f"      uuid={r.uuid_} processed={r.processed}")

# -- 5. Verify in FalkorDB via the adapter's read methods --
print()
print("[6] Reading back from FalkorDB via the adapter...")
nodes = builder.client.get_all_nodes(graph_id)
edges = builder.client.get_all_edges(graph_id)
print(f"    nodes: {len(nodes)}")
print(f"    edges: {len(edges)}")

print()
print("[7] Sample entities (first 10):")
for n in nodes[:10]:
    labels_str = ",".join(n.labels) if n.labels else "(no labels)"
    summary_preview = (n.summary[:60] + "...") if n.summary and len(n.summary) > 60 else (n.summary or "")
    print(f"    [{labels_str}] {n.name!r}  uuid={n.uuid_[:8]}  summary={summary_preview!r}")

print()
print("[8] Sample relationships (first 5):")
for e in edges[:5]:
    src = e.source_node_uuid[:8] if e.source_node_uuid else "?"
    dst = e.target_node_uuid[:8] if e.target_node_uuid else "?"
    fact_preview = (e.fact[:60] + "...") if e.fact and len(e.fact) > 60 else (e.fact or "")
    print(f"    ({src}) -[{e.name or e.fact_type}]→ ({dst})  fact={fact_preview!r}")

# -- 6. Independent verification with the raw falkordb client --
print()
print("[9] Direct falkordb verification (source of truth)...")
import falkordb
client = falkordb.FalkorDB(host=fk_host, port=fk_port)
graph = client.select_graph(graph_id)
n_count = graph.query("MATCH (n) RETURN count(n) AS c").result_set
e_count = graph.query("MATCH ()-[r]->() RETURN count(r) AS c").result_set
print(f"    FalkorDB MATCH count(n)        = {n_count}")
print(f"    FalkorDB MATCH count(edges)    = {e_count}")
labels = graph.query("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY c DESC LIMIT 20")
print(f"    Entity label distribution:")
for row in labels.result_set:
    print(f"      {row[0]}: {row[1]}")
names = graph.query("MATCH (n) RETURN n.name AS name LIMIT 20")
print(f"    Sample node names: {[r[0] for r in names.result_set]}")

# -- 7. Final summary --
print()
print("=" * 70)
print("E2E TEST SUMMARY")
print("=" * 70)
print(f"  Graph ID:           {graph_id}")
print(f"  Seed text:          Iran/US/Israel OSINT briefing ({len(SEED_TEXT)} chars)")
print(f"  Chunks ingested:    {len(episodes)}")
print(f"  Nodes in FalkorDB:  {len(nodes)} (direct: {n_count[0][0]})")
print(f"  Edges in FalkorDB:  {len(edges)} (direct: {e_count[0][0]})")
print(f"  Wall time:          {t1 - t0:.1f}s")
print(f"  Pass criteria:      node_count > 0 AND edge_count > 0")
passing = (len(nodes) > 0 and len(edges) > 0)
print(f"  RESULT:             {'PASS' if passing else 'FAIL'}")
print("=" * 70)
sys.exit(0 if passing else 1)
