"""Test orchestrator — pipeline HITL đầu-cuối (dùng KB thật trong data/kb)."""

from __future__ import annotations

from hitl_chatbot.models import ReplyStatus, ReviewAction, Route, TaskState
from hitl_chatbot.orchestrator import HITLOrchestrator


def test_safe_question_answered_automatically(real_kb_config):
    orch = HITLOrchestrator(real_kb_config)
    resp = orch.handle_message("an.nguyen", "Tôi được bao nhiêu ngày phép năm?")
    assert resp.status == ReplyStatus.ANSWERED
    assert resp.route == Route.AUTO
    stages = {e["stage"] for e in orch.audit.events_for(resp.trace_id)}
    assert {"received", "retrieved", "drafted", "routed", "auto_replied", "replied"} <= stages
    assert orch.queue.list() == []


def test_sensitive_question_goes_to_review_queue(real_kb_config):
    orch = HITLOrchestrator(real_kb_config)
    resp = orch.handle_message("an.nguyen", "Lương tháng này của tôi bị trừ nhiều, vì sao?")
    assert resp.status == ReplyStatus.PENDING_REVIEW
    assert resp.task_id is not None
    task = orch.queue.get(resp.task_id)
    assert task.state == TaskState.PENDING
    assert any(r.startswith("sensitive_topic") for r in task.decision.reasons)


def test_escalate_then_approve(real_kb_config):
    orch = HITLOrchestrator(real_kb_config)
    resp = orch.handle_message("an.nguyen", "Phiếu lương của tôi gửi qua đâu?")
    orch.claim_review(resp.task_id, "minh.hr")
    task = orch.resolve_review(
        resp.task_id, reviewer="minh.hr", action=ReviewAction.APPROVE
    )
    assert task.state == TaskState.RESOLVED
    assert task.final_answer == task.draft.text
    fb = orch.feedback.all()
    assert fb[-1]["label"] == "approved_as_is"
    stages = {e["stage"] for e in orch.audit.events_for(resp.trace_id)}
    assert {"enqueued", "claimed", "resolved", "replied"} <= stages


def test_escalate_then_edit_records_edit_distance(real_kb_config):
    orch = HITLOrchestrator(real_kb_config)
    resp = orch.handle_message("an.nguyen", "Chế độ nghỉ thai sản của công ty ra sao?")
    orch.claim_review(resp.task_id, "lan.hr")
    task = orch.resolve_review(
        resp.task_id,
        reviewer="lan.hr",
        action=ReviewAction.EDIT,
        edited_text="Công ty áp dụng nghỉ thai sản 6 tháng theo luật. Liên hệ HR để biết chi tiết.",
        reason="KB chưa có, chuyên viên trả lời trực tiếp",
    )
    assert task.final_answer.startswith("Công ty áp dụng")
    assert orch.feedback.all()[-1]["edit_distance"] > 0.0


def test_sla_timeout_closes_with_safe_default(real_kb_config, clock):
    orch = HITLOrchestrator(real_kb_config)
    resp = orch.handle_message("an.nguyen", "Tôi muốn khiếu nại quyết định kỷ luật")
    clock.advance(real_kb_config.review_sla_seconds + 10)
    expired = orch.sweep_sla()
    assert [t.id for t in expired] == [resp.task_id]
    m = orch.metrics.compute()
    assert m["sla_timeout_count"] == 1
    assert orch.queue.get(resp.task_id).action == ReviewAction.SLA_TIMEOUT


def test_resolve_is_idempotent_no_double_feedback(real_kb_config):
    orch = HITLOrchestrator(real_kb_config)
    resp = orch.handle_message("an.nguyen", "Phiếu lương của tôi gửi qua đâu?")
    orch.claim_review(resp.task_id, "minh.hr")
    orch.resolve_review(resp.task_id, reviewer="minh.hr", action=ReviewAction.APPROVE)
    orch.resolve_review(resp.task_id, reviewer="minh.hr", action=ReviewAction.APPROVE)
    assert len(orch.feedback.all()) == 1
    resolved_events = [
        e for e in orch.audit.events_for(resp.trace_id) if e["stage"] == "resolved"
    ]
    assert len(resolved_events) == 1
