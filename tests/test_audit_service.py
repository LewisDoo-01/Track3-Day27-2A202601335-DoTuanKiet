"""Test audit_service — nhật ký append-only, truy vết theo trace_id."""

from __future__ import annotations

from hitl_chatbot.audit_service import AuditLog


def test_emit_records_required_fields(config):
    log = AuditLog(config)
    ev = log.emit("trc_a", "received", {"query": "xin chào"})
    assert ev["trace_id"] == "trc_a"
    assert ev["stage"] == "received"
    assert ev["payload"]["query"] == "xin chào"
    assert isinstance(ev["ts"], float)


def test_events_are_appended_not_overwritten(config, clock):
    log = AuditLog(config)
    log.emit("trc_a", "received")
    clock.advance(1)
    log.emit("trc_a", "retrieved")
    clock.advance(1)
    log.emit("trc_b", "received")
    assert len(log.all_events()) == 3


def test_events_for_returns_sorted_single_trace(config, clock):
    log = AuditLog(config)
    log.emit("trc_a", "received")
    clock.advance(5)
    log.emit("trc_b", "received")
    clock.advance(5)
    log.emit("trc_a", "routed")
    evs = log.events_for("trc_a")
    assert [e["stage"] for e in evs] == ["received", "routed"]
    assert evs[0]["ts"] < evs[1]["ts"]


def test_trace_ids_are_unique(config):
    log = AuditLog(config)
    for _ in range(3):
        log.emit("trc_a", "received")
    log.emit("trc_b", "received")
    assert sorted(log.trace_ids()) == ["trc_a", "trc_b"]
