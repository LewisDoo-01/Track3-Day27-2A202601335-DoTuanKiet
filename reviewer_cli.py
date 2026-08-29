"""Dashboard dòng lệnh cho người duyệt (Human-in-the-Loop console).

    python reviewer_cli.py list                      # xem hàng đợi đang chờ
    python reviewer_cli.py show   <task_id>          # xem chi tiết + context
    python reviewer_cli.py claim  <task_id> --by minh
    python reviewer_cli.py approve <task_id> --by minh
    python reviewer_cli.py edit   <task_id> --by minh --text "..." --reason "..."
    python reviewer_cli.py reject <task_id> --by minh --reason "..."
    python reviewer_cli.py sweep-sla                 # đóng task quá hạn
    python reviewer_cli.py metrics

Dùng chung state (data/state/*.json) với FastAPI, nên có thể vừa chạy server
vừa duyệt bằng CLI.
"""

from __future__ import annotations

import argparse
import sys

# Windows: console mặc định cp1252 -> ép UTF-8 để in được tiếng Việt.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hitl_chatbot.models import ReviewAction, TaskState
from hitl_chatbot.orchestrator import HITLOrchestrator
from hitl_chatbot.review_queue_service import QueueError

console = Console()
orch = HITLOrchestrator()


def cmd_list(args):
    state = None if args.state == "all" else TaskState(args.state)
    tasks = orch.queue.list(state)
    table = Table(title=f"Review queue ({args.state})")
    for col in ("task_id", "risk", "state", "assignee", "user", "query", "reasons"):
        table.add_column(col, overflow="fold")
    for t in tasks:
        table.add_row(
            t.id,
            f"{t.decision.risk_score:.2f}",
            t.state.value,
            t.assignee or "-",
            t.user,
            t.query[:60],
            ", ".join(r.split(":")[0] for r in t.decision.reasons),
        )
    console.print(table)
    if not tasks:
        console.print("[dim]— hàng đợi trống —[/dim]")


def cmd_show(args):
    t = orch.queue.get(args.task_id)
    if not t:
        console.print(f"[red]Không có task {args.task_id}[/red]")
        return
    console.print(Panel(t.query, title=f"[bold]{t.id}[/bold] — user: {t.user}"))
    console.print(
        f"[cyan]Route[/cyan] {t.decision.route.value}  "
        f"[cyan]risk[/cyan] {t.decision.risk_score:.2f}  "
        f"[cyan]lý do[/cyan] {t.decision.reasons}"
    )
    console.print(
        Panel(
            f"{t.draft.text}\n\n[dim]confidence={t.draft.confidence:.2f} "
            f"grounded={t.draft.grounded} citations={t.draft.citations}[/dim]",
            title="Câu nháp của bot",
        )
    )
    ctx = Table(title="Context (KB hits)")
    ctx.add_column("doc_id")
    ctx.add_column("score")
    ctx.add_column("snippet", overflow="fold")
    for h in t.hits:
        ctx.add_row(h.doc_id, f"{h.score:.3f}", h.snippet[:200])
    console.print(ctx)
    console.print(f"[dim]state={t.state.value} assignee={t.assignee}[/dim]")


def _resolve(args, action: ReviewAction, edited_text=None, reason=None):
    try:
        t = orch.resolve_review(
            args.task_id,
            reviewer=args.by,
            action=action,
            edited_text=edited_text,
            reason=reason,
        )
        console.print(
            Panel(t.final_answer or "", title=f"[green]{action.value.upper()}[/green] "
                  f"-> câu trả lời cuối cho {t.user}")
        )
    except QueueError as exc:
        console.print(f"[red]Lỗi:[/red] {exc}")


def cmd_claim(args):
    try:
        t = orch.claim_review(args.task_id, args.by)
        console.print(f"[green]{args.by} đã nhận {t.id}[/green]")
    except QueueError as exc:
        console.print(f"[red]Lỗi:[/red] {exc}")


def cmd_approve(args):
    _resolve(args, ReviewAction.APPROVE)


def cmd_edit(args):
    _resolve(args, ReviewAction.EDIT, edited_text=args.text, reason=args.reason)


def cmd_reject(args):
    _resolve(args, ReviewAction.REJECT, reason=args.reason)


def cmd_sweep(args):
    expired = orch.sweep_sla()
    console.print(f"Đã đóng {len(expired)} task quá hạn: {[t.id for t in expired]}")


def cmd_metrics(args):
    data = orch.metrics.compute()
    table = Table(title="HITL metrics")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for k, v in data.items():
        table.add_row(k, str(v))
    console.print(table)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HITL reviewer console")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list"); s.add_argument("--state", default="pending",
        choices=["pending", "in_review", "resolved", "all"]); s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show"); s.add_argument("task_id"); s.set_defaults(fn=cmd_show)

    s = sub.add_parser("claim"); s.add_argument("task_id"); s.add_argument("--by", required=True)
    s.set_defaults(fn=cmd_claim)

    s = sub.add_parser("approve"); s.add_argument("task_id"); s.add_argument("--by", required=True)
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("edit"); s.add_argument("task_id"); s.add_argument("--by", required=True)
    s.add_argument("--text", required=True); s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_edit)

    s = sub.add_parser("reject"); s.add_argument("task_id"); s.add_argument("--by", required=True)
    s.add_argument("--reason", required=True); s.set_defaults(fn=cmd_reject)

    s = sub.add_parser("sweep-sla"); s.set_defaults(fn=cmd_sweep)
    s = sub.add_parser("metrics"); s.set_defaults(fn=cmd_metrics)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.fn(args)
