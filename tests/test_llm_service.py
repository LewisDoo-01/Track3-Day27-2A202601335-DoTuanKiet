"""Test llm_service — FakeLLM + factory build_llm."""

from __future__ import annotations

from dataclasses import replace

from hitl_chatbot.llm_service import FakeLLM, build_llm
from hitl_chatbot.models import DocHit
from hitl_chatbot.retrieval_service import RetrievalService


def test_fake_llm_grounded_when_hits(config):
    hits = RetrievalService(config).search("ngày phép năm")
    draft = FakeLLM(config).draft("ngày phép năm", hits)
    assert draft.grounded is True
    assert draft.citations
    assert 0.0 <= draft.confidence <= 1.0


def test_fake_llm_ungrounded_without_hits(config):
    draft = FakeLLM(config).draft("câu hỏi vu vơ", [])
    assert draft.grounded is False
    assert draft.citations == []
    assert draft.confidence < 0.5


def test_fake_llm_is_deterministic(config):
    hits = [DocHit("phep.md", 0.4, "12 ngày phép năm, báo trước 3 ngày")]
    a = FakeLLM(config).draft("phép năm", hits)
    b = FakeLLM(config).draft("phép năm", hits)
    assert a.to_dict() == b.to_dict()


def test_confidence_higher_with_better_retrieval(config):
    weak = [DocHit("phep.md", 0.03, "…")]
    strong = [DocHit("phep.md", 0.5, "nhân viên được 12 ngày phép năm báo trước 3 ngày")]
    c_weak = FakeLLM(config).draft("phép năm báo trước", weak).confidence
    c_strong = FakeLLM(config).draft("phép năm báo trước", strong).confidence
    assert c_strong > c_weak


def test_build_llm_defaults_to_fake(config):
    assert isinstance(build_llm(config), FakeLLM)


def test_build_llm_openrouter_without_key_falls_back(config):
    cfg = replace(config, llm_provider="openrouter", openrouter_api_key="")
    assert isinstance(build_llm(cfg), FakeLLM)
