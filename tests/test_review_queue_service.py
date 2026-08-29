"""Test review_queue_service — state machine, idempotency, SLA."""

from __future__ import annotations

import pytest

from hitl_chatbot.models import (
    DocHit,
    DraftAnswer,
    ReviewAction,
    Route,
    RouteDecision,
    TaskState,
)
from hitl_chatbot.review_queue_service import QueueError, ReviewQueue


def _enqueue(q: ReviewQueue, conf=0.4):
    return q.enqueue(
        trace_id="trc_test",
        user="an.nguyen",
        query="phiếu lương gửi qua đâu",
        draft=DraftAnswer(text="Gửi qua email nội bộ.", confidence=conf, grounded=True),
        hits=[DocHit("luong.md", 0.5, "phiếu lương gửi qua email nội bộ")],
        decision=RouteDecision(route=Route.ESCALATE, risk_score=0.6, reasons=["sensitive_topic:lương"]),
    )


def test_enqueue_creates_pending_task(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    assert t.state == TaskState.PENDING
    assert q.get(t.id).query == "phiếu lương gửi qua đâu"
    assert len(q.pending()) == 1


def test_claim_moves_to_in_review(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    claimed = q.claim(t.id, "minh.hr")
    assert claimed.state == TaskState.IN_REVIEW
    assert claimed.assignee == "minh.hr"
    assert claimed.claimed_at is not None


def test_double_claim_is_rejected(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    q.claim(t.id, "minh.hr")
    with pytest.raises(QueueError):
        q.claim(t.id, "lan.hr")


def test_resolve_before_claim_is_rejected(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    with pytest.raises(QueueError):
        q.resolve(t.id, reviewer="minh.hr", action=ReviewAction.APPROVE)


def test_resolve_approve_uses_draft_text(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    q.claim(t.id, "minh.hr")
    done = q.resolve(t.id, reviewer="minh.hr", action=ReviewAction.APPROVE)
    assert done.state == TaskState.RESOLVED
    assert done.final_answer == t.draft.text
    assert done.action == ReviewAction.APPROVE


def test_edit_requires_reason_and_text(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    q.claim(t.id, "minh.hr")
    with pytest.raises(QueueError):
        q.resolve(t.id, reviewer="minh.hr", action=ReviewAction.EDIT, edited_text="x")
    done = q.resolve(
        t.id, reviewer="minh.hr", action=ReviewAction.EDIT,
        edited_text="Phiếu lương gửi qua email nội bộ, mật khẩu là mã nhân viên.",
        reason="bổ sung cách mở file",
    )
    assert done.final_answer.endswith("mã nhân viên.")


def test_resolve_is_idempotent(config):
    q = ReviewQueue(config)
    t = _enqueue(q)
    q.claim(t.id, "minh.hr")
    first = q.resolve(t.id, reviewer="minh.hr", action=ReviewAction.APPROVE)
    second = q.resolve(t.id, reviewer="lan.hr", action=ReviewAction.REJECT, reason="đổi ý")
    assert second.action == first.action == ReviewAction.APPROVE
    assert second.final_answer == first.final_answer


def test_expire_stale_closes_with_safe_default(config, clock):
    q = ReviewQueue(config)
    t = _enqueue(q)
    clock.advance(config.review_sla_seconds + 1)
    expired = q.expire_stale()
    assert [e.id for e in expired] == [t.id]
    reloaded = q.get(t.id)
    assert reloaded.state == TaskState.RESOLVED
    assert reloaded.action == ReviewAction.SLA_TIMEOUT
    assert reloaded.final_answer == config.safe_default_answer


def test_expire_stale_ignores_fresh_tasks(config, clock):
    q = ReviewQueue(config)
    _enqueue(q)
    clock.advance(config.review_sla_seconds - 5)
    assert q.expire_stale() == []


def test_list_filters_by_state(config):
    q = ReviewQueue(config)
    a = _enqueue(q)
    _enqueue(q)
    q.claim(a.id, "minh.hr")
    assert len(q.list(TaskState.PENDING)) == 1
    assert len(q.list(TaskState.IN_REVIEW)) == 1
    assert len(q.list()) == 2
