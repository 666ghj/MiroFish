"""
Test: Knowledge Graph build on Zep Cloud
Input : - output/ontology/ontology_*.json  (latest, or pass path as arg)
        - news articles (same date range as ontology)
Output: output/graph/
  graph_<graph_id>.json    — build summary (node/edge count, timing)
  entities_<graph_id>.json — entity detail: raw nodes + filtered result

Run:
    python build_graph.py                                    # auto-picks latest ontology
    python build_graph.py output/ontology/ontology_xyz.json  # specific ontology file
"""

import sys
import json
import time
import argparse
from datetime import datetime, date
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent
PROJECT_ROOT  = SCRIPT_DIR.parent.parent
BACKEND_DIR   = PROJECT_ROOT / "backend"
ONTOLOGY_DIR  = SCRIPT_DIR.parent / "output" / "ontology"
GRAPH_DIR     = SCRIPT_DIR.parent / "output" / "graph"
NEWS_DIR      = PROJECT_ROOT / "data" / "news" / "2026-04"

sys.path.insert(0, str(BACKEND_DIR))
GRAPH_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────
START_DATE    = date(2026, 4, 20)
END_DATE      = date(2026, 4, 22)
GRAPH_NAME    = "MiroFish_Test_Apr2026"
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50
BATCH_SIZE    = 3
POLL_TIMEOUT  = 600


# ── Helpers ──────────────────────────────────────────────────────────────────
def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def extract_body(md_text: str) -> str:
    s = md_text.strip()
    if s.startswith("---"):
        end = s.find("---", 3)
        if end != -1:
            return s[end + 3:].strip()
    return s


def load_combined_text(news_dir: Path, start: date, end: date) -> str:
    parts = []
    for md_file in sorted(news_dir.glob("*.md")):
        try:
            file_date = date.fromisoformat(md_file.stem.split("_")[0])
        except ValueError:
            continue
        if not (start <= file_date <= end):
            continue
        body = extract_body(md_file.read_text(encoding="utf-8"))
        if body:
            parts.append(body)
    return "\n\n---\n\n".join(parts)


def pick_ontology_file(arg_path: str | None) -> Path:
    if arg_path:
        p = Path(arg_path)
        if not p.is_absolute():
            p = ONTOLOGY_DIR / p
        if not p.exists():
            raise FileNotFoundError(f"Ontology file not found: {p}")
        return p

    candidates = sorted(ONTOLOGY_DIR.glob("ontology_*.json"), key=lambda f: f.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(
            f"No ontology_*.json found in {ONTOLOGY_DIR}. Run gen_ontology.py first."
        )
    return candidates[-1]  # latest


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Build Zep Knowledge Graph from ontology")
    parser.add_argument("ontology_file", nargs="?", help="Path to ontology JSON (default: latest in output/)")
    args = parser.parse_args()

    from app.services.graph_builder import GraphBuilderService
    from app.services.text_processor import TextProcessor
    from app.services.zep_entity_reader import ZepEntityReader

    # Load ontology
    ontology_path = pick_ontology_file(args.ontology_file)
    log(f"Using ontology: {ontology_path.name}")
    with open(ontology_path, encoding="utf-8") as f:
        payload = json.load(f)
    ontology = payload["ontology"]

    # Load news text
    log(f"Loading news text: {START_DATE} → {END_DATE}")
    combined_text = load_combined_text(NEWS_DIR, START_DATE, END_DATE)
    log(f"  Text length: {len(combined_text):,} chars")

    svc = GraphBuilderService()
    t_total = time.time()

    # Create graph
    log("Creating Zep graph...")
    graph_id = svc.create_graph(GRAPH_NAME)
    log(f"  graph_id = {graph_id}")

    # Apply ontology
    log("Applying ontology schema...")
    svc.set_ontology(graph_id, ontology)

    # Chunk & upload
    chunks = TextProcessor.split_text(combined_text, CHUNK_SIZE, CHUNK_OVERLAP)
    log(f"Uploading {len(chunks)} chunks (batch_size={BATCH_SIZE})...")

    episode_uuids = svc.add_text_batches(
        graph_id, chunks, BATCH_SIZE,
        progress_callback=lambda msg, _: log(f"  {msg}"),
    )
    log(f"  {len(episode_uuids)} episodes uploaded")

    # Wait for processing
    log("Waiting for Zep to process episodes...")
    svc._wait_for_episodes(
        episode_uuids,
        progress_callback=lambda msg, _: log(f"  {msg}"),
        timeout=POLL_TIMEOUT,
    )

    # Fetch result
    log("Fetching graph stats...")
    graph_info = svc._get_graph_info(graph_id)
    elapsed = round(time.time() - t_total, 2)

    log(f"Done in {elapsed}s — nodes={graph_info.node_count}, edges={graph_info.edge_count}")
    log(f"  Entity types: {graph_info.entity_types}")

    out_path = GRAPH_DIR / f"graph_{graph_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "graph_id": graph_id,
            "graph_name": GRAPH_NAME,
            "built_at": datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
            "ontology_source": ontology_path.name,
            "date_range": {"start": str(START_DATE), "end": str(END_DATE)},
            "chunks_uploaded": len(chunks),
            "node_count": graph_info.node_count,
            "edge_count": graph_info.edge_count,
            "entity_types": graph_info.entity_types,
        }, f, ensure_ascii=False, indent=2)

    log(f"Saved → {out_path.name}")

    # ── Entity detail ─────────────────────────────────────────────────────────
    # Raw graph data — lưu nguyên output của get_graph_data()
    log("Fetching raw graph data...")
    graph_data = svc.get_graph_data(graph_id)
    log(f"  nodes={graph_data['node_count']}, edges={graph_data['edge_count']}")

    # Filtered entities — lưu nguyên output của filter_defined_entities().to_dict()
    log("Running entity filter...")
    defined_types = [e["name"] for e in ontology.get("entity_types", [])]
    reader = ZepEntityReader()
    filtered = reader.filter_defined_entities(
        graph_id=graph_id,
        defined_entity_types=defined_types,
        enrich_with_edges=True,
    )
    log(f"  total={filtered.total_count}, matched={filtered.filtered_count}")
    log(f"  types found: {sorted(filtered.entity_types)}")

    entities_path = GRAPH_DIR / f"entities_{graph_id}.json"
    with open(entities_path, "w", encoding="utf-8") as f:
        json.dump({
            "graph_id": graph_id,
            "fetched_at": datetime.now().isoformat(),
            "ontology_entity_types": defined_types,
            "raw_graph_data": graph_data,
            "filtered_entities": filtered.to_dict(),
        }, f, ensure_ascii=False, indent=2)

    log(f"Saved → {entities_path.name}")


if __name__ == "__main__":
    main()
