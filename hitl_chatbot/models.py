"""Các kiểu dữ liệu dùng chung, viết bằng dataclass cho gọn và dễ serialize.

Toàn bộ pipeline truyền các object này qua lại. Mỗi object đều có `to_dict()`
để ghi xuống JSON (audit log, review queue...).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


def new_trace_id() -> str:
    """ID truy vết 1 hội thoại, xuất hiện trong MỌI dòng audit của hội thoại đó."""
    return "trc_" + uuid.uuid4().hex[:12]


_CLOCK = None  # hàm trả về epoch giây; None = dùng đồng hồ thật


def set_clock(fn) -> None:
    """Cắm 1 đồng hồ giả (test / simulation). Gọi set_clock(None) để trả về thật."""
    global _CLOCK
    _CLOCK = fn


def now_ts() -> float:
    """Thời điểm hiện tại (epoch giây). Dùng đồng hồ giả nếu đã set_clock()."""
    return _CLOCK() if _CLOCK is not None else time.time()


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
@dataclass
class DocHit:
    """Một tài liệu KB khớp với câu hỏi."""

    doc_id: str          # tên file, ví dụ "nghi_phep.md"
    score: float         # điểm tương đồng TF-IDF cosine trong [0, 1]
    snippet: str         # đoạn trích để hiển thị / làm context cho LLM

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
@dataclass
class DraftAnswer:
    """Câu trả lời NHÁP do LLM sinh ra — chưa chắc được gửi cho user."""

    text: str
    confidence: float           # LLM/heuristic tự đánh giá, trong [0, 1]
    citations: list[str] = field(default_factory=list)   # doc_id được dùng
    grounded: bool = True       # False nếu trả lời mà không có tài liệu nào đỡ
    model: str = "fake"

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Risk policy
# --------------------------------------------------------------------------- #
class Route(str, Enum):
    """Kết quả định tuyến của risk_policy_service."""

    AUTO = "auto"          # bot tự trả lời ngay
    ESCALATE = "escalate"  # đẩy vào hàng đợi cho người duyệt


@dataclass
class RouteDecision:
    route: Route
    risk_score: float            # 0.0 (an toàn) .. 1.0 (rủi ro cao)
    reasons: list[str] = field(default_factory=list)  # vì sao ra quyết định này

    def to_dict(self) -> dict:
        d = asdict(self)
        d["route"] = self.route.value
        return d


# --------------------------------------------------------------------------- #
# Review queue
# --------------------------------------------------------------------------- #
class TaskState(str, Enum):
    PENDING = "pending"        # chờ người nhận
    IN_REVIEW = "in_review"    # đã có người nhận (claim), đang xử lý
    RESOLVED = "resolved"      # đã xong (approve/edit/reject/sla_timeout)


class ReviewAction(str, Enum):
    APPROVE = "approve"        # giữ nguyên câu nháp
    EDIT = "edit"             # sửa lại câu trả lời
    REJECT = "reject"         # từ chối trả lời (câu hỏi sai chỗ / cần kênh khác)
    SLA_TIMEOUT = "sla_timeout"  # hệ thống tự đóng vì quá hạn


@dataclass
class ReviewTask:
    """Một việc cần người duyệt. Đây là bản ghi được persist xuống JSON."""

    id: str
    trace_id: str
    user: str
    query: str
    draft: DraftAnswer
    hits: list[DocHit]
    decision: RouteDecision
    state: TaskState = TaskState.PENDING
    assignee: str | None = None
    created_at: float = field(default_factory=now_ts)
    claimed_at: float | None = None
    resolved_at: float | None = None
    action: ReviewAction | None = None
    final_answer: str | None = None
    reviewer_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "user": self.user,
            "query": self.query,
            "draft": self.draft.to_dict(),
            "hits": [h.to_dict() for h in self.hits],
            "decision": self.decision.to_dict(),
            "state": self.state.value,
            "assignee": self.assignee,
            "created_at": self.created_at,
            "claimed_at": self.claimed_at,
            "resolved_at": self.resolved_at,
            "action": self.action.value if self.action else None,
            "final_answer": self.final_answer,
            "reviewer_reason": self.reviewer_reason,
        }

    @staticmethod
    def from_dict(d: dict) -> "ReviewTask":
        return ReviewTask(
            id=d["id"],
            trace_id=d["trace_id"],
            user=d["user"],
            query=d["query"],
            draft=DraftAnswer(**d["draft"]),
            hits=[DocHit(**h) for h in d["hits"]],
            decision=RouteDecision(
                route=Route(d["decision"]["route"]),
                risk_score=d["decision"]["risk_score"],
                reasons=list(d["decision"]["reasons"]),
            ),
            state=TaskState(d["state"]),
            assignee=d.get("assignee"),
            created_at=d["created_at"],
            claimed_at=d.get("claimed_at"),
            resolved_at=d.get("resolved_at"),
            action=ReviewAction(d["action"]) if d.get("action") else None,
            final_answer=d.get("final_answer"),
            reviewer_reason=d.get("reviewer_reason"),
        )


# --------------------------------------------------------------------------- #
# Kết quả trả về cho người dùng cuối
# --------------------------------------------------------------------------- #
class ReplyStatus(str, Enum):
    ANSWERED = "answered"                # đã có câu trả lời cuối cùng
    PENDING_REVIEW = "pending_review"    # đang chờ người duyệt


@dataclass
class ChatResponse:
    trace_id: str
    status: ReplyStatus
    answer: str                      # câu trả lời, hoặc thông báo "đang chờ duyệt"
    route: Route
    task_id: str | None = None       # có giá trị khi status = PENDING_REVIEW

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["route"] = self.route.value
        return d
