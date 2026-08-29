"""Audit service — nhật ký append-only, truy vết mọi bước theo trace_id.

Vì sao quan trọng trong HITL production:
  - Khi có tranh chấp ("bot trả lời sai!"), phải dựng lại được CHÍNH XÁC:
    user hỏi gì -> tìm được doc nào -> LLM nháp gì -> policy quyết định sao ->
    ai duyệt -> sửa thành gì -> lúc mấy giờ.
  - metrics_service đọc lại đúng nhật ký này để tính số liệu -> "đo từ bằng
    chứng, không phải cảm tính".

Ở đây lưu bằng file JSON (list các event). Production nên dùng sink append-only
thật (Kafka, CloudWatch, BigQuery...) — không cho sửa/xoá.
"""

from __future__ import annotations

from .config import Config
from .json_store import JsonCollection
from .models import now_ts

# Các mốc (stage) hợp lệ trong vòng đời 1 request
STAGES = (
    "received",      # nhận câu hỏi từ user
    "retrieved",     # xong retrieval
    "drafted",       # LLM sinh xong câu nháp
    "routed",        # risk_policy ra quyết định auto/escalate
    "auto_replied",  # bot tự trả lời
    "enqueued",      # đẩy vào hàng đợi duyệt
    "claimed",       # người duyệt nhận task
    "resolved",      # người duyệt xử lý xong (approve/edit/reject)
    "sla_timeout",   # hệ thống tự đóng vì quá hạn
    "replied",       # gửi câu trả lời cuối cùng cho user
)


class AuditLog:
    def __init__(self, config: Config):
        self._col = JsonCollection(config.state_dir / "audit_log.json")

    def emit(self, trace_id: str, stage: str, payload: dict | None = None) -> dict:
        """Ghi 1 event. `stage` nên nằm trong STAGES (không ép buộc để dễ mở rộng)."""
        event = {
            "ts": now_ts(),
            "trace_id": trace_id,
            "stage": stage,
            "payload": payload or {},
        }
        self._col.append(event)
        return event

    # --- đọc lại ------------------------------------------------------- #
    def all_events(self) -> list[dict]:
        return sorted(self._col.all(), key=lambda e: e["ts"])

    def events_for(self, trace_id: str) -> list[dict]:
        return [e for e in self.all_events() if e["trace_id"] == trace_id]

    def trace_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for e in self.all_events():
            seen.setdefault(e["trace_id"], None)
        return list(seen)
