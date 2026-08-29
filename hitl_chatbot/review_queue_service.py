"""Review queue service — hàng đợi cho người duyệt.

State machine (không cho nhảy cóc):

        enqueue()            claim()               resolve()
   ─────────────────►  PENDING ─────────► IN_REVIEW ─────────► RESOLVED
                          │                                      ▲
                          └──────── expire_stale() ──────────────┘
                                  (quá SLA, không ai nhận)

Các bảo đảm kiểu production:
  - claim() 2 lần cùng task -> lần 2 báo lỗi (không cho 2 người cùng sửa).
  - resolve() khi chưa claim -> lỗi (phải có người chịu trách nhiệm).
  - resolve() 1 task đã RESOLVED -> IDEMPOTENT: trả lại kết quả cũ, không ghi đè,
    không double-log. (Client bấm 2 lần / retry mạng không gây hại.)
  - expire_stale() gom mọi task PENDING quá hạn, đóng bằng câu safe-default.
"""

from __future__ import annotations

import uuid

from .config import Config
from .json_store import JsonCollection
from .models import (
    DocHit,
    DraftAnswer,
    ReviewAction,
    ReviewTask,
    RouteDecision,
    TaskState,
    now_ts,
)


class QueueError(RuntimeError):
    """Vi phạm state machine (claim trùng, resolve khi chưa claim...)."""


class ReviewQueue:
    def __init__(self, config: Config):
        self.config = config
        self._col = JsonCollection(config.state_dir / "review_queue.json")

    # ------------------------------------------------------------------ #
    def enqueue(
        self,
        *,
        trace_id: str,
        user: str,
        query: str,
        draft: DraftAnswer,
        hits: list[DocHit],
        decision: RouteDecision,
    ) -> ReviewTask:
        task = ReviewTask(
            id="tsk_" + uuid.uuid4().hex[:12],
            trace_id=trace_id,
            user=user,
            query=query,
            draft=draft,
            hits=hits,
            decision=decision,
            state=TaskState.PENDING,
            created_at=now_ts(),
        )
        self._col.append(task.to_dict())
        return task

    # ------------------------------------------------------------------ #
    def get(self, task_id: str) -> ReviewTask | None:
        row = self._col.get(lambda r: r["id"] == task_id)
        return ReviewTask.from_dict(row) if row else None

    def list(self, state: TaskState | None = None) -> list[ReviewTask]:
        rows = self._col.all()
        tasks = [ReviewTask.from_dict(r) for r in rows]
        if state is not None:
            tasks = [t for t in tasks if t.state == state]
        # ưu tiên: rủi ro cao trước, rồi tới cũ nhất
        tasks.sort(key=lambda t: (-t.decision.risk_score, t.created_at))
        return tasks

    def pending(self) -> list[ReviewTask]:
        return self.list(TaskState.PENDING)

    # ------------------------------------------------------------------ #
    def claim(self, task_id: str, reviewer: str) -> ReviewTask:
        task = self._require(task_id)
        if task.state == TaskState.IN_REVIEW:
            raise QueueError(
                f"task {task_id} đã được {task.assignee} nhận rồi"
            )
        if task.state == TaskState.RESOLVED:
            raise QueueError(f"task {task_id} đã đóng, không thể nhận")

        def mutate(r: dict) -> dict:
            r["state"] = TaskState.IN_REVIEW.value
            r["assignee"] = reviewer
            r["claimed_at"] = now_ts()
            return r

        self._col.update(lambda r: r["id"] == task_id, mutate)
        return self._require(task_id)

    # ------------------------------------------------------------------ #
    def resolve(
        self,
        task_id: str,
        *,
        reviewer: str,
        action: ReviewAction,
        edited_text: str | None = None,
        reason: str | None = None,
    ) -> ReviewTask:
        task = self._require(task_id)

        # Idempotency: đã đóng rồi thì trả lại nguyên trạng, không làm gì thêm.
        if task.state == TaskState.RESOLVED:
            return task

        if task.state != TaskState.IN_REVIEW:
            raise QueueError(
                f"phải claim task {task_id} trước khi resolve (state={task.state.value})"
            )
        if action in (ReviewAction.EDIT, ReviewAction.REJECT) and not reason:
            raise QueueError(f"action {action.value} bắt buộc có `reason`")

        final = self._final_answer(task, action, edited_text)

        def mutate(r: dict) -> dict:
            r["state"] = TaskState.RESOLVED.value
            r["action"] = action.value
            r["final_answer"] = final
            r["reviewer_reason"] = reason
            r["assignee"] = reviewer
            r["resolved_at"] = now_ts()
            return r

        self._col.update(lambda r: r["id"] == task_id, mutate)
        return self._require(task_id)

    # ------------------------------------------------------------------ #
    def expire_stale(self, now: float | None = None) -> list[ReviewTask]:
        """Đóng mọi task PENDING quá SLA bằng câu safe-default. Trả list đã đóng."""
        now = now if now is not None else now_ts()
        limit = self.config.review_sla_seconds
        expired: list[ReviewTask] = []
        for task in self.pending():
            if now - task.created_at < limit:
                continue

            def mutate(r: dict) -> dict:
                r["state"] = TaskState.RESOLVED.value
                r["action"] = ReviewAction.SLA_TIMEOUT.value
                r["final_answer"] = self.config.safe_default_answer
                r["reviewer_reason"] = f"SLA {limit}s vượt hạn, không có người duyệt"
                r["resolved_at"] = now
                return r

            self._col.update(lambda r, _id=task.id: r["id"] == _id, mutate)
            expired.append(self._require(task.id))
        return expired

    # ------------------------------------------------------------------ #
    @staticmethod
    def _final_answer(
        task: ReviewTask, action: ReviewAction, edited_text: str | None
    ) -> str:
        if action == ReviewAction.APPROVE:
            return task.draft.text
        if action == ReviewAction.EDIT:
            if not edited_text:
                raise QueueError("action=edit cần `edited_text`")
            return edited_text
        if action == ReviewAction.REJECT:
            return (
                "Câu hỏi này không thể trả lời qua chatbot. "
                "Vui lòng liên hệ trực tiếp bộ phận phụ trách."
            )
        return task.draft.text

    def _require(self, task_id: str) -> ReviewTask:
        task = self.get(task_id)
        if task is None:
            raise QueueError(f"không tìm thấy task {task_id}")
        return task
