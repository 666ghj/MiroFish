"""
Script test ZepEntityReader — đọc graph đã build, xem logic chọn entity làm agent
Chạy từ thư mục backend/

Usage:
    python scripts/test_entity_reader.py <graph_id>
    python scripts/test_entity_reader.py <graph_id> --type Student
    python scripts/test_entity_reader.py <graph_id> --uuid <entity_uuid>
    python scripts/test_entity_reader.py --from-log case_01_academic_scandal
"""
import sys
import json
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.zep_entity_reader import ZepEntityReader

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def load_graph_id_from_log(case_id: str) -> str:
    log_path = os.path.join(OUTPUT_DIR, f"test_graph_output_{case_id}.json")
    if not os.path.exists(log_path):
        print(f"Không tìm thấy file log: {log_path}")
        sys.exit(1)
    with open(log_path, encoding="utf-8") as f:
        data = json.load(f)
    return data["graph_id"]


def print_entity(entity, show_edges: bool = True):
    entity_type = entity.get_entity_type() or "(unknown)"
    print(f"\n  ── [{entity_type}] {entity.name}")
    print(f"     uuid    : {entity.uuid}")
    if entity.summary:
        print(f"     summary : {entity.summary[:120]}")
    if entity.attributes:
        for k, v in entity.attributes.items():
            if k not in ("name",) and v and v != "null":
                print(f"     attr    : {k} = {v}")
    if show_edges and entity.related_edges:
        print(f"     edges ({len(entity.related_edges)}):")
        for e in entity.related_edges:
            arrow = "→" if e["direction"] == "outgoing" else "←"
            print(f"       {arrow} [{e['edge_name']}] {e.get('fact', '')[:80]}")
    if entity.related_nodes:
        names = [n["name"] for n in entity.related_nodes]
        print(f"     related : {', '.join(names)}")


def cmd_all(reader: ZepEntityReader, graph_id: str):
    """Lấy tất cả entity hợp lệ (có custom label) → danh sách agent tiềm năng"""
    print(f"\nGraph: {graph_id}")
    print("Đang lọc entity...")
    result = reader.filter_defined_entities(graph_id, enrich_with_edges=True)

    print(f"\n{'=' * 60}")
    print(f"Tổng nodes     : {result.total_count}")
    print(f"Entity hợp lệ  : {result.filtered_count}  ← đây là các agent tiềm năng")
    print(f"Entity types   : {sorted(result.entity_types)}")
    print(f"{'=' * 60}")

    # Nhóm theo type để dễ đọc
    by_type: dict = {}
    for e in result.entities:
        t = e.get_entity_type() or "unknown"
        by_type.setdefault(t, []).append(e)

    for entity_type, entities in sorted(by_type.items()):
        print(f"\n[{entity_type}] — {len(entities)} entity")
        for e in entities:
            print_entity(e)

    # Lưu output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"test_entity_reader_{graph_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"\nĐã lưu: {out_path}")


def cmd_by_type(reader: ZepEntityReader, graph_id: str, entity_type: str):
    print(f"\nLấy entity type [{entity_type}] từ graph {graph_id}...")
    entities = reader.get_entities_by_type(graph_id, entity_type, enrich_with_edges=True)
    print(f"Tìm thấy {len(entities)} entity loại [{entity_type}]:")
    for e in entities:
        print_entity(e)


def cmd_by_uuid(reader: ZepEntityReader, graph_id: str, uuid: str):
    print(f"\nLấy chi tiết entity {uuid}...")
    entity = reader.get_entity_with_context(graph_id, uuid)
    if not entity:
        print("Không tìm thấy entity.")
        return
    print_entity(entity, show_edges=True)


def main():
    args = sys.argv[1:]
    graph_id = None
    entity_type = None
    entity_uuid = None

    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--from-log":
        if len(args) < 2:
            print("Usage: --from-log <case_id>")
            sys.exit(1)
        graph_id = load_graph_id_from_log(args[1])
        print(f"Graph ID từ log [{args[1]}]: {graph_id}")
        args = args[2:]
    else:
        graph_id = args[0]
        args = args[1:]

    if "--type" in args:
        entity_type = args[args.index("--type") + 1]
    if "--uuid" in args:
        entity_uuid = args[args.index("--uuid") + 1]

    reader = ZepEntityReader()

    if entity_uuid:
        cmd_by_uuid(reader, graph_id, entity_uuid)
    elif entity_type:
        cmd_by_type(reader, graph_id, entity_type)
    else:
        cmd_all(reader, graph_id)


if __name__ == "__main__":
    main()
