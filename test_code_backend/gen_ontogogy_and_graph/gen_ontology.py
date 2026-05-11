"""
Test: Ontology generation from news articles
Input : data/news/2026-04/  (date range configured below)
Output: test_code_backend/output/ontology/ontology_<daterange>_<timestamp>.json

Run:
    python gen_ontology.py
"""

import sys
import json
import time
from datetime import datetime, date
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).parent
PROJECT_ROOT  = SCRIPT_DIR.parent.parent
BACKEND_DIR   = PROJECT_ROOT / "backend"
ONTOLOGY_DIR  = SCRIPT_DIR.parent / "output" / "ontology"
NEWS_DIR      = PROJECT_ROOT / "data" / "news" / "2026-04"

sys.path.insert(0, str(BACKEND_DIR))
ONTOLOGY_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────
START_DATE = date(2026, 4, 20)
END_DATE   = date(2026, 4, 22)

SIMULATION_REQUIREMENT = (
    "Simulate social media public opinion dynamics around global oil/energy markets "
    "and US-Iran geopolitical tensions during April 2026. "
    "Focus on how governments, corporations, media outlets, financial analysts, and "
    "ordinary citizens react and interact on platforms like Twitter and Reddit."
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def extract_body(md_text: str) -> str:
    """Strip YAML frontmatter (---...---), return only article body."""
    s = md_text.strip()
    if s.startswith("---"):
        end = s.find("---", 3)
        if end != -1:
            return s[end + 3:].strip()
    return s


def load_articles(news_dir: Path, start: date, end: date) -> list[dict]:
    articles = []
    for md_file in sorted(news_dir.glob("*.md")):
        try:
            file_date = date.fromisoformat(md_file.stem.split("_")[0])
        except ValueError:
            continue
        if not (start <= file_date <= end):
            continue
        body = extract_body(md_file.read_text(encoding="utf-8"))
        if body:
            articles.append({"filename": md_file.name, "date": str(file_date), "body": body})
    return articles


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    from app.services.ontology_generator import OntologyGenerator

    log(f"Loading news: {START_DATE} → {END_DATE}")
    articles = load_articles(NEWS_DIR, START_DATE, END_DATE)
    log(f"  {len(articles)} articles loaded")

    log("Calling LLM to generate ontology...")
    t0 = time.time()
    ontology = OntologyGenerator().generate(
        document_texts=[a["body"] for a in articles],
        simulation_requirement=SIMULATION_REQUIREMENT,
    )
    elapsed = round(time.time() - t0, 2)

    entity_names = [e["name"] for e in ontology.get("entity_types", [])]
    edge_names   = [e["name"] for e in ontology.get("edge_types", [])]
    log(f"Done in {elapsed}s")
    log(f"  Entities ({len(entity_names)}): {entity_names}")
    log(f"  Edges    ({len(edge_names)}): {edge_names}")

    date_range = f"{START_DATE.strftime('%Y%m%d')}-{END_DATE.strftime('%Y%m%d')}"
    ts = datetime.now().strftime("%H%M%S")
    out_path = ONTOLOGY_DIR / f"ontology_{date_range}_{ts}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "elapsed_seconds": elapsed,
                "date_range": {"start": str(START_DATE), "end": str(END_DATE)},
                "article_count": len(articles),
            },
            "ontology": ontology,
        }, f, ensure_ascii=False, indent=2)

    log(f"Saved → {out_path.name}")


if __name__ == "__main__":
    main()
