# Báo cáo HITL Chatbot — <ngày>

Khung điền tay. Bản sinh tự động: `final_report.md`.

## 1. Bối cảnh
- Domain: trợ lý nội bộ HR/IT.
- Nguồn câu hỏi: `data/scenarios.jsonl` (<N> câu), seed <seed>.
- LLM: <fake | google/gemini-2.5-flash qua OpenRouter>.

## 2. Cấu hình policy
| Tham số | Giá trị | Ghi chú |
|---------|---------|---------|
| confidence_threshold | | dưới ngưỡng -> chuyển người |
| retrieval_threshold | | thiếu căn cứ -> chuyển người |
| review_sla_seconds | | quá hạn -> câu safe-default |
| sensitive_keywords | | chốt chặn cứng |

## 3. Số liệu chính
| Metric | Giá trị | Mục tiêu | Đạt? |
|--------|---------|----------|------|
| automation_rate_pct | | | |
| escalation_rate_pct | | | |
| approve_rate_pct | | | |
| edit_rate_pct | | | |
| reject_rate_pct | | | |
| sla_breach_rate_pct | | 0% | |
| review_latency_sec_p95 | | | |
| avg_edit_distance | | | |
| est_human_minutes_saved | | | |

## 4. Phân tích routing
- Routing khớp kỳ vọng: <x>/<N>.
- Các ca sai (nếu có) và nguyên nhân:

## 5. Đề xuất chỉnh policy
-

## 6. Rủi ro còn lại / việc tiếp theo
-
