"""HITL Chatbot — thư viện minh hoạ quy trình Human-in-the-Loop chuẩn production.

Xem README.md để biết sơ đồ tổng quan và cách chạy.
Các service chính (mỗi file 1 trách nhiệm, có test riêng trong tests/):

    retrieval_service   -> tìm tài liệu liên quan trong Knowledge Base
    llm_service         -> sinh câu trả lời nháp + độ tự tin (confidence)
    risk_policy_service -> QUYẾT ĐỊNH: bot tự trả lời hay chuyển cho người
    review_queue_service-> hàng đợi duyệt (state machine + SLA + idempotency)
    feedback_store      -> lưu phản hồi của người duyệt làm dataset cải tiến
    audit_service       -> nhật ký append-only, truy vết mọi bước theo trace_id
    metrics_service     -> tổng hợp số liệu vận hành từ audit log
    orchestrator        -> ghép tất cả lại thành 1 pipeline handle_message()
"""

__version__ = "0.1.0"
