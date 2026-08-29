"""Web UI cho HITL Chatbot — dùng để deploy lên Streamlit Community Cloud.

3 vai trò trên cùng 1 trang (chọn qua tab):
  - Người dùng cuối : gửi câu hỏi, xem bot trả lời hoặc "đang chờ duyệt".
  - Người duyệt     : xem hàng đợi, mở 1 task, approve / edit / reject.
  - Vận hành        : xem số liệu HITL realtime, quét SLA, seed dữ liệu demo.

State (data/state/*.json) nằm trên container của Streamlit Cloud — đủ cho demo,
sẽ reset khi app redeploy/reboot.

Chạy local:   streamlit run streamlit_app.py
"""

from __future__ import annotations

import os

import streamlit as st

# --------------------------------------------------------------------------- #
# 1. Đưa secrets -> biến môi trường TRƯỚC khi import hitl_chatbot
#    (config.py đọc env ngay lúc import).
# --------------------------------------------------------------------------- #
def _bootstrap_env() -> None:
    try:
        for key in (
            "OPENROUTER_API_KEY",
            "OPENROUTER_MODEL",
            "OPENROUTER_BASE_URL",
            "LLM_PROVIDER",
            "HITL_CONFIDENCE_THRESHOLD",
            "HITL_RETRIEVAL_THRESHOLD",
            "HITL_REVIEW_SLA_SECONDS",
        ):
            if key in st.secrets:
                os.environ.setdefault(key, str(st.secrets[key]))
    except Exception:
        pass  # không có secrets.toml khi chạy local -> bỏ qua

    if not os.environ.get("LLM_PROVIDER"):
        os.environ["LLM_PROVIDER"] = (
            "openrouter" if os.environ.get("OPENROUTER_API_KEY") else "fake"
        )


_bootstrap_env()

from hitl_chatbot.models import ReviewAction, Route, TaskState  # noqa: E402
from hitl_chatbot.orchestrator import HITLOrchestrator  # noqa: E402

SCENARIOS_FILE = os.path.join(os.path.dirname(__file__), "data", "scenarios.jsonl")


@st.cache_resource
def get_orch() -> HITLOrchestrator:
    return HITLOrchestrator()


orch = get_orch()

st.set_page_config(page_title="HITL Chatbot", page_icon="🧑‍⚖️", layout="wide")

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.title("🧑‍⚖️ HITL Chatbot")
    st.caption("Human-in-the-Loop — quy trình vận hành production")

    cfg = orch.config
    provider = cfg.llm_provider
    if provider == "openrouter" and not cfg.openrouter_api_key:
        st.warning("LLM_PROVIDER=openrouter nhưng thiếu API key → đang dùng FakeLLM.")
        provider = "fake (fallback)"
    st.markdown(
        f"""
| Cấu hình | Giá trị |
|---|---|
| LLM | `{provider}` |
| model | `{cfg.openrouter_model}` |
| confidence ≥ | `{cfg.confidence_threshold}` |
| retrieval ≥ | `{cfg.retrieval_threshold}` |
| SLA | `{cfg.review_sla_seconds}s` |
"""
    )

    st.session_state.setdefault("reviewer", "minh.hr")
    st.session_state["reviewer"] = st.text_input(
        "Tên người duyệt (dùng ở tab Hàng đợi)", st.session_state["reviewer"]
    )

    st.divider()
    if st.button("🌱 Seed dữ liệu demo (chạy scenarios)", use_container_width=True):
        import json

        n = 0
        with open(SCENARIOS_FILE, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                sc = json.loads(line)
                orch.handle_message(sc["user"], sc["query"])
                n += 1
        st.success(f"Đã đưa {n} câu hỏi qua pipeline.")
        st.rerun()

    if st.button("⏰ Quét SLA (đóng task quá hạn)", use_container_width=True):
        expired = orch.sweep_sla()
        st.info(f"Đã đóng {len(expired)} task quá hạn.")
        st.rerun()

    if st.button("🗑️ Xoá toàn bộ state", use_container_width=True):
        for name in ("audit_log.json", "review_queue.json", "feedback.json"):
            (cfg.state_dir / name).write_text("[]", encoding="utf-8")
        st.cache_resource.clear()
        st.rerun()

tab_chat, tab_review, tab_metrics, tab_about = st.tabs(
    ["💬 Chat", "🧑‍⚖️ Hàng đợi duyệt", "📊 Số liệu", "ℹ️ Giới thiệu"]
)

# --------------------------------------------------------------------------- #
# Tab 1 — Chat (người dùng cuối)
# --------------------------------------------------------------------------- #
with tab_chat:
    st.subheader("Người dùng hỏi")
    st.session_state.setdefault("history", [])

    col_u, col_send = st.columns([4, 1])
    user = col_u.text_input("Mã nhân viên", "an.nguyen", key="chat_user")
    examples = [
        "Tôi được bao nhiêu ngày phép năm?",
        "Phiếu lương của tôi gửi qua đâu?",
        "Tôi muốn khiếu nại quyết định kỷ luật thì làm sao?",
        "Công ty có chính sách cho mang thú cưng đến văn phòng không?",
    ]
    picked = st.selectbox("Câu hỏi mẫu (hoặc tự gõ bên dưới)", [""] + examples)
    msg = st.text_area("Câu hỏi", value=picked, key="chat_msg", height=80)

    if st.button("Gửi", type="primary") and msg.strip():
        resp = orch.handle_message(user, msg.strip())
        st.session_state["history"].insert(0, resp.to_dict())
        st.rerun()

    for item in st.session_state["history"]:
        route = item["route"]
        if item["status"] == "answered":
            st.success(f"**Bot trả lời tự động** · route=`{route}` · trace `{item['trace_id']}`")
        else:
            st.warning(
                f"**Đang chờ chuyên viên xác nhận** · task `{item['task_id']}` · "
                f"trace `{item['trace_id']}`"
            )
        st.markdown(item["answer"])
        st.divider()

# --------------------------------------------------------------------------- #
# Tab 2 — Hàng đợi duyệt (người duyệt)
# --------------------------------------------------------------------------- #
with tab_review:
    reviewer = st.session_state["reviewer"]
    st.subheader(f"Hàng đợi duyệt — đang thao tác với tư cách `{reviewer}`")

    state_filter = st.radio(
        "Lọc", ["pending", "in_review", "resolved", "all"], horizontal=True
    )
    st_enum = None if state_filter == "all" else TaskState(state_filter)
    tasks = orch.queue.list(st_enum)

    if not tasks:
        st.info("Không có task nào.")
    for t in tasks:
        risk = t.decision.risk_score
        head = f"`{t.id}` · risk **{risk:.2f}** · {t.state.value} · {t.user}: {t.query[:70]}"
        with st.expander(head, expanded=(t.state != TaskState.RESOLVED and len(tasks) <= 3)):
            st.markdown(f"**Câu hỏi:** {t.query}")
            st.markdown(
                f"**Định tuyến:** `{t.decision.route.value}` — lý do: "
                + ", ".join(f"`{r}`" for r in t.decision.reasons)
            )
            st.markdown("**Câu nháp của bot:**")
            st.info(t.draft.text)
            st.caption(
                f"confidence={t.draft.confidence:.2f} · grounded={t.draft.grounded} "
                f"· citations={t.draft.citations}"
            )
            with st.popover("📄 Xem context (KB hits)"):
                for h in t.hits:
                    st.markdown(f"**{h.doc_id}** · score {h.score:.3f}")
                    st.caption(h.snippet)

            if t.state == TaskState.RESOLVED:
                st.success(
                    f"Đã xử lý: **{t.action.value}** bởi `{t.assignee}`"
                    + (f" — lý do: {t.reviewer_reason}" if t.reviewer_reason else "")
                )
                st.markdown("**Câu trả lời cuối:**")
                st.markdown(t.final_answer or "")
                continue

            # --- hành động ---
            if t.state == TaskState.PENDING:
                if st.button("✋ Nhận task (claim)", key=f"claim_{t.id}"):
                    try:
                        orch.claim_review(t.id, reviewer)
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                continue

            # t.state == IN_REVIEW
            st.markdown(f"_Đang được `{t.assignee}` xử lý._")
            action = st.radio(
                "Hành động", ["approve", "edit", "reject"], horizontal=True, key=f"act_{t.id}"
            )
            edited = reason = None
            if action == "edit":
                edited = st.text_area(
                    "Câu trả lời đã sửa", value=t.draft.text, key=f"edit_{t.id}", height=140
                )
                reason = st.text_input("Lý do sửa (bắt buộc)", key=f"rsn_e_{t.id}")
            elif action == "reject":
                reason = st.text_input("Lý do từ chối (bắt buộc)", key=f"rsn_r_{t.id}")

            if st.button("💾 Chốt", type="primary", key=f"resolve_{t.id}"):
                try:
                    done = orch.resolve_review(
                        t.id,
                        reviewer=reviewer,
                        action=ReviewAction(action),
                        edited_text=edited,
                        reason=reason,
                    )
                    st.success(f"Đã chốt: {done.action.value}")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

# --------------------------------------------------------------------------- #
# Tab 3 — Số liệu
# --------------------------------------------------------------------------- #
with tab_metrics:
    st.subheader("Số liệu vận hành HITL (realtime, tính từ audit log)")
    m = orch.metrics.compute()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tổng hội thoại", m["total_conversations"])
    c2.metric("Tự động hoá", f'{m["automation_rate_pct"]}%')
    c3.metric("Chuyển người", f'{m["escalation_rate_pct"]}%')
    c4.metric("Phút người tiết kiệm", m["est_human_minutes_saved"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Approve", f'{m["approve_rate_pct"]}%')
    c2.metric("Edit", f'{m["edit_rate_pct"]}%')
    c3.metric("Reject", f'{m["reject_rate_pct"]}%')
    c4.metric("SLA breach", f'{m["sla_breach_rate_pct"]}%')

    c1, c2, c3 = st.columns(3)
    c1.metric("Review latency P50", f'{m["review_latency_sec_p50"]:.0f}s')
    c2.metric("Review latency P95", f'{m["review_latency_sec_p95"]:.0f}s')
    c3.metric("Edit-distance TB", m["avg_edit_distance"])

    with st.expander("JSON đầy đủ"):
        st.json(m)

    st.caption(
        "Tái lập offline: `python scripts/run_simulation.py --seed 42 && "
        "python scripts/generate_report.py`"
    )

# --------------------------------------------------------------------------- #
# Tab 4 — Giới thiệu
# --------------------------------------------------------------------------- #
with tab_about:
    st.markdown(
        """
### Quy trình HITL

```
User → retrieval → LLM (nháp + confidence) → risk_policy
        │                                        │
        │                              AUTO ─────┴───── ESCALATE
        │                               │                  │
        │                         trả lời ngay      hàng đợi duyệt
        │                                            (claim → approve/edit/reject
        │                                             hoặc quá SLA → safe-default)
        └──────────────── audit log (trace_id) ─────────────┘
                                  │
                            metrics + feedback dataset
```

**9 pattern minh hoạ:** confidence-gated autonomy · risk-based routing (chốt chặn
cứng cho chủ đề nhạy cảm) · review queue state machine · SLA timeout fallback ·
reviewer approve/edit/reject có lý do · audit trail append-only · feedback loop →
dataset · idempotency · metrics vận hành.

Mã nguồn: `hitl_chatbot/` (mỗi service 1 file, có test riêng trong `tests/`).
"""
    )
