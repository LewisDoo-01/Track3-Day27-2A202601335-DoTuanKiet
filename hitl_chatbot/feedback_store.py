"""Feedback store — biến việc người duyệt làm thành DATASET cải tiến.

Mỗi lần người duyệt xử lý 1 task, ta ghi lại:
  - câu hỏi + context (những gì bot "thấy")
  - câu nháp của bot (draft)
  - câu cuối cùng người chốt (gold)
  - nhãn: approved_as_is / edited / rejected / sla_timeout
  - edit_distance chuẩn hoá giữa draft và gold (0 = giữ nguyên, 1 = viết lại hẳn)

Dùng để:
  - đo "bot nháp tốt tới đâu" (tỉ lệ approve nguyên văn, edit_distance trung bình)
  - export ra JSONL làm tập eval / fine-tune sau này
"""

from __future__ import annotations

from .config import Config
from .json_store import JsonCollection
from .models import ReviewAction, ReviewTask, now_ts

_LABELS = {
    ReviewAction.APPROVE: "approved_as_is",
    ReviewAction.EDIT: "edited",
    ReviewAction.REJECT: "rejected",
    ReviewAction.SLA_TIMEOUT: "sla_timeout",
}


def normalized_edit_distance(a: str, b: str) -> float:
    """Levenshtein / max(len) -> [0, 1]. Thuần Python, đủ nhanh cho câu trả lời."""
    a, b = a.strip(), b.strip()
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(
                min(
                    prev[j] + 1,        # xoá
                    cur[j - 1] + 1,     # thêm
                    prev[j - 1] + (ca != cb),  # thay
                )
            )
        prev = cur
    return round(prev[-1] / max(len(a), len(b)), 4)


class FeedbackStore:
    def __init__(self, config: Config):
        self._col = JsonCollection(config.state_dir / "feedback.json")

    def record(self, task: ReviewTask) -> dict:
        """Gọi sau khi task đã RESOLVED."""
        gold = task.final_answer or ""
        action = task.action or ReviewAction.APPROVE
        dist = (
            0.0
            if action == ReviewAction.APPROVE
            else normalized_edit_distance(task.draft.text, gold)
        )
        row = {
            "ts": now_ts(),
            "trace_id": task.trace_id,
            "task_id": task.id,
            "query": task.query,
            "context": [h.doc_id for h in task.hits],
            "draft": task.draft.text,
            "draft_confidence": task.draft.confidence,
            "gold": gold if action != ReviewAction.REJECT else "",
            "label": _LABELS.get(action, "unknown"),
            "edit_distance": dist,
            "reviewer": task.assignee,
            "reason": task.reviewer_reason,
        }
        self._col.append(row)
        return row

    # --- đọc / export ------------------------------------------------- #
    def all(self) -> list[dict]:
        return self._col.all()

    def export_jsonl(self, path) -> int:
        """Xuất tập (query, context, draft, gold, label) ra JSONL. Trả số dòng."""
        import json
        from pathlib import Path

        rows = [r for r in self.all() if r["label"] != "rejected"]
        Path(path).write_text(
            "\n".join(
                json.dumps(
                    {
                        "query": r["query"],
                        "context": r["context"],
                        "draft": r["draft"],
                        "gold": r["gold"],
                        "label": r["label"],
                    },
                    ensure_ascii=False,
                )
                for r in rows
            ),
            encoding="utf-8",
        )
        return len(rows)
