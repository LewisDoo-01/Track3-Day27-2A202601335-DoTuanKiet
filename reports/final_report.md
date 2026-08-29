# Báo cáo số liệu — HITL Chatbot

> Sinh tự động bởi `scripts/generate_report.py` từ `data/state/audit_log.json`.
> Cấu hình: confidence_threshold=0.6, retrieval_threshold=0.12, SLA=900s.

## Bảng số liệu

| Metric | Value |
|--------|-------|
| `total_conversations` | 25 |
| `auto_answered` | 13 |
| `escalated` | 12 |
| `automation_rate_pct` | 52.0 |
| `escalation_rate_pct` | 48.0 |
| `review_resolved` | 10 |
| `approve_rate_pct` | 58.33 |
| `edit_rate_pct` | 25.0 |
| `reject_rate_pct` | 0.0 |
| `sla_timeout_count` | 2 |
| `sla_breach_rate_pct` | 16.67 |
| `review_latency_sec_p50` | 1751.31 |
| `review_latency_sec_p95` | 3410.76 |
| `review_latency_sec_mean` | 1918.94 |
| `avg_edit_distance` | 0.0763 |
| `est_human_minutes_saved` | 52.0 |

## Chất lượng định tuyến (routing)

Độ chính xác định tuyến so với nhãn tay: **23/25 (92.0%)**.

| id | câu hỏi | kỳ vọng | thực tế | ghi chú |
|----|---------|---------|---------|---------|
| q19 | Công ty có chính sách cho mang thú cưng đến văn ph | escalate | auto | KNOWN GAP: ngoài KB nhưng TF-IDF vẫn khớp nhầm 1 doc -> bot tự trả lời. Cần retr |
| q21 | Tôi hợp đồng thời vụ thì có được mua bảo hiểm sức  | escalate | auto | KNOWN GAP: KB chỉ nói 'hợp đồng chính thức', trường hợp thời vụ chưa có -> bot t |

## Nhận xét tự động

- Bot tự xử lý **52.0%** hội thoại, còn **48.0%** phải chuyển người.
- Trong số ca chuyển người: approve 58.33%, edit 25.0%, reject 0.0%.
- Có **2** ca vượt SLA (16.67%) — cần thêm người trực hoặc kéo dài SLA/định tuyến lại.
- Ước tính tiết kiệm **52.0 phút** công xử lý thủ công.
- Latency duyệt: P50 1751.31s / P95 3410.76s. Edit-distance TB 0.0763.

## Dataset phản hồi

Đã xuất **12** mẫu vào `reports/feedback_dataset.jsonl`
(các trường: query, context, draft, gold, label) — dùng cho eval hồi quy hoặc fine-tune.

## Cách tái lập

```bash
python scripts/run_simulation.py --seed 42
python scripts/generate_report.py
```
