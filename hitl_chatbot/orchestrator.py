"""Orchestrator — ghép tất cả service thành 1 pipeline HITL.

    handle_message(user, text)
        -> retrieval -> llm -> risk_policy
        -> AUTO     : trả lời ngay,     audit(auto_replied, replied)
        -> ESCALATE : enqueue,          audit(enqueued), báo user "đang chờ duyệt"

    resolve_review(task_id, reviewer, action, edited_text, reason)
        -> review_queue.resolve -> feedback_store.record
        -> audit(resolved, replied) -> trả câu trả lời cuối cùng

    sweep_sla()  # gọi định kỳ (cron / lúc list hàng đợi)
        -> đóng task quá hạn, audit(sla_timeout, replied)

Mọi bước đều emit audit với CÙNG trace_id -> truy vết trọn vẹn 1 hội thoại.
"""

from __future__ import annotations

from .audit_service import AuditLog
from .config import Config, load_config
from .feedback_store import FeedbackStore
from .llm_service import build_llm
from .metrics_service import MetricsService
from .models import (
    ChatResponse,
    ReplyStatus,
    ReviewAction,
    ReviewTask,
    Route,
    new_trace_id,
)
from .retrieval_service import RetrievalService
from .review_queue_service import ReviewQueue
from .risk_policy_service import RiskPolicyService


class HITLOrchestrator:
    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.retrieval = RetrievalService(self.config)
        self.llm = build_llm(self.config)
        self.policy = RiskPolicyService(self.config)
        self.audit = AuditLog(self.config)
        self.queue = ReviewQueue(self.config)
        self.feedback = FeedbackStore(self.config)
        self.metrics = MetricsService(self.config, self.audit, self.feedback)

    # ------------------------------------------------------------------ #
    def handle_message(self, user: str, text: str) -> ChatResponse:
        trace_id = new_trace_id()
        self.audit.emit(trace_id, "received", {"user": user, "query": text})

        hits = self.retrieval.search(text)
        self.audit.emit(
            trace_id,
            "retrieved",
            {"hits": [h.to_dict() for h in hits], "top_score": self.retrieval.top_score(hits)},
        )

        draft = self.llm.draft(text, hits)
        self.audit.emit(trace_id, "drafted", draft.to_dict())

        decision = self.policy.decide(text, draft, hits)
        self.audit.emit(trace_id, "routed", decision.to_dict())

        if decision.route == Route.AUTO:
            self.audit.emit(trace_id, "auto_replied", {"answer": draft.text})
            self.audit.emit(trace_id, "replied", {"answer": draft.text, "route": "auto"})
            return ChatResponse(
                trace_id=trace_id,
                status=ReplyStatus.ANSWERED,
                answer=draft.text,
                route=Route.AUTO,
            )

        task = self.queue.enqueue(
            trace_id=trace_id,
            user=user,
            query=text,
            draft=draft,
            hits=hits,
            decision=decision,
        )
        self.audit.emit(
            trace_id,
            "enqueued",
            {"task_id": task.id, "risk_score": decision.risk_score, "reasons": decision.reasons},
        )
        return ChatResponse(
            trace_id=trace_id,
            status=ReplyStatus.PENDING_REVIEW,
            answer=(
                "Câu hỏi của bạn cần chuyên viên phụ trách xác nhận trước khi trả lời. "
                "Bạn sẽ nhận được phản hồi sớm nhất có thể."
            ),
            route=Route.ESCALATE,
            task_id=task.id,
        )

    # ------------------------------------------------------------------ #
    def claim_review(self, task_id: str, reviewer: str) -> ReviewTask:
        task = self.queue.claim(task_id, reviewer)
        self.audit.emit(task.trace_id, "claimed", {"task_id": task_id, "reviewer": reviewer})
        return task

    def resolve_review(
        self,
        task_id: str,
        *,
        reviewer: str,
        action: ReviewAction,
        edited_text: str | None = None,
        reason: str | None = None,
    ) -> ReviewTask:
        pre = self.queue.get(task_id)
        task = self.queue.resolve(
            task_id,
            reviewer=reviewer,
            action=action,
            edited_text=edited_text,
            reason=reason,
        )
        # Idempotency: nếu task đã RESOLVED từ trước, không log/ghi feedback lần nữa.
        already_done = pre is not None and pre.state.value == "resolved"
        if not already_done:
            self.feedback.record(task)
            self.audit.emit(
                task.trace_id,
                "resolved",
                {
                    "task_id": task_id,
                    "reviewer": reviewer,
                    "action": task.action.value if task.action else None,
                    "reason": reason,
                },
            )
            self.audit.emit(
                task.trace_id,
                "replied",
                {"answer": task.final_answer, "route": "human"},
            )
        return task

    # ------------------------------------------------------------------ #
    def sweep_sla(self, now: float | None = None) -> list[ReviewTask]:
        expired = self.queue.expire_stale(now=now)
        for task in expired:
            self.feedback.record(task)
            self.audit.emit(task.trace_id, "sla_timeout", {"task_id": task.id})
            self.audit.emit(
                task.trace_id,
                "replied",
                {"answer": task.final_answer, "route": "sla_timeout"},
            )
        return expired
