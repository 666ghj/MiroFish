# Báo cáo Kỹ thuật: Pipeline Mô phỏng MiroFish

**Phiên bản:** 1.0  
**Ngày:** 2026-05-04  
**Dự án:** MiroFish — Hệ thống mô phỏng dư luận mạng xã hội dựa trên OASIS Framework

---

## Mục lục

1. [Tổng quan hệ thống](#1-tổng-quan-hệ-thống)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Giai đoạn 0 — Tiền xử lý tài liệu](#3-giai-đoạn-0--tiền-xử-lý-tài-liệu)
4. [Giai đoạn 1 — Khởi tạo Simulation](#4-giai-đoạn-1--khởi-tạo-simulation)
5. [Giai đoạn 2A — Đọc Entity từ Zep Graph](#5-giai-đoạn-2a--đọc-entity-từ-zep-graph)
6. [Giai đoạn 2B — Sinh Agent Profile](#6-giai-đoạn-2b--sinh-agent-profile)
7. [Giai đoạn 2C — Sinh Simulation Config](#7-giai-đoạn-2c--sinh-simulation-config)
8. [Giai đoạn 3 — Chạy Simulation (OASIS)](#8-giai-đoạn-3--chạy-simulation-oasis)
9. [Giai đoạn 4 — Tạo Report (ReACT Agent)](#9-giai-đoạn-4--tạo-report-react-agent)
10. [Cơ chế Fallback toàn hệ thống](#10-cơ-chế-fallback-toàn-hệ-thống)
11. [Cấu trúc file và thư mục](#11-cấu-trúc-file-và-thư-mục)
12. [Luồng dữ liệu end-to-end](#12-luồng-dữ-liệu-end-to-end)

---

## 1. Tổng quan hệ thống

### 1.1 MiroFish là gì?

MiroFish là một hệ thống mô phỏng dư luận trên mạng xã hội. Ý tưởng cốt lõi là: thay vì quan sát xem điều gì đang xảy ra ngoài đời thực, hệ thống **xây dựng lại một thế giới ảo** có các nhân vật (Agent) giống hệt người thật, rồi "thả" một sự kiện vào trong đó để xem mọi người phản ứng như thế nào.

**Ví dụ thực tế:**  
> Một trường đại học muốn biết: nếu họ tăng học phí 20%, sinh viên, giảng viên, phụ huynh và báo chí sẽ phản ứng ra sao trên mạng xã hội? Thay vì phải thực sự tăng học phí rồi chờ xem hậu quả, MiroFish mô phỏng kịch bản đó trước và dự báo kết quả.

### 1.2 Các thành phần chính

| Thành phần | Vai trò |
|---|---|
| **Zep** | Cơ sở dữ liệu đồ thị (Graph Database) chứa thông tin về các thực thể (người, tổ chức, sự kiện) được trích xuất từ tài liệu gốc |
| **OASIS Framework** | Framework mã nguồn mở chạy mô phỏng mạng xã hội với các Agent AI |
| **LLM (Large Language Model)** | Mô hình ngôn ngữ lớn (như GPT-4, Gemini...) được dùng để tạo hồ sơ nhân vật, cấu hình mô phỏng và viết báo cáo |
| **Flask Backend** | Server Python xử lý API, quản lý trạng thái và điều phối toàn bộ pipeline |
| **Vue.js Frontend** | Giao diện người dùng để upload tài liệu, theo dõi tiến trình và xem báo cáo |

### 1.3 Luồng tổng quát (5 giai đoạn)

```
[Tài liệu gốc] 
      ↓  (Tiền xử lý)
[Zep Graph: Entities + Relationships]
      ↓  (Đọc + Lọc)
[Danh sách EntityNode]
      ↓  (Sinh Profile song song)
[Agent Profiles (reddit_profiles.json / twitter_profiles.csv)]
      ↓  (LLM sinh Config)
[simulation_config.json]
      ↓  (OASIS subprocess)
[actions.jsonl — Log hành động của từng Agent theo từng Round]
      ↓  (ReACT Agent viết báo cáo)
[report.md — Báo cáo dự báo tương lai]
```

---

## 2. Kiến trúc tổng thể

### 2.1 Sơ đồ các module

```
backend/
├── app/
│   ├── services/
│   │   ├── text_processor.py           # Tiền xử lý văn bản
│   │   ├── zep_entity_reader.py        # Đọc Entity từ Zep Graph
│   │   ├── oasis_profile_generator.py  # Sinh Agent Profile
│   │   ├── simulation_config_generator.py  # Sinh tham số mô phỏng
│   │   ├── simulation_manager.py       # Quản lý vòng đời Simulation
│   │   ├── simulation_runner.py        # Chạy + giám sát Simulation
│   │   ├── simulation_ipc.py           # Giao tiếp Flask ↔ OASIS subprocess
│   │   └── report_agent.py             # Viết báo cáo bằng ReACT
│   └── utils/
│       └── llm_cost.py                 # Theo dõi chi phí LLM
└── scripts/
    ├── run_parallel_simulation.py      # OASIS chạy cả hai nền tảng
    ├── run_twitter_simulation.py       # OASIS chỉ Twitter
    ├── run_reddit_simulation.py        # OASIS chỉ Reddit
    └── action_logger.py                # Ghi log hành động Agent
```

### 2.2 Phân tách trách nhiệm

**Flask Backend** (process chính) chịu trách nhiệm:
- Nhận request từ Frontend
- Gọi các service theo đúng thứ tự
- Theo dõi trạng thái và lưu vào file JSON
- Expose API để Frontend poll tiến độ

**OASIS Scripts** (subprocess độc lập) chịu trách nhiệm:
- Khởi tạo môi trường mạng xã hội ảo
- Chạy các vòng (round) mô phỏng
- Cho từng Agent AI "suy nghĩ" và hành động
- Ghi log hành động ra file `actions.jsonl`

Hai phần này giao tiếp với nhau qua **hai cơ chế**:
1. **File-based**: Flask đọc `actions.jsonl` để monitor tiến độ
2. **IPC (Inter-Process Communication)**: Flask ghi lệnh vào `ipc_commands/`, OASIS poll và trả kết quả vào `ipc_responses/` (dùng cho tính năng Interview agent đang chạy)

---

## 3. Giai đoạn 0 — Tiền xử lý tài liệu

**File:** `backend/app/services/text_processor.py`

### 3.1 Mục đích

Trước khi bắt đầu bất kỳ thứ gì, tài liệu gốc của người dùng (PDF, Word, TXT...) phải được chuyển thành văn bản thuần túy và làm sạch.

### 3.2 Luồng xử lý

```
[File upload từ User]
        ↓
TextProcessor.extract_from_files(file_paths)
        ↓  (gọi FileParser.extract_from_multiple)
[raw_text: str]  ← văn bản thô chưa sạch
        ↓
TextProcessor.preprocess_text(raw_text)
        ↓  (chuẩn hóa newline, xóa khoảng trắng thừa)
[document_text: str]  ← văn bản sạch, sẵn sàng dùng
```

### 3.3 Chi tiết xử lý làm sạch

`preprocess_text()` thực hiện 3 bước:
1. Chuẩn hóa ký tự xuống dòng: `\r\n` (Windows) và `\r` (Mac cũ) → `\n` (Linux chuẩn)
2. Loại bỏ dòng trống liên tiếp: nếu có 3 dòng trống liên tiếp → rút về tối đa 2
3. Xóa khoảng trắng đầu/cuối mỗi dòng

### 3.4 Output

`document_text: str` — Chuỗi văn bản sạch, được dùng ở hai nơi sau đó:
- Truyền vào **Zep Graph Builder** để xây đồ thị (qua pipeline riêng, trước khi vào pipeline Simulation)
- Truyền thẳng vào **SimulationConfigGenerator** làm ngữ cảnh cho LLM sinh tham số

> **Lưu ý quan trọng:** Pipeline Simulation giả sử Zep Graph đã được build từ trước. Nghĩa là người dùng phải chạy bước "Phân tích tài liệu / Build Graph" trước, rồi mới chạy Simulation.

---

## 4. Giai đoạn 1 — Khởi tạo Simulation

**File:** `backend/app/services/simulation_manager.py`  
**Hàm:** `SimulationManager.create_simulation()`

### 4.1 Mục đích

Tạo một "phòng mô phỏng" rỗng với ID định danh riêng, chưa có dữ liệu gì. Giống như đặt một bàn làm việc trống trước khi bắt đầu.

### 4.2 Input

```python
project_id: str      # ID dự án (gắn với tài liệu gốc)
graph_id: str        # ID của Zep Graph đã được build từ tài liệu
enable_twitter: bool # Có chạy mô phỏng Twitter không?
enable_reddit: bool  # Có chạy mô phỏng Reddit không?
```

### 4.3 Luồng xử lý

```python
# 1. Tạo ID ngẫu nhiên
simulation_id = f"sim_{uuid4().hex[:12]}"  
# Ví dụ: "sim_a3f9c2b81e4d"

# 2. Khởi tạo object trạng thái
state = SimulationState(
    simulation_id=simulation_id,
    status=SimulationStatus.CREATED,
    ...
)

# 3. Lưu ra file
uploads/simulations/{simulation_id}/state.json

# 4. Cache vào RAM
self._simulations[simulation_id] = state
```

### 4.4 Output

`SimulationState` object với `status = CREATED`

**Nội dung `state.json` lúc này:**
```json
{
  "simulation_id": "sim_a3f9c2b81e4d",
  "project_id": "proj_xyz",
  "graph_id": "graph_abc",
  "enable_twitter": true,
  "enable_reddit": true,
  "status": "created",
  "entities_count": 0,
  "profiles_count": 0,
  "config_generated": false,
  "created_at": "2026-05-04T10:00:00"
}
```

### 4.5 Cơ chế load lại trạng thái

`SimulationManager` có hai tầng cache:
1. **RAM cache** (`_simulations` dict): Truy cập tức thì, mất khi restart server
2. **File cache** (`state.json`): Persistent, load lại khi RAM không có

Khi gọi `_load_simulation_state(simulation_id)`:
- Tìm trong RAM trước → nếu có, trả về luôn
- Nếu không có → đọc từ `state.json` → parse → lưu vào RAM → trả về

---

## 5. Giai đoạn 2A — Đọc Entity từ Zep Graph

**File:** `backend/app/services/zep_entity_reader.py`  
**Hàm:** `ZepEntityReader.filter_defined_entities()`

### 5.1 Zep Graph là gì?

Zep là một **Graph Database** (cơ sở dữ liệu dạng đồ thị). Sau khi người dùng upload tài liệu, hệ thống đã phân tích và lưu các thông tin vào Zep dưới dạng:
- **Node** (Nút): Đại diện cho một thực thể (người, tổ chức, địa điểm, sự kiện...)
- **Edge** (Cạnh): Đại diện cho mối quan hệ giữa hai thực thể ("A là giám đốc của B", "C phát biểu về D"...)

**Ví dụ về một Graph từ tài liệu về trường đại học:**
```
[Trần Văn A] --[là sinh viên của]--> [Đại học X]
[Nguyễn B]   --[là giảng viên của]--> [Đại học X]
[Đại học X]  --[tăng học phí]--> [Năm học 2025]
[VnExpress]  --[đưa tin về]--> [Đại học X]
```

### 5.2 Cấu trúc dữ liệu EntityNode

```python
@dataclass
class EntityNode:
    uuid: str               # ID định danh duy nhất trong Zep
    name: str               # Tên ("Trần Văn A", "Đại học X")
    labels: List[str]       # Loại thực thể ["Entity", "Student"]
    summary: str            # Tóm tắt do Zep tự sinh ra
    attributes: Dict        # Thuộc tính bổ sung {"age": 20, "major": "CNTT"}
    related_edges: List     # Các quan hệ liên quan
    related_nodes: List     # Các node khác có kết nối
```

**Ví dụ thực tế một EntityNode:**
```json
{
  "uuid": "e1a2b3c4-...",
  "name": "Trần Văn An",
  "labels": ["Entity", "Student"],
  "summary": "Sinh viên năm 3 ngành CNTT tại Đại học X, tích cực tham gia các hoạt động sinh viên",
  "attributes": {"year": 3, "major": "Computer Science"},
  "related_edges": [
    {"direction": "outgoing", "edge_name": "studies_at", "fact": "Trần Văn An học tại Đại học X"}
  ],
  "related_nodes": [
    {"name": "Đại học X", "labels": ["Entity", "University"], "summary": "..."}
  ]
}
```

### 5.3 Luồng xử lý chi tiết

```
filter_defined_entities(graph_id, defined_entity_types, enrich_with_edges=True)
        |
        ├── get_all_nodes(graph_id)
        │       └── fetch_all_nodes() — có phân trang, retry 3 lần, backoff 2s→4s→8s
        │           → List[Dict] — toàn bộ node trong Graph
        │
        ├── get_all_edges(graph_id)
        │       └── fetch_all_edges() — có phân trang, retry 3 lần
        │           → List[Dict] — toàn bộ edge trong Graph
        │
        ├── Xây dựng node_map: {uuid → node_data}
        │
        └── Lặp qua từng node:
                ├── Lọc: giữ lại node có custom label (khác "Entity" và "Node")
                │         Ví dụ: ["Entity", "Student"] → giữ, vì có "Student"
                │         Ví dụ: ["Entity"]             → bỏ, vì chỉ có "Entity"
                │
                ├── Nếu defined_entity_types được chỉ định:
                │         chỉ giữ node có label khớp với danh sách
                │
                ├── Tìm related_edges: duyệt all_edges, lấy các edge
                │         có source_node_uuid HOẶC target_node_uuid = node.uuid
                │         → gán direction: "outgoing" hoặc "incoming"
                │
                └── Tìm related_nodes: từ related_node_uuids → tra node_map
                         → lấy thông tin cơ bản (uuid, name, labels, summary)
```

### 5.4 Output

```python
FilteredEntities(
    entities=[EntityNode, EntityNode, ...],  # Danh sách entity đã lọc
    entity_types={"Student", "University", "MediaOutlet"},  # Các loại xuất hiện
    total_count=150,    # Tổng số node trong graph
    filtered_count=47,  # Số entity hợp lệ sau lọc
)
```

### 5.5 Cơ chế Retry

Mọi lời gọi Zep API đều được bọc trong `_call_with_retry()`:
- Thử tối đa **3 lần**
- Độ trễ giữa các lần: **2s → 4s → 8s** (Exponential backoff)
- Nếu vẫn fail sau 3 lần → raise exception lên caller

### 5.6 Fallback nghiêm trọng

Nếu `filtered_count == 0` sau khi lọc:
```python
state.status = SimulationStatus.FAILED
state.error = "No valid entities extracted for simulation. Please check if the Graph was generated properly with valid text."
```
Pipeline **dừng hoàn toàn**, không tiếp tục.

---

## 6. Giai đoạn 2B — Sinh Agent Profile

**File:** `backend/app/services/oasis_profile_generator.py`  
**Hàm:** `OasisProfileGenerator.generate_profiles_from_entities()`

### 6.1 Mục đích

Mỗi EntityNode (thực thể trong Zep) cần được "hóa thân" thành một Agent AI với đủ nhân cách, lịch sử, cách nói chuyện... để khi chạy mô phỏng, Agent đó behave đúng như người thật. Đây là bước **chuyển đổi từ dữ liệu khô sang nhân vật sống động**.

**Ví dụ:**
- EntityNode: `{name: "Trần Văn An", labels: ["Student"], summary: "Sinh viên năm 3 CNTT"}`
- OasisAgentProfile: `{bio: "Sinh viên CNTT năm 3 tại Đại học X, mê game và lo lắng về học phí tăng", persona: "Trần Văn An là sinh viên 21 tuổi, MBTI INFP, hay đăng status buổi đêm, viết theo kiểu Gen Z, thường phản ứng nhanh với tin tức về học phí..."}`

### 6.2 Cấu trúc OasisAgentProfile

```python
@dataclass
class OasisAgentProfile:
    user_id: int          # Index (0, 1, 2, ...)
    user_name: str        # "tran_van_an_492" (tên tài khoản, random suffix)
    name: str             # "Trần Văn An"
    bio: str              # Tiểu sử ngắn hiển thị công khai (~200 ký tự)
    persona: str          # Mô tả nhân cách chi tiết (~2000 từ) — LLM dùng làm System Prompt
    karma: int            # (Reddit) Điểm karma
    friend_count: int     # (Twitter) Số bạn bè
    follower_count: int   # (Twitter) Số người theo dõi
    age: int
    gender: str           # "male" / "female" / "other"
    mbti: str             # "INFP", "ESTJ", ...
    country: str          # "Việt Nam"
    profession: str       # "Sinh viên"
    interested_topics: List[str]
```

**Điểm quan trọng về `persona`:** Đây là chuỗi văn bản ~2000 từ mà OASIS sẽ nhét vào **System Prompt** của Agent khi nó "suy nghĩ" và đưa ra hành động. Nó quyết định toàn bộ cách Agent đó hoạt động trong mô phỏng.

### 6.3 Luồng song song (ThreadPoolExecutor)

```python
with ThreadPoolExecutor(max_workers=parallel_count) as executor:
    # Giao việc cho tất cả entity cùng lúc
    futures = {executor.submit(generate_single_profile, idx, entity): (idx, entity)
               for idx, entity in enumerate(entities)}
    
    # Thu gom kết quả khi từng profile hoàn thành
    for future in as_completed(futures):
        result_idx, profile, error = future.result()
        profiles[result_idx] = profile
        save_profiles_realtime()  # Lưu ngay, không chờ tất cả xong
```

Mặc định `parallel_count = 3` — tức là tại bất kỳ thời điểm nào, tối đa 3 entity được xử lý đồng thời.

### 6.4 Luồng xử lý cho từng entity

```
generate_single_profile(idx, entity)
        |
        ├── _build_entity_context(entity)
        │       ├── 1. Lấy attributes của node
        │       ├── 2. Lấy facts từ related_edges (đã có từ bước trước)
        │       ├── 3. Lấy summary của related_nodes
        │       └── 4. _search_zep_for_entity() — Gọi Zep Vector Search
        │               ├── search_edges(query) — thread 1
        │               └── search_nodes(query) — thread 2
        │               (2 thread chạy song song, retry 3 lần mỗi cái)
        │               → ghép thành context string
        │
        ├── Phân loại entity type:
        │       ├── INDIVIDUAL: student, alumni, professor, person, publicfigure...
        │       └── GROUP: university, governmentagency, ngo, mediaoutlet...
        │
        └── _generate_profile_with_llm(entity_name, type, summary, attrs, context)
                ├── Chọn prompt template:
                │       ├── Individual → _build_individual_persona_prompt()
                │       └── Group → _build_group_persona_prompt()
                │
                └── Gọi LLM (retry vòng lặp):
                        Attempt 1: temperature=0.7
                        Attempt 2: temperature=0.6  (nếu fail)
                        Attempt 3: temperature=0.5  (nếu fail)
                        → JSON với bio, persona, age, gender, mbti, country...
```

### 6.5 Chi tiết Zep Vector Search

`_search_zep_for_entity()` dùng **semantic search** — tìm kiếm theo nghĩa, không phải từ khóa:

```python
comprehensive_query = f"Provide all facts, activities, relationships, and context about: {entity_name}"

# Chạy song song 2 loại search
search_edges() → tìm trong các mối quan hệ (edge) — lấy tối đa 30 kết quả
search_nodes() → tìm trong các node thực thể — lấy tối đa 20 kết quả
```

Mỗi search có retry riêng: 3 lần, backoff 2s→4s→8s.  
Nếu timeout tổng (30s) hoặc fail hoàn toàn → trả về `{"facts": [], "node_summaries": [], "context": ""}` và tiếp tục không lỗi.

### 6.6 Xử lý JSON từ LLM

LLM đôi khi trả về JSON bị hỏng (cắt ngang do token limit, ký tự lạ...). Hệ thống có chuỗi sửa lỗi:

```
LLM response
      |
      ├── finish_reason == "length"? → _fix_truncated_json()
      │       Đếm { và } chưa đóng → tự thêm vào cuối
      │
      ├── json.loads() lỗi? → _try_fix_json()
      │       ├── Gọi _fix_truncated_json() trước
      │       ├── Dùng regex tìm khối {...} lớn nhất
      │       ├── Clean newline trong string values
      │       ├── Xóa control characters (0x00–0x1F)
      │       └── Nếu vẫn fail → regex mót bio và persona riêng lẻ
      │
      └── Sau 3 attempt đều fail → _generate_profile_rule_based()
```

### 6.7 Fallback theo Rule (khi LLM hoàn toàn thất bại)

| Entity Type | age | gender | activity | influence |
|---|---|---|---|---|
| student / alumni | 18–30 | random | Cao, chủ yếu buổi tối | Thấp |
| publicfigure / expert / faculty | 35–60 | random | Trung bình | Cao |
| mediaoutlet | 30 (ảo) | "other" | Cả ngày | Rất cao |
| university / governmentagency / ngo | 30 (ảo) | "other" | Giờ hành chính | Rất cao |
| Default | 25–50 | random | Trung bình | Trung bình |

### 6.8 Lưu file kết quả

**Reddit format** (`reddit_profiles.json`):
```json
[
  {
    "user_id": 0,
    "username": "tran_van_an_492",
    "name": "Trần Văn An",
    "bio": "Sinh viên CNTT năm 3, lo lắng về học phí...",
    "persona": "Trần Văn An là sinh viên 21 tuổi...(2000 từ mô tả nhân cách)...",
    "karma": 1500,
    "age": 21,
    "gender": "male",
    "mbti": "INFP",
    "country": "Việt Nam"
  }
]
```

**Twitter format** (`twitter_profiles.csv`):
```csv
user_id,name,username,user_char,description
0,Trần Văn An,tran_van_an_492,"bio + persona ghép lại (System Prompt cho LLM)","bio ngắn"
```

**Realtime save:** Sau mỗi profile hoàn thành (không cần chờ tất cả), file được ghi ngay. Điều này đảm bảo nếu server crash giữa chừng, dữ liệu đã gen không bị mất.

---

## 7. Giai đoạn 2C — Sinh Simulation Config

**File:** `backend/app/services/simulation_config_generator.py`  
**Hàm:** `SimulationConfigGenerator.generate_config()`

### 7.1 Mục đích

Đây là giai đoạn LLM "thiết kế kịch bản mô phỏng". Dựa trên yêu cầu của người dùng + dữ liệu entity, LLM quyết định:
- Mô phỏng kéo dài bao nhiêu giờ?
- Giờ nào sẽ có nhiều hoạt động?
- Sự kiện ban đầu nào sẽ khởi động cuộc thảo luận?
- Mỗi Agent sẽ hoạt động theo kiểu gì?

### 7.2 Luồng tổng quát (tuần tự, không song song)

```
generate_config(simulation_id, project_id, graph_id, simulation_requirement,
                document_text, entities, enable_twitter, enable_reddit)
        │
        ├── _build_context()      → context string (tối đa 50,000 ký tự)
        │       ├── simulation_requirement (giữ nguyên)
        │       ├── entity summary (tóm tắt theo loại, tối đa 20 entity/loại)
        │       └── document_text (phần còn lại, bị cắt nếu quá dài)
        │
        ├── Step 1: _generate_time_config()      → TimeSimulationConfig
        ├── Step 2: _generate_event_config()     → EventConfig (có initial posts)
        ├── Step 3..N: _generate_agent_configs_batch()  (15 agent/lần)
        ├── _assign_initial_post_agents()        → gán agent_id cho từng post
        └── Hardcode: Twitter + Reddit PlatformConfig
```

### 7.3 Step 1 — Cấu hình Thời gian

**Hàm:** `_generate_time_config(context, num_entities)`

LLM nhận context đã được cắt còn 10,000 ký tự và sinh ra:

```json
{
  "total_simulation_hours": 72,
  "minutes_per_round": 60,
  "agents_per_hour_min": 5,
  "agents_per_hour_max": 30,
  "peak_hours": [19, 20, 21, 22],
  "off_peak_hours": [0, 1, 2, 3, 4, 5],
  "morning_hours": [6, 7, 8],
  "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
  "reasoning": "Chủ đề học phí thu hút cả sinh viên và phụ huynh, cao điểm tối..."
}
```

**Validation sau khi nhận:**
```python
# Đảm bảo agents_per_hour không vượt tổng số agent thực tế
if agents_per_hour_min > num_entities:
    agents_per_hour_min = max(1, num_entities // 10)
if agents_per_hour_max > num_entities:
    agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
if agents_per_hour_min >= agents_per_hour_max:
    agents_per_hour_min = max(1, agents_per_hour_max // 2)
```

**Fallback (LLM fail):**
```python
{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": max(1, num_entities // 15),
    "agents_per_hour_max": max(5, num_entities // 5),
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    ...
}
```

**Ý nghĩa các thông số:**
- `total_simulation_hours = 72` → Mô phỏng 3 ngày thực (72 vòng nếu mỗi vòng = 1 giờ)
- `minutes_per_round = 60` → Mỗi vòng đại diện cho 1 giờ trong thế giới thực
- `agents_per_hour_min/max = 5/30` → Mỗi giờ, OASIS sẽ kích hoạt ngẫu nhiên 5 đến 30 agent để hoạt động

### 7.4 Step 2 — Cấu hình Sự kiện

**Hàm:** `_generate_event_config(context, simulation_requirement, entities)`

LLM sinh ra "ngòi nổ" cho cuộc mô phỏng — các bài đăng đầu tiên sẽ khởi động thảo luận:

```json
{
  "hot_topics": ["học phí", "biểu tình", "phản đối", "giáo dục công lập"],
  "narrative_direction": "Thông báo tăng học phí gây ra làn sóng phản ứng mạnh từ sinh viên, dần leo thang thành phong trào...",
  "initial_posts": [
    {
      "content": "CHÍNH THỨC: Đại học X thông báo tăng học phí 20% từ học kỳ tới. Xem chi tiết tại...",
      "poster_type": "MediaOutlet"
    },
    {
      "content": "Không thể chấp nhận được! Học phí đã cao mà còn tăng thêm?! #HọcPhíTăng",
      "poster_type": "Student"
    }
  ],
  "reasoning": "..."
}
```

**Sau đó:** `_assign_initial_post_agents()` ghép mỗi post với agent phù hợp:

```
poster_type = "MediaOutlet"
      │
      ├── 1. Direct match: agents_by_type["mediaoutlet"] → lấy agent đầu tiên
      │
      ├── 2. Alias match (nếu direct fail):
      │       type_aliases = {
      │           "mediaoutlet": ["mediaoutlet", "media"],
      │           "official": ["official", "university", "governmentagency", "government"],
      │           "student": ["student", "person"],
      │           ...
      │       }
      │
      └── 3. Fallback: agent có influence_weight cao nhất
```

Kết quả: `poster_agent_id` được gán vào mỗi post:
```json
{"content": "CHÍNH THỨC...", "poster_type": "MediaOutlet", "poster_agent_id": 12}
```

### 7.5 Step 3..N — Cấu hình Agent (chia batch)

**Hàm:** `_generate_agent_configs_batch(context, entities_batch, start_idx, simulation_requirement)`

Do số lượng agent có thể lớn, không thể đưa tất cả vào một prompt. Hệ thống chia nhỏ **15 agent một lần**:

```
47 agents → batch 1 (agent 0-14) + batch 2 (agent 15-29) + batch 3 (agent 30-44) + batch 4 (agent 45-46)
```

Với mỗi batch, gửi cho LLM danh sách entity và nhận lại cấu hình hoạt động:

```json
{
  "agent_configs": [
    {
      "agent_id": 0,
      "activity_level": 0.8,
      "posts_per_hour": 0.6,
      "comments_per_hour": 1.5,
      "active_hours": [8, 9, 10, 18, 19, 20, 21, 22, 23],
      "response_delay_min": 1,
      "response_delay_max": 15,
      "sentiment_bias": -0.3,
      "stance": "opposing",
      "influence_weight": 0.8
    }
  ]
}
```

**Giải thích các thông số:**
- `activity_level`: 0.0–1.0, xác suất agent "thức dậy" trong một round
- `posts_per_hour`: Trung bình số bài đăng mới mỗi giờ
- `comments_per_hour`: Trung bình số bình luận mỗi giờ
- `active_hours`: Danh sách giờ trong ngày agent có thể hoạt động (0–23)
- `response_delay_min/max`: Thời gian (phút mô phỏng) agent chờ trước khi phản ứng với tin hot
- `sentiment_bias`: -1.0 (rất tiêu cực) → 0.0 (trung lập) → 1.0 (rất tích cực)
- `stance`: "supportive" / "opposing" / "neutral" / "observer"
- `influence_weight`: Mức độ bài đăng của agent này được agent khác nhìn thấy và quan tâm

**Fallback theo rule khi LLM fail:**

| Entity Type | activity | active_hours | response_delay | influence |
|---|---|---|---|---|
| university / governmentagency | 0.2 | 9–17 | 60–240 phút | 3.0 |
| mediaoutlet | 0.5 | 7–23 | 5–30 phút | 2.5 |
| professor / expert / official | 0.4 | 8–21 | 15–90 phút | 2.0 |
| student | 0.8 | Sáng + Tối | 1–15 phút | 0.8 |
| alumni | 0.6 | Trưa + Tối | 5–30 phút | 1.0 |
| Default | 0.7 | 9–23 | 2–20 phút | 1.0 |

### 7.6 Cơ chế retry chung cho mọi LLM call

Tất cả LLM call trong `SimulationConfigGenerator` đi qua `_call_llm_with_retry()`:

```
Attempt 1: temperature=0.7
      ↓ (nếu fail hoặc JSON lỗi)
Attempt 2: temperature=0.6
      ↓
Attempt 3: temperature=0.5
      ↓ (nếu vẫn fail)
→ raise exception → caller dùng hardcode fallback
```

Giữa các lần retry nếu lỗi connection: sleep `2*(attempt+1)` giây (2s, 4s).

### 7.7 File đầu ra

`uploads/simulations/{sim_id}/simulation_config.json` — **File quan trọng nhất**, được đọc bởi cả Flask và OASIS scripts:

```json
{
  "simulation_id": "sim_a3f9c2b81e4d",
  "project_id": "proj_xyz",
  "graph_id": "graph_abc",
  "simulation_requirement": "Mô phỏng phản ứng của cộng đồng khi Đại học X tăng học phí 20%",
  "time_config": {
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 30,
    "peak_hours": [19, 20, 21, 22],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "peak_activity_multiplier": 1.5,
    "off_peak_activity_multiplier": 0.05
  },
  "agent_configs": [
    {
      "agent_id": 0,
      "entity_uuid": "e1a2b3...",
      "entity_name": "Trần Văn An",
      "entity_type": "Student",
      "activity_level": 0.8,
      "stance": "opposing",
      "influence_weight": 0.8,
      ...
    }
  ],
  "event_config": {
    "hot_topics": ["học phí", "biểu tình"],
    "narrative_direction": "...",
    "initial_posts": [
      {
        "content": "CHÍNH THỨC: Đại học X tăng học phí...",
        "poster_type": "MediaOutlet",
        "poster_agent_id": 12
      }
    ]
  },
  "twitter_config": {
    "platform": "twitter",
    "recency_weight": 0.4,
    "popularity_weight": 0.3,
    "viral_threshold": 10,
    "echo_chamber_strength": 0.5
  },
  "reddit_config": {
    "platform": "reddit",
    "recency_weight": 0.3,
    "popularity_weight": 0.4,
    "viral_threshold": 15,
    "echo_chamber_strength": 0.6
  }
}
```

Sau khi lưu file này, `state.status` được cập nhật thành `READY`.

---

## 8. Giai đoạn 3 — Chạy Simulation (OASIS)

**Files:** `backend/app/services/simulation_runner.py` + `backend/scripts/run_parallel_simulation.py`

### 8.1 Mô hình chạy

Flask **không** chạy OASIS trực tiếp trong cùng process. Thay vào đó:

```
Flask Process
      │
      └── subprocess.Popen(run_parallel_simulation.py --config ...)
                │
                ├── OASIS Twitter Environment (async task)
                └── OASIS Reddit Environment (async task)
```

**Lý do tách process:** OASIS là framework async nặng, chạy nhiều agent đồng thời. Nếu chạy trong Flask sẽ block hoàn toàn API server. Tách process giúp Flask vẫn nhận được request trong khi OASIS chạy ngầm.

### 8.2 Khởi động Simulation

**Hàm:** `SimulationRunner.start_simulation()`

```python
# 1. Load config
with open(config_path) as f:
    config = json.load(f)

# 2. Tính tổng số round
total_rounds = int(total_hours * 60 / minutes_per_round)
# Ví dụ: 72 giờ × 60 phút / 60 phút/round = 72 rounds

# 3. Chọn script
script_name = "run_parallel_simulation.py"  # hoặc twitter/reddit only

# 4. Khởi động subprocess
process = subprocess.Popen(
    [sys.executable, script_path, "--config", config_path],
    cwd=sim_dir,
    stdout=main_log_file,   # stdout → simulation.log
    stderr=subprocess.STDOUT,
    start_new_session=True, # Tạo process group mới (quan trọng cho kill)
    env={...PYTHONUTF8=1...}
)

# 5. Lưu PID để có thể kill sau này
state.process_pid = process.pid

# 6. Khởi động thread giám sát
monitor_thread = Thread(target=cls._monitor_simulation, args=(simulation_id,), daemon=True)
monitor_thread.start()
```

### 8.3 Bên trong OASIS Script

**File:** `backend/scripts/run_parallel_simulation.py`

Script này chạy bằng Python asyncio, khởi tạo hai môi trường mạng xã hội:

```python
# Tạo LLM model (dùng camel-ai ModelFactory)
model = ModelFactory.create(ModelPlatformType.OPENAI, ...)

# Tạo Twitter environment
twitter_env = TwitterSocialEnvironment(...)
twitter_agent_graph = generate_twitter_agent_graph(
    profiles=twitter_profiles,    # Đọc từ twitter_profiles.csv
    model=model,
    initial_posts=initial_posts   # Đọc từ simulation_config.json
)

# Tạo Reddit environment
reddit_env = RedditSocialEnvironment(...)
reddit_agent_graph = generate_reddit_agent_graph(
    profiles=reddit_profiles,     # Đọc từ reddit_profiles.json
    model=model,
    initial_posts=initial_posts
)
```

**Vòng lặp Simulation:**
```
Round 1 (giờ 0:00 - 1:00)
      │
      ├── Tính activity_multiplier:
      │       hour=0 → off_peak → multiplier=0.05
      │       hour=20 → peak → multiplier=1.5
      │
      ├── Tính số agent active = random(min, max) * multiplier
      │
      ├── Chọn ngẫu nhiên N agents từ danh sách
      │
      ├── Với mỗi agent được chọn:
      │       ├── Agent "nhìn" timeline (các bài đăng gần đây)
      │       ├── LLM suy nghĩ dựa trên persona + nội dung thấy được
      │       └── LLM chọn một action:
      │               Twitter: CREATE_POST / LIKE_POST / REPOST / FOLLOW / DO_NOTHING / QUOTE_POST
      │               Reddit:  CREATE_POST / CREATE_COMMENT / LIKE_POST / DISLIKE_POST / SEARCH_POSTS / ...
      │
      └── Ghi log ra actions.jsonl
              {"round": 1, "agent_id": 5, "agent_name": "...", "action_type": "CREATE_POST", "action_args": {...}}

Round 2...
...
Round 72 → ghi {"event_type": "simulation_end", "total_rounds": 72, "total_actions": 3420}
```

### 8.4 Cấu trúc file log

```
uploads/simulations/{sim_id}/
├── twitter/
│   └── actions.jsonl    ← mỗi dòng là 1 hành động trên Twitter
├── reddit/
│   └── actions.jsonl    ← mỗi dòng là 1 hành động trên Reddit
├── simulation.log       ← stdout/stderr của subprocess
└── run_state.json       ← trạng thái real-time (Flask cập nhật)
```

**Ví dụ một dòng trong `actions.jsonl`:**
```json
{
  "round": 15,
  "timestamp": "2026-05-04T15:30:00",
  "agent_id": 3,
  "agent_name": "tran_van_an_492",
  "action_type": "CREATE_POST",
  "action_args": {
    "content": "Không chịu nổi rồi! Học phí tăng 20% mà lương bố mẹ mình có tăng đâu... #HọcPhíTăng #ĐạiHọcX"
  },
  "result": "Post created with id 142",
  "success": true
}
```

**Sự kiện hệ thống (không phải hành động agent):**
```json
{"event_type": "round_end", "round": 15, "simulated_hours": 15}
{"event_type": "simulation_end", "total_rounds": 72, "total_actions": 3420}
```

### 8.5 Monitor Thread

**Hàm:** `SimulationRunner._monitor_simulation()` — chạy liên tục trong nền:

```
Mỗi 2 giây:
      ├── Đọc twitter/actions.jsonl từ vị trí đã đọc lần trước (file seek)
      │       → parse từng dòng JSON mới
      │       → cập nhật state.twitter_current_round, state.twitter_actions_count
      │       → phát hiện event_type "simulation_end" → state.twitter_completed = True
      │
      ├── Làm tương tự với reddit/actions.jsonl
      │
      ├── Kiểm tra _check_all_platforms_completed():
      │       Nếu cả 2 platform đều completed → state.runner_status = COMPLETED
      │
      └── Lưu run_state.json (để Frontend có thể poll tiến độ qua API)
```

**Khi subprocess kết thúc:**
- `exit_code = 0` → `COMPLETED`
- `exit_code != 0` → `FAILED`, đọc 2000 ký tự cuối `simulation.log` làm error message
- Dù thế nào: đóng file handles, xóa khỏi `_processes` dict

### 8.6 Dừng Simulation

**Hàm:** `SimulationRunner.stop_simulation()`

Phải dừng cả **process group** (bao gồm subprocess và các child của nó):

```python
# Unix/Linux/Mac:
pgid = os.getpgid(process.pid)
os.killpg(pgid, signal.SIGTERM)  # Gửi SIGTERM nhẹ nhàng
process.wait(timeout=10)         # Chờ tối đa 10s
# Nếu timeout → os.killpg(pgid, signal.SIGKILL)  # Kill cưỡng bức

# Windows:
subprocess.run(['taskkill', '/PID', str(pid), '/T'])      # /T = kill cả tree
# Nếu timeout → subprocess.run(['taskkill', '/F', '/PID', str(pid), '/T'])  # /F = force
```

Lý do phải dùng process group thay vì kill process đơn: OASIS script có thể spawn thêm child process, phải kill toàn bộ.

### 8.7 IPC — Interview Agent đang chạy

Trong khi simulation đang chạy, người dùng có thể "phỏng vấn" một agent bất kỳ:

```
Flask API nhận request interview(agent_id=5, prompt="Bạn nghĩ gì về việc tăng học phí?")
      │
      └── SimulationIPCClient.send_interview()
              │
              ├── Ghi file: ipc_commands/{uuid}.json
              │       {"command_id": "...", "command_type": "interview", "args": {"agent_id": 5, "prompt": "..."}}
              │
              └── Poll ipc_responses/{uuid}.json (mỗi 0.5s, timeout 60s)
                      │
                      └── (Bên trong OASIS script, ParallelIPCHandler poll ipc_commands/*)
                              │
                              ├── Phát hiện command mới
                              ├── Chạy ManualAction INTERVIEW với agent 5
                              ├── Agent 5 LLM trả lời câu hỏi dựa trên persona
                              └── Ghi kết quả: ipc_responses/{uuid}.json
                                      {"command_id": "...", "status": "completed", "result": {"response": "..."}}
```

**Fallback interview:** Nếu environment không alive (env_status.json không có status="alive") → raise `ValueError` ngay, không gửi IPC.

---

## 9. Giai đoạn 4 — Tạo Report (ReACT Agent)

**File:** `backend/app/services/report_agent.py`

### 9.1 ReACT là gì?

ReACT (Reason + Act) là một kỹ thuật prompting cho LLM, trong đó LLM được phép:
1. **Suy nghĩ** (Reason) về việc cần làm
2. **Gọi công cụ** (Act) để lấy thêm thông tin
3. **Quan sát** kết quả trả về
4. Lặp lại cho đến khi có đủ thông tin để trả lời

Thay vì "hỏi LLM một câu, nhận một câu trả lời", ReACT cho phép LLM tự chủ đi tìm dữ liệu trước khi viết.

### 9.2 Triết lý của báo cáo

Báo cáo được định vị là **"Báo cáo Dự báo Tương lai"** — không phải phân tích dữ liệu khô khan, mà là: *"Trong thế giới mô phỏng, điều này đã xảy ra — đây là dự báo về những gì có thể xảy ra trong tương lai thực."*

Các Agent trong mô phỏng được xem là **đại diện cho hành vi con người trong tương lai**.

### 9.3 Luồng tổng quát

```
generate_report(simulation_id, graph_id, simulation_requirement)
        │
        ├── Phase A: Planning (Lên dàn ý)
        │       ├── Query Zep → lấy statistics (total nodes, edges, entity types)
        │       ├── Lấy sample facts từ graph
        │       ├── LLM (PLAN_SYSTEM_PROMPT + context) → JSON outline
        │       └── → ReportOutline {title, summary, sections: [2-5 sections]}
        │
        ├── Phase B: Generating (Viết từng section)
        │       └── Với mỗi section:
        │               └── ReACT loop (tối đa 5 lần tool call, tối thiểu 3):
        │                       ├── LLM suy nghĩ → gọi tool → nhận kết quả → suy nghĩ tiếp
        │                       └── Khi đủ data → "Final Answer: [nội dung section]"
        │
        └── Phase C: Assembly (Ghép báo cáo)
                ├── Ghép tất cả sections thành Markdown
                └── Lưu report.json + report.md
```

### 9.4 Phase A — Lên dàn ý

**Input vào LLM:**
```
PLAN_SYSTEM_PROMPT:
  "Bạn là chuyên gia viết Báo cáo Dự báo Tương lai, với góc nhìn 
   của Chúa về thế giới mô phỏng..."

PLAN_USER_PROMPT:
  "Biến số tiêm vào: {simulation_requirement}
   Quy mô: {total_nodes} nodes, {total_edges} edges
   Phân phối loại entity: {entity_types}
   Sample facts: {related_facts_json}"
```

**Output:**
```json
{
  "title": "Dự báo Làn sóng Phản đối Học phí Tăng tại Đại học X",
  "summary": "Mô phỏng cho thấy quyết định tăng 20% học phí sẽ kích hoạt làn sóng biểu tình trực tuyến trong vòng 48 giờ, dẫn đầu bởi sinh viên năm 3-4",
  "sections": [
    {"title": "Sự bùng nổ ban đầu trên mạng xã hội", "description": "Phân tích..."},
    {"title": "Phân cực dư luận: Ủng hộ vs Phản đối", "description": "..."},
    {"title": "Phản ứng của các bên liên quan", "description": "..."},
    {"title": "Dự báo xu hướng và rủi ro", "description": "..."}
  ]
}
```

### 9.5 Phase B — Viết từng Section (ReACT)

Với mỗi section, một vòng hội thoại mới bắt đầu:

**System Prompt** cho LLM bao gồm:
- Tiêu đề và tóm tắt báo cáo
- Yêu cầu mô phỏng
- Tiêu đề section đang viết
- Mô tả 4 công cụ có sẵn
- Luật: phải gọi tool 3-5 lần, không dùng heading (#), dịch mọi content sang tiếng Việt

**4 công cụ khả dụng:**

| Tool | Mô tả | Dùng khi |
|---|---|---|
| `insight_forge(query)` | Tự chia query thành sub-questions, search Zep đa chiều (facts + entities + relationships) | Phân tích sâu một chủ đề phức tạp |
| `panorama_search(query)` | Lấy toàn cảnh evolution của event, phân biệt facts hiện tại vs lịch sử | Hiểu timeline, diễn biến sự kiện |
| `quick_search(query)` | Search đơn giản, nhanh | Xác minh một thông tin cụ thể |
| `interview_agents(topic, agent_types, question)` | Phỏng vấn thực Agent đang chạy qua IPC | Cần góc nhìn first-person từ nhân vật |

**Ví dụ vòng ReACT:**

```
LLM lần 1:
  [Suy nghĩ] Tôi cần hiểu sinh viên đã phản ứng như thế nào...
  <tool_call>
  {"name": "insight_forge", "parameters": {"query": "phản ứng của sinh viên khi học phí tăng"}}
  </tool_call>

[Hệ thống inject kết quả tool]
  Observation: "Facts: Trần Văn An đăng status phản đối lúc 20:15. 
  Nhóm sinh viên tự phát tạo hashtag #HọcPhíTăng lúc 21:00..."

LLM lần 2:
  [Suy nghĩ] Tốt, cần thêm góc nhìn từ truyền thông...
  <tool_call>
  {"name": "interview_agents", "parameters": {
    "topic": "học phí tăng",
    "agent_types": ["MediaOutlet"],
    "question": "Bạn đưa tin về vụ tăng học phí này như thế nào?"
  }}
  </tool_call>

[Kết quả interview thực từ OASIS qua IPC]
  Observation: "VnExpress_reporter_291: Chúng tôi đã đăng bài ngay khi nhận được 
  thông cáo chính thức, thu hút 50,000 lượt xem trong 2 giờ đầu..."

LLM lần 3:
  <tool_call>{"name": "panorama_search", ...}</tool_call>

LLM lần 4:
  <tool_call>{"name": "quick_search", ...}</tool_call>

LLM lần 5 (khi đã đủ data):
  Final Answer: 
  Trong 24 giờ đầu sau thông báo, mạng xã hội đã chứng kiến một làn sóng phản ứng 
  chưa từng có...

  **Giai đoạn bùng nổ (Giờ 0-4)**

  Ngay khi thông báo được đăng tải, các tài khoản truyền thông lớn nhanh chóng 
  tiếp nhận và khuếch đại:

  > "Trần Văn An sẽ nói: Không chịu nổi rồi! Học phí tăng 20% mà lương bố mẹ 
  mình có tăng đâu... #HọcPhíTăng"

  Phản ứng này phản ánh tâm lý chung của nhóm sinh viên có hoàn cảnh khó khăn...
```

**Quy tắc định dạng nghiêm ngặt:**
- ❌ Không dùng `#`, `##`, `###` (heading)
- ✅ Dùng `**bold**` thay thế
- ✅ Quote agent speech bằng `>` format
- ✅ Dịch mọi content tiếng Anh/tiếng Trung sang tiếng Việt
- ❌ Không fabricate thông tin không có trong simulation data

### 9.6 Logging chi tiết

Mọi bước trong quá trình tạo report được ghi vào `agent_log.jsonl`:

```
uploads/reports/{report_id}/
├── agent_log.jsonl     ← JSONL, mỗi dòng là một event (tool_call, llm_response, section_complete...)
├── console_log.txt     ← Log dạng console text (INFO/WARNING level)
├── report.json         ← Full report object
└── report.md           ← Nội dung Markdown
```

**Ví dụ nội dung `agent_log.jsonl`:**
```json
{"timestamp": "2026-05-04T16:00:00", "action": "planning_complete", "stage": "planning", "details": {"outline": {...}}}
{"timestamp": "2026-05-04T16:01:00", "action": "section_start", "stage": "generating", "section_title": "Sự bùng nổ ban đầu"}
{"timestamp": "2026-05-04T16:01:05", "action": "tool_call", "details": {"tool_name": "insight_forge", "parameters": {...}}}
{"timestamp": "2026-05-04T16:01:10", "action": "tool_result", "details": {"tool_name": "insight_forge", "result": "...(full)"}}
{"timestamp": "2026-05-04T16:02:00", "action": "section_complete", "section_title": "Sự bùng nổ ban đầu", "details": {"content": "...(full)"}}
{"timestamp": "2026-05-04T16:05:00", "action": "report_complete", "details": {"total_sections": 4, "total_time_seconds": 300.5}}
```

Frontend lắng nghe log này để hiển thị tiến độ real-time và nội dung từng section khi hoàn thành.

---

## 10. Cơ chế Fallback toàn hệ thống

### 10.1 Bảng tổng hợp

| Giai đoạn | Thành phần | Lỗi | Fallback | Severity |
|---|---|---|---|---|
| 2A | ZepEntityReader | API lỗi | Retry 3 lần, backoff 2s→4s→8s | Tiếp tục |
| 2A | ZepEntityReader | 0 entity sau lọc | **Dừng pipeline**, status=FAILED | **Nghiêm trọng** |
| 2B | Zep Vector Search | Timeout / lỗi | Bỏ qua, context rỗng, tiếp tục | Nhẹ |
| 2B | LLM Profile Gen | JSON lỗi | `_fix_truncated_json()` → `_try_fix_json()` | Tự phục hồi |
| 2B | LLM Profile Gen | 3 lần fail | `_generate_profile_rule_based()` | Degraded |
| 2B | ThreadPoolExecutor | Exception 1 entity | Dùng fallback profile, tiếp tục | Nhẹ |
| 2C | LLM Time Config | Fail | Hardcoded defaults (72h, 60min/round) | Degraded |
| 2C | LLM Event Config | Fail | Empty hot_topics, no initial_posts | Degraded |
| 2C | LLM Agent Config | 1 agent thiếu | `_generate_agent_config_by_rule()` | Nhẹ |
| 2C | poster_type match | Không khớp | Agent có influence_weight cao nhất | Nhẹ |
| 2C | LLM JSON | Cắt ngang | `_fix_truncated_json()` | Tự phục hồi |
| 3 | subprocess | exit_code != 0 | RunnerStatus=FAILED, đọc log | Nghiêm trọng |
| 3 | SIGTERM | Timeout 10s | SIGKILL (Unix) / taskkill /F (Win) | Forced |
| 3 | IPC Interview | Environment chết | ValueError ngay, không wait | Nhẹ |
| 3 | IPC Interview | Timeout 60s | TimeoutError trả về caller | Nhẹ |
| 4 | Zep tool call | Lỗi | Log warning, tiếp tục ReACT | Nhẹ |
| 4 | Interview tool | Env không alive | Trả về error message, tiếp tục | Nhẹ |

### 10.2 Mức độ ảnh hưởng

**Scenario 1 — LLM hoàn toàn không khả dụng:**
- Profile: Tất cả dùng rule-based → Profiles cơ bản nhưng vẫn chạy được
- Config: Hardcoded defaults → Mô phỏng với cài đặt chuẩn thay vì tùy chỉnh
- Report: Không thể tạo (phụ thuộc LLM hoàn toàn)

**Scenario 2 — Zep không khả dụng:**
- Nếu không fetch được entity → Pipeline dừng ở 2A
- Nếu Vector Search fail → Profile thiếu context nhưng vẫn tạo được

**Scenario 3 — OASIS subprocess crash:**
- RunnerStatus = FAILED
- Log lỗi được lưu vào simulation.log
- Người dùng có thể cleanup rồi chạy lại

---

## 11. Cấu trúc file và thư mục

### 11.1 Thư mục Simulation

```
uploads/simulations/{simulation_id}/
│
├── state.json                  ← Trạng thái lifecycle (CREATED/PREPARING/READY/RUNNING/...)
├── run_state.json              ← Trạng thái runtime (round hiện tại, actions count, ...)
├── simulation_config.json      ← Config đầy đủ (time, agents, events, platforms)
│
├── reddit_profiles.json        ← Profile agents format Reddit
├── twitter_profiles.csv        ← Profile agents format Twitter
│
├── simulation.log              ← stdout + stderr của OASIS subprocess
├── env_status.json             ← Trạng thái IPC environment (alive/stopped)
│
├── twitter/
│   └── actions.jsonl           ← Log hành động Twitter (từng dòng = 1 action)
│
├── reddit/
│   └── actions.jsonl           ← Log hành động Reddit
│
├── ipc_commands/               ← Flask ghi lệnh vào đây
│   └── {uuid}.json
│
├── ipc_responses/              ← OASIS ghi response vào đây
│   └── {uuid}.json
│
├── twitter_simulation.db       ← SQLite database của OASIS Twitter
└── reddit_simulation.db        ← SQLite database của OASIS Reddit
```

### 11.2 Thư mục Report

```
uploads/reports/{report_id}/
│
├── report.json                 ← Full report object (JSON)
├── report.md                   ← Nội dung Markdown
│
├── agent_log.jsonl             ← Log chi tiết từng bước ReACT (JSONL)
└── console_log.txt             ← Log console text (INFO/WARNING)
```

---

## 12. Luồng dữ liệu end-to-end

### 12.1 Sơ đồ tổng hợp

```
[USER]
  │ Upload tài liệu + yêu cầu mô phỏng
  ↓
[TextProcessor]
  │ document_text (cleaned string)
  ↓
[Zep Graph Builder] ← (pipeline riêng, chạy trước)
  │ Graph {Nodes + Edges}
  ↓
[ZepEntityReader.filter_defined_entities()]
  │ List[EntityNode] — 47 entities
  │ (mỗi entity: uuid, name, labels, summary, related_edges, related_nodes)
  ↓
[OasisProfileGenerator.generate_profiles_from_entities()]
  │ ← Zep Vector Search (parallel, cho từng entity)
  │ ← LLM (parallel, 3 luồng, retry 3 lần / rule-based fallback)
  │ List[OasisAgentProfile] — 47 profiles
  │ → reddit_profiles.json (realtime save)
  │ → twitter_profiles.csv (realtime save)
  ↓
[SimulationConfigGenerator.generate_config()]
  │ ← LLM (4 bước tuần tự: time → event → agents×3 batch → platform)
  │ SimulationParameters
  │ → simulation_config.json
  ↓
[SimulationRunner.start_simulation()]
  │ subprocess.Popen(run_parallel_simulation.py --config ...)
  │
  │   [OASIS Script — Subprocess]
  │   ├── Read: reddit_profiles.json + twitter_profiles.csv
  │   ├── Read: simulation_config.json
  │   ├── Init: Twitter Environment + Reddit Environment
  │   └── Loop 72 rounds:
  │           └── N agents active per round
  │                   └── LLM(persona + timeline) → action → log
  │   → twitter/actions.jsonl
  │   → reddit/actions.jsonl
  │
  │   [Monitor Thread — Flask]
  │   Đọc actions.jsonl mỗi 2s → cập nhật run_state.json
  ↓
[ReportAgent.generate_report()]
  │ ← Zep Graph (query statistics + facts)
  │ ← LLM (Planning: 1 call)
  │ ← LLM ReACT (Per section: 3-5 tool calls + 1 final answer)
  │       ← ZepTools (insight_forge / panorama_search / quick_search)
  │       ← SimulationRunner.interview_agents_batch() (qua IPC nếu env alive)
  │ → report.md
  │ → agent_log.jsonl
  ↓
[USER nhận báo cáo]
```

### 12.2 Trạng thái lifecycle của SimulationState

```
CREATED
   ↓ (prepare_simulation bắt đầu)
PREPARING
   ↓ (tất cả 3 phase chuẩn bị xong)
READY
   ↓ (start_simulation được gọi)
RUNNING  ←→  PAUSED (tính năng tương lai)
   ↓ (mô phỏng tự nhiên kết thúc)
COMPLETED
   ↓ (hoặc)
FAILED    ← (bất kỳ lỗi nghiêm trọng nào)
STOPPED   ← (người dùng chủ động dừng)
```

### 12.3 Trạng thái lifecycle của RunnerStatus

```
IDLE
  ↓ (start_simulation)
STARTING
  ↓ (subprocess bắt đầu)
RUNNING
  ↓ (simulation_end event trong actions.jsonl)
COMPLETED

Hoặc:
RUNNING → STOPPING → STOPPED  (người dùng stop)
RUNNING → FAILED               (subprocess crash)
```

---

*Báo cáo này được tạo bởi Claude Sonnet 4.6 dựa trên phân tích mã nguồn MiroFish.*  
*Cập nhật lần cuối: 2026-05-04*
