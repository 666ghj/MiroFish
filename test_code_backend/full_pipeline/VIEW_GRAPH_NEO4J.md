# Xem Knowledge Graph trên Neo4j Browser

Hướng dẫn mở Neo4j Browser và xem graph (entity + quan hệ) theo từng `group_id`.

---

## 1. Mở Neo4j Browser

Vào trình duyệt:

**http://localhost:7474/browser/**

Đăng nhập (lấy từ `.env` của project):

| Trường | Giá trị |
|---|---|
| Connect URL | `bolt://localhost:7687` |
| Username | `neo4j` |
| Password | `team10diem` |

> Sau khi connect, gõ Cypher vào ô lệnh trên cùng → bấm ▶ hoặc `Ctrl+Enter` để chạy.

---

## 2. `group_id` là gì — và tại sao BẮT BUỘC dùng

Mỗi lần build graph tạo ra một **`group_id`** riêng (= `graph_id`, dạng `mirofish_<hex>`).
Tất cả node/edge của một graph được gắn cùng `group_id` đó.

⚠️ **Luôn lọc theo `group_id` trong MỌI query.** Nếu không, Neo4j trả về node của **tất cả graph** trộn lẫn → rối và sai.

### Liệt kê các `group_id` đang có

```cypher
MATCH (n:Entity)
RETURN n.group_id AS graph_id, count(*) AS so_entity
ORDER BY so_entity DESC
```

Các graph hiện có (ví dụ — của bạn có thể khác):

| group_id | số entity |
|---|---|
| `mirofish_47869debf1e64df1` | 53 |
| `mirofish_ffef92194e574283` | 31 |
| `mirofish_8770c4041fb141d3` | 30 |
| `mirofish_ea729b57027c4ceb` | 23 |

> 💡 Copy `group_id` muốn xem, rồi thay vào `$GID` trong các query bên dưới.
> `graph_id` cũng được in ra khi build graph xong (`"graph_id": "mirofish_..."`).

---

## 3. Hai kiểu xem chính

### Kiểu A — Xem TRỰC QUAN (entity + quan hệ, dạng đồ thị kéo thả)

Đổi `group_id` cho đúng graph bạn muốn:

```cypher
MATCH (n:Entity {group_id: 'mirofish_8770c4041fb141d3'})-[r:RELATES_TO]->(m:Entity)
RETURN n, r, m
```

→ Neo4j Browser hiện các **node tròn (entity)** nối với nhau bằng **mũi tên (quan hệ)**, kéo thả được.
Bấm vào 1 node/edge để xem chi tiết (name, fact, summary...).

### Kiểu B — Xem dạng BẢNG (tên + loại + tóm tắt entity)

```cypher
MATCH (n:Entity {group_id: 'mirofish_8770c4041fb141d3'})
RETURN n.name AS ten, labels(n) AS loai, n.summary AS tom_tat
```

→ Hiện bảng: tên thực thể | loại (entity type) | tóm tắt.
(Nếu Browser mở ở chế độ Graph, bấm icon **Table** bên trái kết quả để xem dạng bảng.)

---

## 4. Đổi graph khác để xem

Chỉ cần thay chuỗi `group_id` trong query. Ví dụ xem graph 53-entity:

```cypher
MATCH (n:Entity {group_id: 'mirofish_47869debf1e64df1'})-[r:RELATES_TO]->(m:Entity)
RETURN n, r, m
```

---

## 5. Một số query hữu ích khác (tùy chọn)

**Xem cả chunk (Episodic) + entity mà chunk đó trích ra:**
```cypher
MATCH (e:Episodic {group_id: 'mirofish_8770c4041fb141d3'})-[r:MENTIONS]->(n:Entity)
RETURN e, r, n
```

**Xem TẤT CẢ node + mọi quan hệ của 1 graph (graph đầy đủ):**
```cypher
MATCH (n {group_id: 'mirofish_8770c4041fb141d3'})-[r]->(m {group_id: 'mirofish_8770c4041fb141d3'})
RETURN n, r, m
```

**Xem các fact (quan hệ) dạng bảng — nguồn → fact → đích:**
```cypher
MATCH (n:Entity {group_id: 'mirofish_8770c4041fb141d3'})-[r:RELATES_TO]->(m:Entity)
RETURN n.name AS tu, r.fact AS quan_he, m.name AS den
```

**Chỉ xem fact CÒN hiệu lực (bỏ fact đã bị vô hiệu hóa / expired):**
```cypher
MATCH (n:Entity {group_id: 'mirofish_8770c4041fb141d3'})-[r:RELATES_TO]->(m:Entity)
WHERE r.expired_at IS NULL
RETURN n.name AS tu, r.fact AS quan_he, m.name AS den
```

**Giới hạn cho nhẹ (graph lớn):** thêm `LIMIT 50` vào cuối query.

---

## Mẹo

- Loại node: `Entity` (thực thể có tên), `Episodic` (chunk text gốc), quan hệ chính là `RELATES_TO`.
- Trong Browser, kết quả có 2 nút chuyển: **Graph view** (hình tròn) và **Table view** (bảng) — ở cạnh trái khung kết quả.
- Mỗi `:RELATES_TO` có field `fact` (câu mô tả quan hệ), `valid_at` / `invalid_at` / `expired_at` (thông tin thời gian — temporal graph).
