"""Fixtures dùng chung cho test.

Nguyên tắc:
  - Mỗi test có state_dir riêng (tmp_path) -> không đụng data/state thật, chạy song song được.
  - LLM luôn là FakeLLM -> offline, deterministic, không tốn API.
  - Đồng hồ: test nào cần điều khiển thời gian thì dùng fixture `clock`;
    fixture autouse `_reset_clock` đảm bảo trả về đồng hồ thật sau mỗi test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hitl_chatbot import models  # noqa: E402
from hitl_chatbot.config import load_config  # noqa: E402
from hitl_chatbot.orchestrator import HITLOrchestrator  # noqa: E402

# KB nhỏ, cố định — 1 doc thường + 1 doc chạm từ khoá nhạy cảm ("lương").
_KB = {
    "phep.md": (
        "# Nghỉ phép năm\n"
        "Nhân viên chính thức được 12 ngày phép năm. "
        "Khi xin nghỉ phép cần báo quản lý trước 3 ngày làm việc. "
        "Phép năm được cộng dồn tối đa 5 ngày sang năm sau."
    ),
    "luong.md": (
        "# Lương\n"
        "Lương được trả một lần mỗi tháng vào ngày làm việc cuối cùng. "
        "Phiếu lương gửi qua email nội bộ."
    ),
    "it.md": (
        "# IT Support\n"
        "Giờ hỗ trợ IT là thứ 2 đến thứ 6, từ 8:30 đến 18:00. "
        "Máy tính hỏng sẽ được cấp máy dự phòng trong 1 ngày làm việc."
    ),
}


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    d = tmp_path / "kb"
    d.mkdir()
    for name, text in _KB.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def config(kb_dir: Path, state_dir: Path):
    return load_config(
        kb_dir=kb_dir,
        state_dir=state_dir,
        llm_provider="fake",
        review_sla_seconds=100,
        confidence_threshold=0.70,
        retrieval_threshold=0.05,
    )


@pytest.fixture
def real_kb_config(state_dir: Path):
    """Dùng KB thật trong data/kb cho test end-to-end."""
    return load_config(
        state_dir=state_dir,
        llm_provider="fake",
        review_sla_seconds=100,
    )


@pytest.fixture
def orch(config) -> HITLOrchestrator:
    return HITLOrchestrator(config)


class Clock:
    def __init__(self, start: float = 1_700_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> "Clock":
        self.t += seconds
        return self


@pytest.fixture
def clock() -> Clock:
    c = Clock()
    models.set_clock(c)
    return c


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    models.set_clock(None)
