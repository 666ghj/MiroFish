#!/usr/bin/env python3
"""
Prepare article input for MiroFish pipeline.

Reads config_articles.env, loads and filters articles from articles.jsonl,
combines their text, and writes the result to a temp file.

Outputs a single JSON to stdout:
  {
    "combined_file":          "/home/anman/intern/MiroFish/test_code_backend/full_pipeline/data/articles_combined.md",
    "article_count":          42,
    "project_name":           "...",
    "simulation_requirement": "...",
    "start_time":             "2025-11-01",   # or null
    "end_time":               "2025-11-30"    # or null
  }

Usage:
  python prepare_input.py [config_articles.env]
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path


# ─── Config parser ────────────────────────────────────────────────────────────
path_output = "/home/anman/intern/MiroFish/test_code_backend/full_pipeline/data"

def parse_config(path: str) -> dict:
    """Parse 'key = value' config file (spaces around = allowed, # = comment).
    Values may optionally be wrapped in single or double quotes."""
    cfg = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if value:
                cfg[key] = value
    return cfg


# ─── Article loading ──────────────────────────────────────────────────────────

def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- … ---), return article body only."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].lstrip("\n")
    return content


def load_articles(article_path: str, full_content: bool,
                  start_time: str, end_time: str) -> list:
    jsonl_path = os.path.join(article_path, "articles.jsonl")
    if not os.path.exists(jsonl_path):
        raise FileNotFoundError(f"articles.jsonl not found: {jsonl_path}")

    start_dt = datetime.strptime(start_time, "%Y-%m-%d").date() if start_time else None
    end_dt   = datetime.strptime(end_time,   "%Y-%m-%d").date() if end_time   else None

    articles = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record   = json.loads(line)
            date_str = record.get("published_date", "")
            file_rel = record.get("file_path", "")
            if not date_str or not file_rel:
                continue

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if start_dt and date < start_dt:
                continue
            if end_dt   and date > end_dt:
                continue

            full_path = os.path.join(article_path, file_rel)
            if not os.path.exists(full_path):
                continue

            with open(full_path, encoding="utf-8") as mdf:
                raw = mdf.read()

            content = raw if full_content else strip_frontmatter(raw)
            articles.append({"date": date_str, "file_path": file_rel, "content": content})

    articles.sort(key=lambda a: a["date"])
    return articles


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    script_dir  = Path(__file__).parent
    config_path = sys.argv[1] if len(sys.argv) > 1 else str(script_dir / "config_articles.env")

    cfg = parse_config(config_path)

    article_path = cfg.get("article_path", "")
    full_content = cfg.get("full_content", "False").strip().lower() in ("true", "1", "yes")
    start_time   = cfg.get("start_time") or ""
    end_time     = cfg.get("end_time")   or ""
    sim_req      = cfg.get(
        "simulation_requirement",
        "Analyze how these news articles affect market sentiment and predict participant behavior.",
    )
    project_name = cfg.get("project_name", "MiroFish Pipeline")

    if not article_path:
        print(json.dumps({"error": "article_path is required"}))
        sys.exit(1)

    articles = load_articles(article_path, full_content, start_time, end_time)
    if not articles:
        print(json.dumps({"error": "No articles found for the given parameters"}))
        sys.exit(1)

    # Write combined text to path_output
    os.makedirs(path_output, exist_ok=True)
    out_path = os.path.join(path_output, "articles_combined.md")
    with open(out_path, "w", encoding="utf-8") as f:
        for art in articles:
            f.write(f"\n\n=== {art['file_path']} ({art['date']}) ===\n\n")
            f.write(art["content"])

    print(json.dumps({
        "combined_file":          out_path,
        "article_count":          len(articles),
        "project_name":           project_name,
        "simulation_requirement": sim_req,
        "start_time":             start_time or None,
        "end_time":               end_time   or None,
        "word_count":              sum(len(art["content"].split()) for art in articles)
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
