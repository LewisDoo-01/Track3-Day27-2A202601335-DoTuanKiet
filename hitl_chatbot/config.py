"""Cấu hình tập trung cho toàn hệ thống HITL.

Mọi "con số ma thuật" (ngưỡng confidence, ngưỡng retrieval, thời gian SLA,
danh sách từ khoá nhạy cảm...) đều nằm ở đây để:
  - dễ tinh chỉnh policy mà không phải sửa code logic
  - test có thể override bằng cách truyền Config riêng

Giá trị đọc từ biến môi trường (file .env) nếu có, nếu không dùng mặc định.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Thư mục gốc của repo (…/Track3-Day27-...)
ROOT = Path(__file__).resolve().parent.parent

# Nạp .env thủ công (không phụ thuộc python-dotenv để phần lõi chạy được ngay)
_ENV_FILE = ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        # Không ghi đè biến đã có sẵn trong môi trường
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Từ khoá làm 1 câu hỏi trở thành "nhạy cảm" -> LUÔN chuyển người duyệt,
# bất kể bot tự tin đến đâu. Đây là "chốt chặn cứng" của HITL.
DEFAULT_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    # Lương/thưởng CÁ NHÂN (không chặn câu hỏi chính sách chung như "nghỉ không lương")
    "lương của tôi", "lương tháng", "phiếu lương", "bảng lương",
    "trừ lương", "tính lương", "mức lương", "tăng lương",
    "thưởng của tôi", "mức thưởng", "tiền thưởng",
    # Chấm dứt lao động / kỷ luật
    "sa thải", "sa thai", "đuổi việc", "kỷ luật", "ky luat", "chấm dứt hợp đồng",
    # Dữ liệu cá nhân / pháp lý
    "dữ liệu cá nhân", "du lieu ca nhan", "pii", "cccd", "cmnd", "căn cước",
    "hộ chiếu", "lộ lọt dữ liệu", "rò rỉ dữ liệu",
    "khiếu nại", "khieu nai", "tố cáo", "kiện", "pháp lý", "phap ly",
)

# Cụm từ cho thấy câu trả lời đề xuất 1 HÀNH ĐỘNG có tác dụng phụ
# (tạo ticket, reset mật khẩu, cấp quyền...) -> cần người xác nhận.
DEFAULT_ACTION_PHRASES: tuple[str, ...] = (
    "reset mật khẩu", "reset password", "đặt lại mật khẩu",
    "cấp quyền", "cấp cho tôi quyền", "grant access",
    "xoá tài khoản", "khoá tài khoản", "hoàn tiền", "refund",
)


@dataclass(frozen=True)
class Config:
    """Toàn bộ tham số điều khiển hành vi HITL."""

    # --- Ngưỡng định tuyến (routing) ---
    # confidence < ngưỡng này  -> chuyển người (bot không đủ chắc chắn)
    confidence_threshold: float = _get_float("HITL_CONFIDENCE_THRESHOLD", 0.60)
    # điểm retrieval cao nhất < ngưỡng này -> chuyển người (thiếu căn cứ)
    retrieval_threshold: float = _get_float("HITL_RETRIEVAL_THRESHOLD", 0.12)

    # --- SLA cho người duyệt ---
    # task PENDING quá số giây này mà chưa ai xử lý -> tự đóng bằng câu safe-default
    review_sla_seconds: int = _get_int("HITL_REVIEW_SLA_SECONDS", 900)  # 15 phút

    # --- Giả định để quy đổi ra "phút người tiết kiệm" trong report ---
    minutes_per_manual_answer: float = _get_float("HITL_MINUTES_PER_MANUAL_ANSWER", 4.0)

    # --- LLM ---
    llm_provider: str = os.environ.get("LLM_PROVIDER", "fake")  # "fake" | "openrouter"
    openrouter_model: str = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    openrouter_base_url: str = os.environ.get(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")

    # --- Đường dẫn dữ liệu ---
    kb_dir: Path = ROOT / "data" / "kb"
    state_dir: Path = ROOT / "data" / "state"

    # --- Từ điển rủi ro ---
    sensitive_keywords: tuple[str, ...] = DEFAULT_SENSITIVE_KEYWORDS
    action_phrases: tuple[str, ...] = DEFAULT_ACTION_PHRASES

    # Câu trả lời an toàn khi bot không chắc và không có người duyệt kịp
    safe_default_answer: str = (
        "Xin lỗi, câu hỏi này cần chuyên viên phụ trách xác nhận và hiện chưa có "
        "phản hồi kịp thời. Vui lòng liên hệ bộ phận HR/IT qua kênh hỗ trợ chính thức."
    )


def load_config(**overrides) -> Config:
    """Tạo Config, cho phép test override từng field."""
    base = Config()
    if not overrides:
        return base
    from dataclasses import replace

    return replace(base, **overrides)
