"""Metrics service — tổng hợp số liệu vận hành HITL TỪ audit log.

Nguyên tắc: đo từ bằng chứng (audit event), không phải từ biến đếm rải rác
trong code. Muốn kiểm chứng con số -> mở data/state/audit_log.json ra soi.

Các chỉ số (đúng ngôn ngữ vận hành trung tâm hỗ trợ):
  automation_rate      : % hội thoại bot tự trả lời (không cần người)
  escalation_rate      : % hội thoại phải chuyển người
  approve/edit/reject_rate : trong số ca chuyển người, người duyệt xử lý thế nào
  review_latency P50/P95   : thời gian từ lúc enqueue -> resolved (giây)
  sla_breach_rate      : % ca chuyển người bị timeout (không ai duyệt kịp)
  avg_edit_distance    : trung bình mức độ người phải sửa câu nháp
  est_human_minutes_saved : auto_answered * phút-xử-lý-thủ-công giả định
"""

from __future__ import annotations

import csv
import io
import json
import statistics

from .audit_service import AuditLog
from .config import Config
from .feedback_store import FeedbackStore


def _percentile(values: list[float], pct: float) -> float:
    """Percentile theo nội suy tuyến tính. pct trong [0, 100]."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = (pct / 100) * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


class MetricsService:
    def __init__(self, config: Config, audit: AuditLog, feedback: FeedbackStore):
        self.config = config
        self.audit = audit
        self.feedback = feedback

    # ------------------------------------------------------------------ #
    def compute(self) -> dict:
        events = self.audit.all_events()
        by_trace: dict[str, list[dict]] = {}
        for e in events:
            by_trace.setdefault(e["trace_id"], []).append(e)

        total = len(by_trace)
        auto = escalated = 0
        approve = edit = reject = sla_timeout = 0
        latencies: list[float] = []

        for stages in by_trace.values():
            kinds = {s["stage"] for s in stages}
            if "auto_replied" in kinds:
                auto += 1
            if "enqueued" in kinds:
                escalated += 1
                enq = next(s for s in stages if s["stage"] == "enqueued")
                done = [
                    s for s in stages if s["stage"] in ("resolved", "sla_timeout")
                ]
                if done:
                    latencies.append(done[-1]["ts"] - enq["ts"])
                for s in stages:
                    if s["stage"] == "resolved":
                        act = s["payload"].get("action")
                        approve += act == "approve"
                        edit += act == "edit"
                        reject += act == "reject"
                    if s["stage"] == "sla_timeout":
                        sla_timeout += 1

        fb = self.feedback.all()
        dists = [
            r["edit_distance"]
            for r in fb
            if r["label"] in ("edited", "approved_as_is")
        ]

        def pct(n: int, d: int) -> float:
            return round(100 * n / d, 2) if d else 0.0

        return {
            "total_conversations": total,
            "auto_answered": auto,
            "escalated": escalated,
            "automation_rate_pct": pct(auto, total),
            "escalation_rate_pct": pct(escalated, total),
            "review_resolved": approve + edit + reject,
            "approve_rate_pct": pct(approve, escalated),
            "edit_rate_pct": pct(edit, escalated),
            "reject_rate_pct": pct(reject, escalated),
            "sla_timeout_count": sla_timeout,
            "sla_breach_rate_pct": pct(sla_timeout, escalated),
            "review_latency_sec_p50": round(_percentile(latencies, 50), 2),
            "review_latency_sec_p95": round(_percentile(latencies, 95), 2),
            "review_latency_sec_mean": round(
                statistics.fmean(latencies) if latencies else 0.0, 2
            ),
            "avg_edit_distance": round(
                statistics.fmean(dists) if dists else 0.0, 4
            ),
            "est_human_minutes_saved": round(
                auto * self.config.minutes_per_manual_answer, 1
            ),
        }

    # ------------------------------------------------------------------ #
    def to_json(self, path) -> dict:
        data = self.compute()
        from pathlib import Path

        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data

    def to_csv(self, path) -> None:
        data = self.compute()
        from pathlib import Path

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["metric", "value"])
        for k, v in data.items():
            w.writerow([k, v])
        Path(path).write_text(buf.getvalue(), encoding="utf-8")
