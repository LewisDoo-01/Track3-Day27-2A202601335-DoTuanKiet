"""Test feedback_store — edit distance + ghi dataset phản hồi."""

from __future__ import annotations

import json

from hitl_chatbot.feedback_store import FeedbackStore, normalized_edit_distance
from hitl_chatbot.models import (
    DocHit,
    DraftAnswer,
    ReviewAction,
    ReviewTask,
    Route,
    RouteDecision,
    TaskState,
)


def _task(action, draft_text="Bạn được 12 ngày phép năm.", final=None):
    return ReviewTask(
        id="tsk_1",
        trace_id="trc_1",
        user="an",
        query="phép năm",
        draft=DraftAnswer(text=draft_text, confidence=0.4, grounded=True, citations=["phep.md"]),
        hits=[DocHit("phep.md", 0.4, "12 ngày phép năm")],
        decision=RouteDecision(route=Route.ESCALATE, risk_score=0.4, reasons=["low_confidence"]),
        state=TaskState.RESOLVED,
        assignee="minh.hr",
        action=action,
        final_answer=final if final is not None else draft_text,
        reviewer_reason="r",
    )


def test_normalized_edit_distance_bounds():
    assert normalized_edit_distance("abc", "abc") == 0.0
    assert normalized_edit_distance("abc", "xyz") == 1.0
    assert 0.0 < normalized_edit_distance("phép năm 12 ngày", "phép năm 14 ngày") < 1.0


def test_record_approve_has_zero_distance(config):
    fs = FeedbackStore(config)
    row = fs.record(_task(ReviewAction.APPROVE))
    assert row["label"] == "approved_as_is"
    assert row["edit_distance"] == 0.0


def test_record_edit_has_positive_distance(config):
    fs = FeedbackStore(config)
    row = fs.record(_task(ReviewAction.EDIT, final="Bạn được 12 ngày phép năm, báo trước 3 ngày."))
    assert row["label"] == "edited"
    assert row["edit_distance"] > 0.0
    assert row["gold"].endswith("3 ngày.")


def test_record_reject_has_empty_gold(config):
    fs = FeedbackStore(config)
    row = fs.record(_task(ReviewAction.REJECT, final="Vui lòng liên hệ HR."))
    assert row["label"] == "rejected"
    assert row["gold"] == ""


def test_export_jsonl_excludes_rejected(config, tmp_path):
    fs = FeedbackStore(config)
    fs.record(_task(ReviewAction.APPROVE))
    fs.record(_task(ReviewAction.REJECT, final="x"))
    out = tmp_path / "ds.jsonl"
    n = fs.export_jsonl(out)
    assert n == 1
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1
    assert set(lines[0]) == {"query", "context", "draft", "gold", "label"}
