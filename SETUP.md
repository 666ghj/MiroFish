# Hướng dẫn chạy MiroFish với Graphiti + Neo4j

Bản fork này đã chuyển từ **Zep Cloud** sang **Graphiti + Neo4j (self-hosted)**.

---

## Yêu cầu

| Tool | Version | Check |
|---|---|---|
| Docker + Docker Compose | 20.10+ | `docker --version` |
| Python | 3.11 hoặc 3.12 | `python --version` |
| uv (hoặc pip) | latest | `uv --version` |
| Node.js (nếu chạy frontend) | 18+ | `node -v` |

RAM khuyến nghị: **≥ 8 GB** (Neo4j ăn ~2GB heap + ~1GB pagecache).

---

## Bước 1 — Cấu hình `.env`

```bash
cp .env.example .env
```

Mở `.env` và set tối thiểu:

```env
# LLM cho extraction (bắt buộc)
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Neo4j (bolt://localhost khi chạy backend trên máy host)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=123

# Embedding cho Graphiti vector search
# Để trống EMBEDDING_API_KEY thì sẽ fallback về LLM_API_KEY
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

**Lưu ý NEO4J_URI:**
- Chạy backend trên máy host → `bolt://localhost:7687`
- Chạy backend trong docker compose → `bolt://neo4j:7687`

---

## Bước 2 — Khởi động Neo4j

```bash
# Chỉ chạy Neo4j (không pull image mirofish 4.7GB)
docker compose up -d neo4j

# Đợi ~30s, theo dõi log
docker compose logs -f neo4j
# Khi thấy "Started." là OK, Ctrl+C thoát log
```

Kiểm tra:

```bash
docker compose ps                    # neo4j phải (healthy)
curl http://localhost:7474           # trả về HTML
```

Mở trình duyệt: <http://localhost:7474>
Login: `neo4j` / `123` (theo `.env`)

---

## Bước 3 — Cài Python deps

```bash
cd backend

# Cách A: dùng uv (khuyến nghị)
uv sync

# Cách B: dùng pip
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Bước 4 — Chạy backend

```bash
# Từ project root
npm run backend

# Hoặc trực tiếp
cd backend && uv run python run.py
```

Backend chạy tại <http://localhost:5001>

Chạy kèm frontend:

```bash
npm run setup:all     # cài deps lần đầu
npm run dev           # chạy backend + frontend song song
```

- Frontend: <http://localhost:3000>
- Backend: <http://localhost:5001>

---

## Lệnh quản lý Neo4j

```bash
# Tắt nhưng GIỮ DATA
docker compose stop neo4j

# Start lại
docker compose start neo4j

# Tắt + xóa container (vẫn giữ data trong volume)
docker compose down

# XÓA SẠCH (kể cả graph data) — chỉ khi muốn reset
docker compose down -v
```

---

## Kiểm tra tài nguyên

```bash
# RAM/CPU real-time của các container
docker stats

# Disk usage của Docker
docker system df

# Dung lượng volume neo4j
docker system df -v | grep neo4j
```

---

## Truy cập graph data trực tiếp

```bash
# Vào shell container
docker exec -it neo4j bash

# Chạy Cypher query
docker exec -it neo4j cypher-shell -u neo4j -p 123

# Trong cypher-shell:
neo4j@neo4j> MATCH (n) RETURN count(n);
neo4j@neo4j> MATCH (n:Entity) WHERE n.group_id = 'mirofish_xxx' RETURN n LIMIT 10;
```

Hoặc dùng UI tại <http://localhost:7474>:

```cypher
// Xem toàn bộ graph của 1 group
MATCH (n) WHERE n.group_id = 'mirofish_xxx'
OPTIONAL MATCH (n)-[r]-(m)
RETURN n, r, m LIMIT 100

// Đếm node theo type
MATCH (n) RETURN labels(n)[0] AS type, count(*) AS count
```

---

## Troubleshooting

### Pull image bị reset connection
GitHub Container Registry hay reset với image lớn. **Không cần pull image mirofish** — chỉ cần Neo4j (341MB). Backend chạy trực tiếp trên host bằng Python.

### Backend báo "ZEP_API_KEY is not configured"
File `config.py` còn check biến cũ — đảm bảo đã pull bản mới có Neo4j config.

### Backend lỗi `ModuleNotFoundError: zep_cloud`
Code services chưa migrate xong. Các file cần sửa:
- `backend/app/services/graph_builder.py`
- `backend/app/services/zep_entity_reader.py` → đổi tên thành `entity_reader.py`
- `backend/app/services/zep_tools.py` → đổi tên thành `graph_tools.py`
- `backend/app/services/zep_graph_memory_updater.py`
- `backend/app/services/oasis_profile_generator.py`
- `backend/app/utils/zep_paging.py` → đổi sang `EntityNode.get_by_group_ids()` / `EntityEdge.get_by_group_ids()`

### Connection refused khi backend connect Neo4j
- Check `docker compose ps` xem neo4j có `(healthy)` chưa
- Check `NEO4J_URI` đúng: `bolt://localhost:7687` (host) hay `bolt://neo4j:7687` (docker)
- Đợi đủ ~30s sau khi `up -d neo4j`

### Neo4j OOM trên server RAM nhỏ
Giảm heap trong `docker-compose.yml`:

```yaml
- NEO4J_server_memory_heap_max__size=1g
- NEO4J_server_memory_pagecache_size=512m
```

---

## Mapping Zep → Graphiti (tham khảo khi migrate code)

| Zep SDK | Graphiti |
|---|---|
| `client.graph.search(graph_id, query)` | `await graphiti.search(query, group_ids=[graph_id])` |
| `client.graph.node.get_by_graph_id(graph_id)` | `await EntityNode.get_by_group_ids(driver, [graph_id])` |
| `client.graph.edge.get_by_graph_id(graph_id)` | `await EntityEdge.get_by_group_ids(driver, [graph_id])` |
| `client.graph.node.get(uuid_=x)` | `await EntityNode.get_by_uuid(driver, x)` |
| `client.graph.node.get_entity_edges(node_uuid=x)` | `await EntityEdge.get_by_node_uuid(driver, x)` |
| `client.graph.episode.get(uuid_=x)` | `await EpisodicNode.get_by_uuid(driver, x)` |
| `client.graph.add(...)` | `await graphiti.add_episode(...)` |
| `client.graph.add_batch(...)` | `await graphiti.add_episode_bulk(...)` |
| `client.graph.create(graph_id=x)` | Không cần — `group_id` tự tạo khi add episode |
| `client.graph.set_ontology(...)` | Truyền `entity_types=...` vào `add_episode()` |
| `client.graph.delete(graph_id=x)` | `await EntityNode.delete_by_group_id(driver, x)` + `EpisodicNode.delete_by_group_id(...)` |

---

## Tham khảo

- Graphiti docs: <https://help.getzep.com/graphiti>
- Neo4j Cypher: <https://neo4j.com/docs/cypher-manual/>
- MiroFish gốc: README.md / README-EN.md
