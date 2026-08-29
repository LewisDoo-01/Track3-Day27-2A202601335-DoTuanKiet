# Day 27 — HITL Chatbot: quy trình Human-in-the-Loop chuẩn production

Chatbot hỗ trợ nội bộ (HR/IT helpdesk) minh hoạ **vòng đời đầy đủ của một request
đi qua Human-in-the-Loop**: bot trả lời nháp → chính sách rủi ro quyết định tự
động hay chuyển người → hàng đợi duyệt có state machine + SLA → người duyệt
approve/edit/reject → nhật ký audit → số liệu vận hành → dataset phản hồi.

Mục tiêu là **cho thấy quy trình vận hành**, không phải làm một chatbot thông minh.
Vì vậy retrieval (TF-IDF) và FakeLLM được cố tình giữ đơn giản; phần "production"
nằm ở cách các service ghép với nhau, ở state machine, idempotency, SLA và audit.

## Sơ đồ tổng quan

```
                                   +--------------------+
User --"cau hoi"-->  Orchestrator  |  handle_message()  |
                                   +---------+----------+
                                             v
                     1. retrieval_service.search()   -> docs + score + citations
                                             v
                     2. llm_service.draft()          -> answer + confidence
                                             v
                     3. risk_policy_service.decide() -> AUTO | ESCALATE (+ reasons)
                              |                             |
                        AUTO  |                             |  ESCALATE
                              v                             v
                   +------------------+        +-----------------------------+
                   | tra loi ngay     |        | review_queue.enqueue()      |
                   | audit: auto_*    |        | bot: "dang cho chuyen vien"  |
                   +--------+---------+        +--------------+--------------+
                            |                                 v
                            |                    +-----------------------------+
                            |                    |  NGUOI DUYET                 |
                            |                    |  FastAPI /reviews  hoac      |
                            |                    |  reviewer_cli.py            |
                            |                    |  claim -> xem context ->    |
                            |                    |  approve / edit / reject    |
                            |                    +--------------+--------------+
                            |                                   v
                            |             resolve(): tra ket qua + feedback_store.record()
                            |             (hoac qua han -> sweep_sla() -> cau safe-default)
                            v                                   v
                   +----------------------------------------------------------+
                   | audit_service   - JSON append-only, 1 trace_id / hoi thoai|
                   | metrics_service - doc audit -> so lieu -> report          |
                   +----------------------------------------------------------+
```

State machine của một review task:

```
   enqueue()          claim()             resolve(approve/edit/reject)
 ----------> PENDING --------> IN_REVIEW --------------------------------> RESOLVED
                 |                                                            ^
                 +------------- expire_stale()  (qua SLA) --------------------+
```

## Cấu trúc file

| File | Nội dung | Test |
|------|----------|------|
| `hitl_chatbot/config.py` | Toàn bộ ngưỡng & từ khoá nhạy cảm, nạp từ `.env` | — |
| `hitl_chatbot/models.py` | Dataclass dùng chung + đồng hồ giả `set_clock()` | — |
| `hitl_chatbot/json_store.py` | Kho JSON ghi atomic (thay cho DB, đủ cho lab) | — |
| `hitl_chatbot/retrieval_service.py` | TF-IDF + cosine thuần Python trên KB markdown | `test_retrieval_service.py` |
| `hitl_chatbot/llm_service.py` | `FakeLLM` (deterministic) + `OpenRouterLLM` (Gemini 2.5) | `test_llm_service.py` |
| `hitl_chatbot/risk_policy_service.py` | **Quyết định AUTO vs ESCALATE** — trái tim HITL | `test_risk_policy_service.py` |
| `hitl_chatbot/review_queue_service.py` | Hàng đợi duyệt: state machine, idempotency, SLA | `test_review_queue_service.py` |
| `hitl_chatbot/feedback_store.py` | Ghi phản hồi người duyệt + edit-distance → dataset | `test_feedback_store.py` |
| `hitl_chatbot/audit_service.py` | Nhật ký append-only, truy vết theo `trace_id` | `test_audit_service.py` |
| `hitl_chatbot/metrics_service.py` | Tổng hợp số liệu vận hành từ audit log | `test_metrics_service.py` |
| `hitl_chatbot/orchestrator.py` | Ghép tất cả thành 1 pipeline | `test_orchestrator.py` (end-to-end) |
| `app.py` | FastAPI: `/chat`, `/reviews`, `/reviews/{id}/claim\|resolve`, `/metrics` | — |
| `reviewer_cli.py` | Dashboard dòng lệnh cho người duyệt (`rich`) | — |
| `scripts/run_simulation.py` | Chạy 25 hội thoại + người duyệt giả lập → sinh audit | — |
| `scripts/generate_report.py` | audit → `reports/metrics.{json,csv}` + `final_report.md` | — |
| `data/kb/*.md` | Knowledge Base (8 tài liệu HR/IT) | — |
| `data/scenarios.jsonl` | 25 câu hỏi gắn nhãn `expected_route` để đo policy | — |

## Các khái niệm HITL được minh hoạ

1. **Confidence-gated autonomy** — bot tự trả lời khi đủ tự tin *và* rủi ro thấp.
2. **Risk-based routing / chốt chặn cứng** — chủ đề nhạy cảm (lương cá nhân, kỷ
   luật, dữ liệu cá nhân, pháp lý) **luôn** qua người, kể cả khi model tự tin 99%.
3. **Review queue + state machine** — `PENDING → IN_REVIEW → RESOLVED`, không cho nhảy cóc.
4. **SLA / timeout fallback** — task chờ quá hạn → tự đóng bằng câu an toàn, không để user chờ vô hạn.
5. **Reviewer actions** — APPROVE / EDIT / REJECT, EDIT và REJECT bắt buộc có lý do.
6. **Audit trail** — mọi bước emit event cùng `trace_id`; số liệu tính lại từ đây.
7. **Feedback loop** — việc người duyệt làm → dataset `(query, context, draft, gold, label)` để eval/fine-tune.
8. **Idempotency** — resolve một task 2 lần không double-effect, không double-log.
9. **Metrics vận hành** — automation rate, escalation rate, review latency P50/P95,
   approve/edit/reject rate, SLA breach rate, phút người tiết kiệm.

## Yêu cầu

- Python 3.10+ (đã test trên 3.13).
- Phần lõi + toàn bộ test chạy **offline**, không cần API key / Docker / Redis.
- Chỉ cần `OPENROUTER_API_KEY` nếu muốn dùng LLM thật (`google/gemini-2.5-flash`).

## Cài đặt

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows;  Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env             # rồi điền OPENROUTER_API_KEY (hoặc để LLM_PROVIDER=fake)
```

`.env` mặc định đặt `LLM_PROVIDER=openrouter` + `OPENROUTER_MODEL=google/gemini-2.5-flash`.
Nếu chưa có key, hệ thống tự lùi về `FakeLLM` và in cảnh báo — vẫn chạy được đầy đủ.

## Chạy

### 1. API server + reviewer console

```bash
uvicorn app:app --reload
# mở http://127.0.0.1:8000/docs

# user hỏi
curl -X POST localhost:8000/chat -H "content-type: application/json" \
     -d '{"user":"an.nguyen","message":"Toi duoc bao nhieu ngay phep nam?"}'

# câu nhạy cảm -> vào hàng đợi
curl -X POST localhost:8000/chat -H "content-type: application/json" \
     -d '{"user":"an.nguyen","message":"Phieu luong cua toi gui qua dau?"}'
```

Người duyệt xử lý (CLI, dùng chung state với server):

```bash
python reviewer_cli.py list
python reviewer_cli.py show    <task_id>
python reviewer_cli.py claim   <task_id> --by minh.hr
python reviewer_cli.py approve <task_id> --by minh.hr
python reviewer_cli.py edit    <task_id> --by minh.hr --text "..." --reason "..."
python reviewer_cli.py sweep-sla
python reviewer_cli.py metrics
```

### 2. Web UI (Streamlit)

```bash
streamlit run streamlit_app.py
```

3 tab: **Chat** (người dùng hỏi) · **Hàng đợi duyệt** (claim → approve/edit/reject) ·
**Số liệu** (metrics realtime). Nút *Seed dữ liệu demo* ở sidebar chạy toàn bộ
`data/scenarios.jsonl` để có sẵn task + số liệu.

### 3. Mô phỏng + báo cáo số liệu

```bash
python scripts/run_simulation.py --seed 42     # 25 hội thoại + người duyệt giả lập
python scripts/generate_report.py              # -> reports/metrics.{json,csv}, final_report.md
```

Đồng hồ dùng bản giả (`models.set_clock`) nên latency trong report **tái lập được**.
Thêm `--live` vào `run_simulation.py` để gọi Gemini thật qua OpenRouter.

## Chạy test

```bash
pytest -q
```

45 test, ~0.5s, hoàn toàn offline. Mỗi test có `state_dir` riêng (`tmp_path`),
LLM luôn là `FakeLLM`, đồng hồ được reset sau mỗi test.

| File test | Kiểm tra chính |
|-----------|----------------|
| `test_retrieval_service.py` | tìm đúng doc; câu ngoài KB → điểm thấp; KB rỗng |
| `test_llm_service.py` | confidence theo retrieval; ungrounded khi không có hit; deterministic; fallback khi thiếu key |
| `test_risk_policy_service.py` | 4 rule; chốt chặn cứng thắng cả confidence cao; risk_score đơn điệu |
| `test_review_queue_service.py` | vòng đời; double-claim / resolve-sớm bị chặn; idempotent; SLA timeout |
| `test_feedback_store.py` | edit-distance; nhãn approve/edit/reject; export JSONL bỏ reject |
| `test_audit_service.py` | event đủ trường; append không ghi đè; đọc theo trace_id |
| `test_metrics_service.py` | các tỉ lệ khớp tính tay; P50/P95; log rỗng không chia 0 |
| `test_orchestrator.py` | end-to-end: auto / escalate→approve / escalate→edit / SLA timeout / idempotency |

## Đọc báo cáo

- `reports/final_report.md` — bảng số liệu + độ chính xác định tuyến + nhận xét tự động.
- `reports/metrics.json`, `reports/metrics.csv` — số liệu dạng máy đọc.
- `reports/feedback_dataset.jsonl` — tập `(query, context, draft, gold, label)`.
- `reports/report_template.md` — khung điền tay khi viết báo cáo chính thức.

Kết quả mẫu (seed 42): automation rate **52%**, escalation **48%**, trong đó approve
~58% / edit 25% / reject 0%, SLA breach 2 ca; định tuyến khớp nhãn tay **23/25 (92%)**
với 2 "known gap" được ghi rõ trong report (retrieval khớp nhầm / KB thiếu tình huống).

## Deploy lên Streamlit Community Cloud

1. Push repo lên GitHub (đã public).
2. Vào https://share.streamlit.io → **New app** → chọn repo, branch `main`,
   main file `streamlit_app.py`.
3. **Advanced settings**: Python 3.11+ (khuyến nghị 3.12).
4. **Settings → Secrets**: dán nội dung `.streamlit/secrets.toml.example` và điền
   `OPENROUTER_API_KEY` (không có key thì app tự chạy `FakeLLM`).
5. Deploy. Mỗi lần push `main`, Streamlit tự build lại.

Lưu ý: state (`data/state/*.json`) nằm trên container Streamlit — reset khi app
redeploy/ngủ. Đây là demo, không phải store bền vững.

## Giới hạn đã biết (production sẽ khác)

- `json_store` ghi atomic nhưng **không** chống 2 tiến trình ghi song song → thay bằng Postgres/hàng đợi thật.
- Audit lưu file JSON có thể sửa → production dùng sink append-only (Kafka/BigQuery).
- Retrieval TF-IDF đơn giản, đôi khi khớp nhầm doc → dùng vector search + rerank.
- Chưa có auth/RBAC cho endpoint người duyệt, chưa có thông báo realtime cho user khi task được resolve.
