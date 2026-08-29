"""FastAPI cho HITL chatbot — 2 nhóm endpoint.

NGƯỜI DÙNG CUỐI
  POST /chat                      gửi câu hỏi -> answered | pending_review

NGƯỜI DUYỆT (reviewer console / tích hợp hệ thống khác)
  GET  /reviews                   danh sách task (mặc định: đang chờ)
  GET  /reviews/{id}              chi tiết 1 task (kèm context để duyệt)
  POST /reviews/{id}/claim        nhận task
  POST /reviews/{id}/resolve      approve | edit | reject
  POST /reviews/sweep-sla         đóng các task quá hạn (thường do cron gọi)

VẬN HÀNH
  GET  /metrics                   số liệu HITL realtime

Chạy:  uvicorn app:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from hitl_chatbot.models import ReviewAction, TaskState
from hitl_chatbot.orchestrator import HITLOrchestrator
from hitl_chatbot.review_queue_service import QueueError

app = FastAPI(title="HITL Chatbot", version="0.1.0")
orch = HITLOrchestrator()


# --------------------------- schema request --------------------------- #
class ChatIn(BaseModel):
    user: str = Field(..., examples=["an.nguyen"])
    message: str = Field(..., examples=["Tôi được bao nhiêu ngày phép năm?"])


class ClaimIn(BaseModel):
    reviewer: str


class ResolveIn(BaseModel):
    reviewer: str
    action: ReviewAction
    edited_text: str | None = None
    reason: str | None = None


# --------------------------- endpoints -------------------------------- #
@app.post("/chat")
def chat(body: ChatIn):
    resp = orch.handle_message(body.user, body.message)
    return resp.to_dict()


@app.get("/reviews")
def list_reviews(state: str = "pending"):
    st = None if state == "all" else TaskState(state)
    return [t.to_dict() for t in orch.queue.list(st)]


@app.get("/reviews/{task_id}")
def get_review(task_id: str):
    task = orch.queue.get(task_id)
    if task is None:
        raise HTTPException(404, f"không có task {task_id}")
    return task.to_dict()


@app.post("/reviews/{task_id}/claim")
def claim_review(task_id: str, body: ClaimIn):
    try:
        return orch.claim_review(task_id, body.reviewer).to_dict()
    except QueueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/reviews/{task_id}/resolve")
def resolve_review(task_id: str, body: ResolveIn):
    try:
        task = orch.resolve_review(
            task_id,
            reviewer=body.reviewer,
            action=body.action,
            edited_text=body.edited_text,
            reason=body.reason,
        )
        return task.to_dict()
    except QueueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/reviews/sweep-sla")
def sweep_sla():
    return [t.to_dict() for t in orch.sweep_sla()]


@app.get("/metrics")
def metrics():
    return orch.metrics.compute()
