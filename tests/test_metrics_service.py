"""Test metrics_service — tổng hợp số liệu từ audit log + feedback."""

from __future__ import annotations

from hitl_chatbot.audit_service import AuditLog
from hitl_chatbot.feedback_store import FeedbackStore
from hitl_chatbot.metrics_service import MetricsService, _percentile
from hitl_chatbot.models import (
    DocHit,
    DraftAnswer,
    ReviewAction,
    ReviewTask,
    Route,
    RouteDecision,
    TaskState,
)


def test_percentile_linear_interpolation():
    assert _percentile([], 50) == 0.0
    assert _percentile([10], 95) == 10
    assert _percentile([60, 240, 900], 50) == 240
    assert round(_percentile([60, 240, 900], 95), 1) == 834.0


def _resolved_task(action, draft="aaaa", gold="aaab"):
    return ReviewTask(
        id="tsk", trace_id="t", user="u", query="q",
        draft=DraftAnswer(text=draft, confidence=0.4, grounded=True),
        hits=[DocHit("d.md", 0.4, "…")],
        decision=RouteDecision(route=Route.ESCALATE, risk_score=0.4, reasons=["low_confidence"]),
        state=TaskState.RESOLVED, assignee="minh", action=action,
        final_answer=gold if action == ReviewAction.EDIT else draft,
        reviewer_reason="r",
    )


def test_compute_matches_hand_calc(config, clock):
    audit = AuditLog(config)
    feedback = FeedbackStore(config)

    # trace1: bot tự trả lời
    audit.emit("t1", "received")
    audit.emit("t1", "auto_replied")

    # trace2: escalate -> approve, latency 240s
    clock.advance(100)
    audit.emit("t2", "enqueued")
    clock.advance(240)
    audit.emit("t2", "resolved", {"action": "approve"})

    # trace3: escalate -> edit, latency 60s
    audit.emit("t3", "enqueued")
    clock.advance(60)
    audit.emit("t3", "resolved", {"action": "edit"})

    # trace4: escalate -> SLA timeout, latency 900s
    audit.emit("t4", "enqueued")
    clock.advance(900)
    audit.emit("t4", "sla_timeout")

    feedback.record(_resolved_task(ReviewAction.APPROVE))   # edit_distance 0.0
    feedback.record(_resolved_task(ReviewAction.EDIT))      # 1/4 = 0.25

    m = MetricsService(config, audit, feedback).compute()
    assert m["total_conversations"] == 4
    assert m["auto_answered"] == 1
    assert m["escalated"] == 3
    assert m["automation_rate_pct"] == 25.0
    assert m["escalation_rate_pct"] == 75.0
    assert m["approve_rate_pct"] == 33.33
    assert m["edit_rate_pct"] == 33.33
    assert m["reject_rate_pct"] == 0.0
    assert m["sla_timeout_count"] == 1
    assert m["sla_breach_rate_pct"] == 33.33
    assert m["review_latency_sec_p50"] == 240.0
    assert m["review_latency_sec_mean"] == 400.0
    assert m["avg_edit_distance"] == 0.125
    assert m["est_human_minutes_saved"] == 4.0


def test_empty_log_has_no_zero_division(config):
    m = MetricsService(config, AuditLog(config), FeedbackStore(config)).compute()
    assert m["total_conversations"] == 0
    assert m["automation_rate_pct"] == 0.0
    assert m["review_latency_sec_p95"] == 0.0
