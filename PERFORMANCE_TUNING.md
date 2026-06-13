# Performance Tuning — Tăng tốc pipeline khi có resource lớn

Tài liệu này liệt kê các **param có thể nâng lên để chạy nhanh hơn** khi bạn có máy/GPU/LLM-server mạnh hơn.
Mỗi mục ghi rõ: **file + dòng**, giá trị hiện tại, giá trị đề xuất, và **giúp nhanh ở bước nào**.

> ⚠️ **Nút thắt thật không nằm ở code mà ở 2 server LLM/embedding.**
> Toàn bộ semaphore/concurrency bên dưới bị giới hạn bởi số request đồng thời mà
> - LLM server (`LLM_BASE_URL`, vd `localhost:8027`) và
> - embedding server (`EMBEDDING_BASE_URL`, vd `localhost:8026`)
>
> chịu được. Tăng các con số vượt quá khả năng 2 server này sẽ gây **timeout / 429 / 400**, KHÔNG nhanh hơn.
> Quy tắc: nâng dần, theo dõi log, dừng khi bắt đầu thấy lỗi.

---

## ✅ ĐÃ ÁP DỤNG — cấu hình cho 2 model hiện tại (cập nhật mới nhất)

Server hiện tại:
- **LLM:** `Qwen/Qwen3.6-27B` @ `localhost:8027` — `max_model_len = 262144` (256K)
- **Embedding:** `Qwen/Qwen3-Embedding-4B` @ `localhost:8026` — `max_model_len = 40960` (40K)

> ⚠️ **Đã fix tên model:** `.env` trước ghi `Qwen/Qwen3.6-27B-FP8` (sai → gây 404). Server chỉ phục vụ `Qwen/Qwen3.6-27B`.

Các giá trị đã set (tận dụng cửa sổ context lớn 256K):

| Param | File:dòng | Cũ → **Mới** | Lý do |
|---|---|---|---|
| `LLM_MODEL_NAME` | [.env:6](.env#L6) | `…-27B-FP8` → **`…-27B`** | Fix 404 (bắt buộc) |
| `SEMAPHORE_LIMIT` | [.env:26](.env#L26) | `10` → **`30`** | Build graph nhanh hơn |
| `CHUNK_TOKEN_SIZE` | [.env:27](.env#L27) | `3000` → **`8000`** | Ít chunk hơn (< embed 40960) |
| `max_tokens` ×2 | [backend/app/utils/llm_client.py:44](backend/app/utils/llm_client.py#L44), [:91](backend/app/utils/llm_client.py#L91) | `16000` → **`32000`** | Output dài hơn |
| `MAX_TEXT_LENGTH_FOR_LLM` | [backend/app/services/ontology_generator.py:291](backend/app/services/ontology_generator.py#L291) | `40000` → **`400000`** | Ontology đọc nhiều text hơn (~100K token) |
| `token_limit` / `message_window_size` | [backend/scripts/run_parallel_simulation.py:1128](backend/scripts/run_parallel_simulation.py#L1128) | `24000`/`25` → **`150000`/`50`** | Agent nhớ nhiều hơn, ít bị cắt |
| `parallel_profile_count` | [backend/app/services/simulation_manager.py:352](backend/app/services/simulation_manager.py#L352) | `3` → **`15`** | Sinh profile song song |
| `parallel_count` (default) | [backend/app/services/oasis_profile_generator.py:1198](backend/app/services/oasis_profile_generator.py#L1198) | `5` → **`15`** | (đồng bộ với trên) |
| `semaphore` ×2 (oasis.make) | [backend/scripts/run_parallel_simulation.py:1340](backend/scripts/run_parallel_simulation.py#L1340), [:1535](backend/scripts/run_parallel_simulation.py#L1535) | `8` → **`30`** | Nhiều agent gọi LLM/round |
| `batch_size` (build) | [backend/app/api/graph.py:459](backend/app/api/graph.py#L459) | `3` → **`8`** | Ít round-trip khi nạp chunk |

**Cần làm sau khi sửa:** restart backend để `.env` có hiệu lực (`cd backend && FLASK_PORT=5002 uv run python run.py`).

---

## 🎯 TL;DR — Sửa 3 thứ này trước (ăn nhất)

| Ưu tiên | Param | File:dòng | Hiện tại | Đề xuất (máy mạnh) | Tăng tốc bước |
|---|---|---|---|---|---|
| 1 | `SEMAPHORE_LIMIT` | [.env:26](.env#L26) | `10` | `30` | **Build graph** (chậm nhất) |
| 2 | `parallel_profile_count` | [backend/app/services/simulation_manager.py:352](backend/app/services/simulation_manager.py#L352) | `3` | `15` | **Sinh agent profile** |
| 3 | `semaphore` (oasis.make) | [backend/scripts/run_parallel_simulation.py:1340](backend/scripts/run_parallel_simulation.py#L1340), [:1535](backend/scripts/run_parallel_simulation.py#L1535) | `8` | `30` | **Simulation** (nhiều agent gọi LLM) |

---

## 🟢 Nhóm 1 — Build knowledge graph (bước chậm nhất)

### 1.1 `SEMAPHORE_LIMIT` — ⭐ quan trọng nhất
- **File:** [.env:26](.env#L26) → `SEMAPHORE_LIMIT=10`
- **Là gì:** số thao tác LLM/embedding **đồng thời** mà `graphiti_core` chạy khi build graph.
  (Đọc bởi thư viện tại `graphiti_core/helpers.py`, default lib = 20.)
- **Đề xuất:** `20`–`50` (giới hạn bởi sức chịu của LLM + embedding server).
- **Giúp gì:** Build graph là bước tốn thời gian nhất (extract entity + embedding cho từng chunk). Đây là đòn bẩy lớn nhất.

### 1.2 `USE_PARALLEL_RUNTIME`
- **File:** [.env:28](.env#L28) → `USE_PARALLEL_RUNTIME=false`
- **Là gì:** bật Neo4j parallel runtime cho các Cypher query.
- **Đề xuất:** `true` — **CHỈ khi dùng Neo4j Enterprise** (Community Edition không hỗ trợ, bật vô tác dụng).
- **Giúp gì:** truy vấn graph nhanh hơn khi Neo4j có nhiều core.

### 1.3 `CHUNK_TOKEN_SIZE`
- **File:** [.env:27](.env#L27) → `CHUNK_TOKEN_SIZE=3000`
- **Là gì:** kích thước mỗi chunk (token) khi graphiti tự chia text.
- **Đề xuất:** `5000`–`8000` — **CHỈ khi LLM/embedding có cửa sổ context lớn** (model hiện tại 32K nên cẩn thận).
- **Giúp gì:** chunk to hơn → ít chunk hơn → ít vòng LLM call hơn khi build. (Đánh đổi: mỗi call nặng hơn.)

### 1.4 `batch_size` khi build (hardcode — phải sửa code)
- **File:** [backend/app/api/graph.py:459](backend/app/api/graph.py#L459) → `batch_size=3`
  (default cũng ở [backend/app/services/graph_builder.py:67](backend/app/services/graph_builder.py#L67) và [:294](backend/app/services/graph_builder.py#L294))
- **Là gì:** số chunk gửi đi mỗi đợt. Endpoint `build` KHÔNG nhận param này từ request → phải sửa trực tiếp.
- **Đề xuất:** `5`–`10`.
- **Giúp gì:** giảm số lần round-trip khi nạp chunk vào graph.

---

## 🟡 Nhóm 2 — Simulation (bước chậm thứ 2)

### 2.1 `parallel_profile_count` — sinh agent profile song song
- **File:** [backend/app/services/simulation_manager.py:352](backend/app/services/simulation_manager.py#L352) → `parallel_profile_count: int = 3`
  (worker thực thi ở [backend/app/services/oasis_profile_generator.py:1198](backend/app/services/oasis_profile_generator.py#L1198) → `parallel_count: int = 5`)
- **Là gì:** số thread sinh profile đồng thời, mỗi profile = 1 LLM call.
- **Đề xuất:** `10`–`20`.
- **Giúp gì:** với 50 profile: 3 thread ≈ 100–250s; 15 thread nhanh ~5×.

### 2.2 `semaphore` trong `oasis.make()` — LLM call đồng thời mỗi round
- **File:**
  - [backend/scripts/run_parallel_simulation.py:1340](backend/scripts/run_parallel_simulation.py#L1340) (Twitter) → `semaphore=8`
  - [backend/scripts/run_parallel_simulation.py:1535](backend/scripts/run_parallel_simulation.py#L1535) (Reddit) → `semaphore=8`
  - [backend/scripts/run_twitter_simulation.py:597](backend/scripts/run_twitter_simulation.py#L597) → `semaphore=30`
  - [backend/scripts/run_reddit_simulation.py:582](backend/scripts/run_reddit_simulation.py#L582) → `semaphore=30`
- **Là gì:** giới hạn số agent gọi LLM cùng lúc trong 1 round.
- **Đề xuất:** `20`–`40` (đã hạ xuống 8 cho server nhỏ; server mạnh thì nới ra).
- **Giúp gì:** mỗi round simulation chạy nhanh hơn khi nhiều agent xử lý song song.

---

## 🔵 Nhóm 3 — Token / context (chỉ nâng SAU KHI đổi sang model cửa sổ lớn)

> ⚠️ Mấy param này đã được **hạ xuống** để vừa model 32K hiện tại (`max_total_tokens=32768`).
> Chúng **không tăng tốc trực tiếp**, mà tăng *throughput mỗi call* → ít vòng lặp/ít bị cắt context.
> **Nâng lên sẽ gây lỗi HTTP 400 nếu model vẫn là 32K.** Chỉ nâng khi đã trỏ sang model/endpoint cửa sổ lớn (vd 128K).

| Param | File:dòng | Hiện tại | Khi model lớn | Vai trò |
|---|---|---|---|---|
| `max_tokens` (chat) | [backend/app/utils/llm_client.py:44](backend/app/utils/llm_client.py#L44) | `16000` | `32000`–`50000` | output tối đa mỗi call |
| `max_tokens` (chat_json) | [backend/app/utils/llm_client.py:91](backend/app/utils/llm_client.py#L91) | `16000` | `32000`–`50000` | output JSON (ontology) |
| `MAX_TEXT_LENGTH_FOR_LLM` | [backend/app/services/ontology_generator.py:291](backend/app/services/ontology_generator.py#L291) | `40000` | `100000`+ | số ký tự input cho ontology (hiện cắt bớt) |
| `token_limit` (agent memory) | [backend/scripts/run_parallel_simulation.py:1128](backend/scripts/run_parallel_simulation.py#L1128) | `24000` | `100000`+ | context history mỗi agent giữ lại |
| `message_window_size` | [backend/scripts/run_parallel_simulation.py:1128](backend/scripts/run_parallel_simulation.py#L1128) | `25` | `50`+ | số message agent nhớ |

---

## ⚙️ Nhóm 4 — Throughput-vs-độ-sâu (đánh đổi chất lượng/tốc độ, không phải resource)

Mấy cái này không cần máy mạnh — chúng đổi **độ sâu xử lý** lấy **tốc độ**. Giảm xuống = nhanh hơn nhưng kết quả nông hơn.

| Param | File:dòng | Hiện tại | Để chạy nhanh |
|---|---|---|---|
| `OASIS_DEFAULT_MAX_ROUNDS` | [backend/app/config.py:55](backend/app/config.py#L55) (env `OASIS_DEFAULT_MAX_ROUNDS`) | `10` | giảm còn `3`–`5` khi test nhanh |
| `REPORT_AGENT_MAX_TOOL_CALLS` | [backend/app/config.py:69](backend/app/config.py#L69) | `5` | giảm → report nhanh hơn, ít truy vấn graph hơn |
| `REPORT_AGENT_MAX_REFLECTION_ROUNDS` | [backend/app/config.py:70](backend/app/config.py#L70) | `2` | giảm còn `1` → report nhanh hơn |

---

## 📌 Lưu ý vận hành

1. **Sửa `.env` → phải restart backend** (biến môi trường chỉ đọc lúc khởi động; Flask reloader KHÔNG reload `.env`).
   ```bash
   cd backend && FLASK_PORT=5002 uv run python run.py
   ```
2. **Sửa code `.py` → Flask reloader tự nạp lại** (nếu debug mode bật), không cần restart.
3. **Nâng dần, đừng nhảy vọt.** Tăng semaphore → xem log có `429`/`timeout`/`400` không → nếu có thì hạ lại.
4. **Trần trên = sức chịu của LLM + embedding server**, không phải code. Đó mới là nút thắt thật.
