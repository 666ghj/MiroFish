# Full Pipeline Runner

Chạy toàn bộ MiroFish pipeline từ command line, không cần mở UI.

## Files

| File | Vai trò |
|---|---|
| `prepare_input.py` | Đọc config, load & filter articles, ghi combined text ra temp file, in JSON metadata ra stdout |
| `run.sh` | Gọi `prepare_input.py`, khởi động backend nếu cần, rồi gọi tuần tự các API |
| `config_articles.env` | Cấu hình input |


## Cấu hình (`config_articles.env`)

| Tham số | Bắt buộc | Mô tả |
|---|---|---|
| `article_path` | Có | Đường dẫn thư mục chứa `articles.jsonl` và thư mục `news/` |
| `full_content` | Không | `True` = giữ toàn bộ markdown; `False` (mặc định) = chỉ lấy body bài viết, bỏ YAML frontmatter |
| `start_time` | Không | Lọc bài viết từ ngày (`YYYY-MM-DD`), để trống = không lọc |
| `end_time` | Không | Lọc bài viết đến ngày (`YYYY-MM-DD`), để trống = không lọc |
| `simulation_requirement` | Không | Mô tả yêu cầu phân tích/dự báo gửi cho LLM |
| `project_name` | Không | Tên project |

---

## Cách 1 — Chạy toàn bộ pipeline 1 lệnh (khuyến nghị)

**Không cần mở terminal riêng cho backend.** `run.sh` tự kiểm tra và khởi động Flask nếu chưa chạy.

Chạy 7 bước tự động: ontology → graph → create sim → prepare sim → start sim → chờ hoàn thành → generate report.

```bash
# Từ project root
cd /home/anman/intern/quynhht/MiroFish
bash test_code_backend/full_pipeline/run.sh

# Hoặc chỉ định config khác
bash test_code_backend/full_pipeline/run.sh path/to/config.env
```

Log in ra terminal từng bước. Cuối cùng in ra `project_id`, `graph_id`, `simulation_id`, `report_id`.

> Backend được tự động khởi động trong background — **không cần mở terminal riêng**. Log đầy đủ nằm ở `backend/logs/YYYY-MM-DD.log`.

Muốn kill port
```bash
kill $(lsof -ti :5001)
```
---

## Cách 2 — Chạy từng bước thủ công

Khi cần debug hoặc muốn kiểm tra kết quả từng bước.

### Bước 0: Khởi động Flask backend (port 5001)

Mở **terminal riêng**, giữ nguyên trong suốt quá trình:

```bash
cd /home/anman/intern/MiroFish
FLASK_PORT=5001 npm run backend  
# hoặc: python backend/run.py
```

Kiểm tra backend đã sẵn sàng:
```bash
curl http://localhost:5001/health
# → {"status": "ok", "service": "MiroFish Backend"}
```

### Bước 1: Chuẩn bị input (Python)

Chạy trong **terminal khác**:

```bash
cd /home/anman/intern/MiroFish
python3 test_code_backend/full_pipeline/prepare_input.py \
    test_code_backend/full_pipeline/config_articles.env
```

Output là JSON, ví dụ:
```json
{
  "combined_file": "/tmp/mirofish_articles_abc123.md",
  "article_count": 42,
  "project_name": "Oil Market Sentiment Pipeline",
  "simulation_requirement": "Analyze how ...",
  "start_time": null,
  "end_time": null
}
```

Lưu lại đường dẫn `combined_file` để dùng ở bước tiếp theo.

---

### Bước 2: Generate ontology → lấy `project_id`

```bash
COMBINED_FILE="/home/anman/intern/MiroFish/test_code_backend/full_pipeline/data/articles_combined.md"  

COMBINED_FILE="/home/anman/intern/MiroFish/data/news/2026-02/2026-02-03_oil-prices-add-gains-after-report-says_0178c4.md"  

curl -s http://localhost:5001/api/graph/ontology/generate \
  -F "files=@${COMBINED_FILE};filename=articles.md" \
  -F "simulation_requirement=Analyze how these oil and financial market news articles affect investor sentiment and market dynamics. Predict how different market participants (traders, analysts, retail investors) will react and what the overall price trend will be." \
  -F "project_name=Oil Market Pipeline" \
  | jq '{project_id: .data.project_id, entity_types: [.data.ontology.entity_types[].name]}'
```

Lưu lại `project_id`.

---

### Bước 3: Build knowledge graph → lấy `task_id`

```bash
PROJECT_ID="proj_xxxxxxxxxxxx"  

curl -s http://localhost:5001/api/graph/build \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\"}" \
  | jq '{task_id: .data.task_id}'
```

Poll tiến độ build (chạy lặp lại đến khi `status=completed`):

```bash
TASK_ID="task_xxxxxxxxxxxx"  

curl -s http://localhost:5001/api/graph/task/$TASK_ID \
  | jq '{status: .data.status, progress: .data.progress, graph_id: .data.result.graph_id}'
```

Khi `status=completed`, lưu lại `graph_id`.

---

### Bước 4: Tạo simulation → lấy `simulation_id`

```bash
PROJECT_ID="proj_xxxxxxxxxxxx"

curl -s http://localhost:5001/api/simulation/create \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"enable_twitter\": true, \"enable_reddit\": true}" \
  | jq '{simulation_id: .data.simulation_id}'
```

---

### Bước 5: Prepare simulation (sinh agent profiles + config)

```bash
SIM_ID="sim_xxxxxxxxxxxx"

curl -s http://localhost:5001/api/simulation/prepare \
  -H "Content-Type: application/json" \
  -d "{\"simulation_id\": \"$SIM_ID\", \"use_llm_for_profiles\": true, \"parallel_profile_count\": 5}" \
  | jq '{task_id: .data.task_id, status: .data.status}'
```

Poll tiến độ (bước này lâu nhất, ~5–15 phút tùy số agents):

```bash
TASK_ID="task_xxxxxxxxxxxx"

curl -s http://localhost:5001/api/simulation/prepare/status \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$TASK_ID\", \"simulation_id\": \"$SIM_ID\"}" \
  | jq '{status: .data.status, progress: .data.progress, message: .data.message}'
```

---

### Bước 6: Start simulation

```bash
SIM_ID="sim_xxxxxxxxxxxx"

curl -s http://localhost:5001/api/simulation/start \
  -H "Content-Type: application/json" \
  -d "{\"simulation_id\": \"$SIM_ID\", \"platform\": \"parallel\", \"force\": true}" \
  | jq '{runner_status: .data.runner_status, total_rounds: .data.total_rounds}'
```

thêm cờ `\"force\": true` nếu muốn chạy simulation của SIM_ID đó mà không phải chạy lại prepare simualtion

---

### Bước 7: Theo dõi simulation đến khi hoàn thành

Chạy lệnh sau để tự động poll mỗi 30 giây, tự thoát khi simulation kết thúc:

```bash
SIM_ID="sim_xxxxxxxxxxxx"


while true; do
  RESP=$(curl -s http://localhost:5001/api/simulation/$SIM_ID/run-status)
  RS=$(echo "$RESP" | jq -r '.data.runner_status')
  CR=$(echo "$RESP" | jq -r '.data.current_round')
  TR=$(echo "$RESP" | jq -r '.data.total_rounds')
  echo "[$(date '+%H:%M:%S')] $RS  round=$CR/$TR"
  [[ "$RS" == "completed" || "$RS" == "stopped" || "$RS" == "failed" ]] && break
  sleep 30
done
```

Hoặc kiểm tra thủ công một lần:

```bash
# Trạng thái tổng quan (round hiện tại, % tiến độ)
curl -s http://localhost:5001/api/simulation/$SIM_ID/run-status \
  | jq '{runner_status: .data.runner_status, current_round: .data.current_round, total_rounds: .data.total_rounds}'

# Hành động của agents (real-time)
curl -s "http://localhost:5001/api/simulation/$SIM_ID/actions?limit=20" | jq .
```

Dừng simulation
```bash
SIM_ID="sim_0d2a9fa9936a"

curl -s http://localhost:5001/api/simulation/stop \
  -H "Content-Type: application/json" \
  -d "{\"simulation_id\": \"$SIM_ID\"}" \
  | jq '{success: .success, runner_status: .data.runner_status}'
```

---

### Bước 8: Generate report

```bash
SIM_ID="sim_xxxxxxxxxxxx"

# 1. Bắt đầu generate → lấy task_id và report_id
RESP=$(curl -s http://localhost:5001/api/report/generate \
  -H "Content-Type: application/json" \
  -d "{\"simulation_id\": \"$SIM_ID\"}")
TASK_ID=$(echo "$RESP"   | jq -r '.data.task_id')
REPORT_ID=$(echo "$RESP" | jq -r '.data.report_id')
echo "task_id=$TASK_ID  report_id=$REPORT_ID"

# 2. Poll đến khi completed (chạy lặp lại, ~5–15 phút)
while true; do
  R=$(curl -s http://localhost:5001/api/report/generate/status \
    -H "Content-Type: application/json" \
    -d "{\"task_id\": \"$TASK_ID\"}")
  ST=$(echo "$R" | jq -r '.data.status')
  PG=$(echo "$R" | jq -r '.data.progress')
  echo "$ST ${PG}%"
  [[ "$ST" == "completed" ]] && break
  [[ "$ST" == "failed"    ]] && { echo "FAILED"; break; }
  sleep 15
done

# 3. Download file Markdown
curl -s http://localhost:5001/api/report/$REPORT_ID/download -o report.md
echo "Saved to report.md"
```

Nếu sim đã có report rồi mà muốn chạy lại thì dùng như sau

```bash
SIM_ID="sim_xxxxxxxxxxxx"

# 1. Bắt đầu generate → lấy task_id và report_id
RESP=$(curl -s http://localhost:5001/api/report/generate \
  -H "Content-Type: application/json" \
  -d "{\"simulation_id\": \"$SIM_ID\", \"force_regenerate\": true}")
TASK_ID=$(echo "$RESP"   | jq -r '.data.task_id')
REPORT_ID=$(echo "$RESP" | jq -r '.data.report_id')
echo "task_id=$TASK_ID  report_id=$REPORT_ID"

# 2. Poll đến khi completed (chạy lặp lại, ~5–15 phút)
while true; do
  R=$(curl -s http://localhost:5001/api/report/generate/status \
    -H "Content-Type: application/json" \
    -d "{\"task_id\": \"$TASK_ID\"}")
  ST=$(echo "$R" | jq -r '.data.status')
  PG=$(echo "$R" | jq -r '.data.progress')
  echo "$ST ${PG}%"
  [[ "$ST" == "completed" ]] && break
  [[ "$ST" == "failed"    ]] && { echo "FAILED"; break; }
  sleep 15
done

# 3. Download file Markdown
curl -s http://localhost:5001/api/report/$REPORT_ID/download -o report.md
echo "Saved to report.md"
```

---

## Output files

| Loại | Đường dẫn |
|---|---|
| Project metadata + extracted text | `backend/uploads/projects/<project_id>/` |
| Agent profiles (Reddit) | `backend/uploads/simulations/<sim_id>/reddit_profiles.json` |
| Agent profiles (Twitter) | `backend/uploads/simulations/<sim_id>/twitter_profiles.csv` |
| Simulation config (LLM-generated) | `backend/uploads/simulations/<sim_id>/simulation_config.json` |
| Run state & action log | `backend/uploads/simulations/<sim_id>/run_state.json` |
| Report | `backend/uploads/reports/<report_id>/` |
