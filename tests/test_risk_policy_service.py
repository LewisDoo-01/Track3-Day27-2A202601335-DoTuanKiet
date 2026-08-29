"""Test risk_policy_service — logic quyết định AUTO vs ESCALATE."""

from __future__ import annotations

from hitl_chatbot.models import DocHit, DraftAnswer, Route
from hitl_chatbot.risk_policy_service import RiskPolicyService


def _draft(conf=0.9, grounded=True, text="Bạn được 12 ngày phép năm."):
    return DraftAnswer(text=text, confidence=conf, citations=["phep.md"], grounded=grounded)


def _hits(score=0.4):
    return [DocHit("phep.md", score, "12 ngày phép năm")]


def test_normal_question_is_auto(config):
    d = RiskPolicyService(config).decide("tôi được mấy ngày phép năm", _draft(), _hits())
    assert d.route == Route.AUTO
    assert d.reasons == []
    assert d.risk_score == 0.0


def test_sensitive_keyword_always_escalates_even_if_confident(config):
    # confidence 0.99, có căn cứ tốt — nhưng hỏi về "lương" -> vẫn phải qua người
    d = RiskPolicyService(config).decide(
        "phiếu lương của tôi gửi qua đâu", _draft(conf=0.99), _hits(0.6)
    )
    assert d.route == Route.ESCALATE
    assert any(r.startswith("sensitive_topic") for r in d.reasons)


def test_low_confidence_escalates(config):
    d = RiskPolicyService(config).decide("câu hỏi mơ hồ", _draft(conf=0.3), _hits())
    assert d.route == Route.ESCALATE
    assert any(r.startswith("low_confidence") for r in d.reasons)


def test_weak_grounding_escalates(config):
    d = RiskPolicyService(config).decide("hỏi ngoài KB", _draft(grounded=False), [])
    assert d.route == Route.ESCALATE
    assert any(r.startswith("weak_grounding") for r in d.reasons)


def test_action_phrase_escalates(config):
    d = RiskPolicyService(config).decide(
        "làm sao để reset mật khẩu", _draft(text="Bạn cần reset mật khẩu qua IT."), _hits()
    )
    assert d.route == Route.ESCALATE
    assert any(r.startswith("action_required") for r in d.reasons)


def test_risk_score_increases_with_more_reasons(config):
    svc = RiskPolicyService(config)
    one = svc.decide("câu mơ hồ", _draft(conf=0.3), _hits())
    many = svc.decide("lương của tôi", _draft(conf=0.2, grounded=False), [])
    assert many.risk_score >= one.risk_score > 0.0
    assert many.risk_score <= 1.0
