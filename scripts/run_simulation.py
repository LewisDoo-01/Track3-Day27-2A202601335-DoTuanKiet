"""Chạy mô phỏng vận hành HITL để sinh dữ liệu cho báo cáo.

Kịch bản:
  1. Xoá sạch state cũ (data/state/*.json).
  2. Đưa lần lượt các câu hỏi trong data/scenarios.jsonl qua orchestrator.
  3. Một "người duyệt giả lập" (deterministic) xử lý phần lớn hàng đợi:
        - approve nếu bot có căn cứ và đủ tự tin
        - edit    nếu có căn cứ nhưng chưa chắc  (thêm ghi chú an toàn)
        - reject  nếu bot đoán mò / ngoài phạm vi
     Một phần task cố tình BỎ QUA để minh hoạ SLA timeout.
  4. Tua đồng hồ vượt SLA -> sweep_sla() đóng số task tồn.

Đồng hồ dùng bản giả (models.set_clock) nên latency trong report là số có nghĩa
và TÁI LẬP được (seed cố định). Mặc định LLM = FakeLLM; thêm --live để gọi thật.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

# Windows: console mặc định cp1252 -> ép UTF-8 để in được tiếng Việt.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from hitl_chatbot import models  # noqa: E402
from hitl_chatbot.config import load_config  # noqa: E402
from hitl_chatbot.models import ReviewAction, TaskState  # noqa: E402
from hitl_chatbot.orchestrator import HITLOrchestrator  # noqa: E402

REVIEWERS = ["minh.hr", "lan.hr", "tuan.it"]


class FakeClock:
    """Đồng hồ giả: bắt đầu từ mốc cố định, chỉ tiến khi được bảo tiến."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def reset_state(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    for name in ("audit_log.json", "review_queue.json", "feedback.json"):
        (state_dir / name).write_text("[]", encoding="utf-8")


def simulated_reviewer_decision(task) -> tuple[ReviewAction, str | None, str | None]:
    """Quy tắc duyệt giả lập — cố định theo đặc điểm task."""
    d = task.draft
    if d.grounded and d.confidence >= 0.6:
        return ReviewAction.APPROVE, None, None
    if d.grounded and d.confidence >= 0.4:
        edited = (
            d.text
            + "\n\n[Chuyên viên bổ sung] Nếu trường hợp của bạn khác thông tin trên, "
            "vui lòng liên hệ HR/IT để được tư vấn riêng."
        )
        return ReviewAction.EDIT, edited, "bổ sung lưu ý, câu nháp chưa đủ ngữ cảnh"
    return ReviewAction.REJECT, None, "ngoài phạm vi KB, cần chuyển kênh chuyên trách"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-review-every", type=int, default=5,
                    help="cứ N task thì bỏ 1 task không duyệt (minh hoạ SLA)")
    ap.add_argument("--live", action="store_true", help="gọi LLM thật qua OpenRouter")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    clock = FakeClock()
    models.set_clock(clock)

    # Ép provider bằng override tường minh (không phụ thuộc thứ tự import .env)
    config = load_config(llm_provider="openrouter" if args.live else "fake")
    reset_state(config.state_dir)
    orch = HITLOrchestrator(config)

    scenarios = [
        json.loads(line)
        for line in (ROOT / "data" / "scenarios.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    pending_task_ids: list[str] = []
    routing_rows: list[dict] = []
    for i, sc in enumerate(scenarios):
        clock.advance(rng.uniform(20, 90))  # user đến rải rác
        resp = orch.handle_message(sc["user"], sc["query"])
        got = resp.route.value
        ok = got == sc["expected_route"]
        routing_rows.append(
            {"id": sc["id"], "query": sc["query"], "expected": sc["expected_route"],
             "got": got, "match": ok, "note": sc.get("note", "")}
        )
        print(f"{sc['id']:>4}  {got:9}  (expected {sc['expected_route']:9})  {sc['query'][:52]}")
        if resp.task_id:
            pending_task_ids.append(resp.task_id)

    routed_correct = sum(r["match"] for r in routing_rows)

    # --- Người duyệt giả lập xử lý hàng đợi --------------------------- #
    reviewed = skipped = 0
    for idx, task_id in enumerate(pending_task_ids):
        if args.skip_review_every and idx % args.skip_review_every == args.skip_review_every - 1:
            skipped += 1
            continue
        reviewer = rng.choice(REVIEWERS)
        clock.advance(rng.uniform(20, 150))         # chờ trong hàng đợi
        orch.claim_review(task_id, reviewer)
        clock.advance(rng.uniform(40, 240))         # thời gian đọc + xử lý
        task = orch.queue.get(task_id)
        action, edited, reason = simulated_reviewer_decision(task)
        orch.resolve_review(
            task_id, reviewer=reviewer, action=action, edited_text=edited, reason=reason
        )
        reviewed += 1

    # --- Tua vượt SLA rồi quét ------------------------------------- #
    clock.advance(config.review_sla_seconds + 60)
    expired = orch.sweep_sla()

    models.set_clock(None)

    n = len(scenarios)
    (config.state_dir / "routing_eval.json").write_text(
        json.dumps(
            {
                "total": n,
                "correct": routed_correct,
                "accuracy_pct": round(100 * routed_correct / n, 2),
                "mismatches": [r for r in routing_rows if not r["match"]],
                "rows": routing_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n" + "=" * 60)
    print(f"Hội thoại              : {n}")
    print(f"Routing khớp kỳ vọng   : {routed_correct}/{n} ({routed_correct / n:.0%})")
    print(f"Task chuyển người      : {len(pending_task_ids)}")
    print(f"  - đã duyệt            : {reviewed}")
    print(f"  - bỏ qua -> SLA close : {len(expired)} (cố tình bỏ {skipped})")
    print(f"State: {config.state_dir}")
    print("Chạy tiếp: python scripts/generate_report.py")


if __name__ == "__main__":
    main()
