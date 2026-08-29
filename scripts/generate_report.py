"""Sinh báo cáo số liệu từ state hiện tại (chạy sau run_simulation.py).

Tạo ra trong reports/:
  metrics.json        số liệu dạng máy đọc
  metrics.csv         số liệu dạng bảng
  final_report.md     báo cáo có nhận xét tự động
  feedback_dataset.jsonl  tập (query, context, draft, gold) để eval/fine-tune
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from hitl_chatbot.config import load_config  # noqa: E402
from hitl_chatbot.orchestrator import HITLOrchestrator  # noqa: E402

REPORTS = ROOT / "reports"


def _auto_comment(m: dict) -> str:
    lines: list[str] = []
    aut = m["automation_rate_pct"]
    lines.append(
        f"- Bot tự xử lý **{aut}%** hội thoại, còn **{m['escalation_rate_pct']}%** "
        f"phải chuyển người."
    )
    if m["escalated"]:
        lines.append(
            f"- Trong số ca chuyển người: approve {m['approve_rate_pct']}%, "
            f"edit {m['edit_rate_pct']}%, reject {m['reject_rate_pct']}%."
        )
        if m["approve_rate_pct"] >= 60:
            lines.append(
                "- Tỉ lệ approve nguyên văn cao ⇒ câu nháp của bot khá tốt; có thể "
                "cân nhắc **hạ nhẹ ngưỡng confidence** để tăng tự động hoá — nhưng "
                "GIỮ NGUYÊN chốt chặn cứng cho chủ đề nhạy cảm."
            )
        if m["reject_rate_pct"] >= 25:
            lines.append(
                "- Tỉ lệ reject cao ⇒ nhiều câu hỏi ngoài phạm vi KB. Nên **bổ sung "
                "tài liệu** hoặc thêm câu định tuyến sang kênh khác sớm hơn."
            )
    if m["sla_timeout_count"]:
        lines.append(
            f"- Có **{m['sla_timeout_count']}** ca vượt SLA "
            f"({m['sla_breach_rate_pct']}%) — cần thêm người trực hoặc kéo dài SLA/"
            "định tuyến lại."
        )
    lines.append(
        f"- Ước tính tiết kiệm **{m['est_human_minutes_saved']} phút** công xử lý thủ công."
    )
    lines.append(
        f"- Latency duyệt: P50 {m['review_latency_sec_p50']}s / "
        f"P95 {m['review_latency_sec_p95']}s. Edit-distance TB {m['avg_edit_distance']}."
    )
    return "\n".join(lines)


def _routing_section(state_dir) -> str:
    import json
    from pathlib import Path

    f = Path(state_dir) / "routing_eval.json"
    if not f.exists():
        return "_(chưa có — chạy `python scripts/run_simulation.py`)_"
    data = json.loads(f.read_text(encoding="utf-8"))
    lines = [
        f"Độ chính xác định tuyến so với nhãn tay: "
        f"**{data['correct']}/{data['total']} ({data['accuracy_pct']}%)**.",
        "",
    ]
    if data["mismatches"]:
        lines.append("| id | câu hỏi | kỳ vọng | thực tế | ghi chú |")
        lines.append("|----|---------|---------|---------|---------|")
        for r in data["mismatches"]:
            lines.append(
                f"| {r['id']} | {r['query'][:50]} | {r['expected']} | {r['got']} | {r['note'][:80]} |"
            )
    else:
        lines.append("Không có ca lệch nhãn.")
    return "\n".join(lines)


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    # Report chỉ đọc state, không gọi LLM -> ép fake để không cần API key.
    config = load_config(llm_provider="fake")
    orch = HITLOrchestrator(config)

    m = orch.metrics.to_json(REPORTS / "metrics.json")
    orch.metrics.to_csv(REPORTS / "metrics.csv")
    n_ds = orch.feedback.export_jsonl(REPORTS / "feedback_dataset.jsonl")

    rows = "\n".join(f"| `{k}` | {v} |" for k, v in m.items())
    report = f"""# Báo cáo số liệu — HITL Chatbot

> Sinh tự động bởi `scripts/generate_report.py` từ `data/state/audit_log.json`.
> Cấu hình: confidence_threshold={config.confidence_threshold}, \
retrieval_threshold={config.retrieval_threshold}, SLA={config.review_sla_seconds}s.

## Bảng số liệu

| Metric | Value |
|--------|-------|
{rows}

## Chất lượng định tuyến (routing)

{_routing_section(config.state_dir)}

## Nhận xét tự động

{_auto_comment(m)}

## Dataset phản hồi

Đã xuất **{n_ds}** mẫu vào `reports/feedback_dataset.jsonl`
(các trường: query, context, draft, gold, label) — dùng cho eval hồi quy hoặc fine-tune.

## Cách tái lập

```bash
python scripts/run_simulation.py --seed 42
python scripts/generate_report.py
```
"""
    (REPORTS / "final_report.md").write_text(report, encoding="utf-8")
    print("Đã ghi: reports/metrics.json, metrics.csv, final_report.md, feedback_dataset.jsonl")
    for k, v in m.items():
        print(f"  {k:32} {v}")


if __name__ == "__main__":
    main()
