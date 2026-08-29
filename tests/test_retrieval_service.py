"""Test RetrievalService — TF-IDF trên KB."""

from __future__ import annotations

from hitl_chatbot.config import load_config
from hitl_chatbot.retrieval_service import RetrievalService, tokenize


def test_tokenize_keeps_vietnamese():
    assert tokenize("Nghỉ phép năm 2024") == ["nghỉ", "phép", "năm", "2024"]


def test_search_finds_relevant_doc(config):
    r = RetrievalService(config)
    hits = r.search("tôi được bao nhiêu ngày phép năm")
    assert hits, "phải có ít nhất 1 hit"
    assert hits[0].doc_id == "phep.md"
    assert hits[0].score > 0
    # hits sắp xếp giảm dần theo score
    assert all(a.score >= b.score for a, b in zip(hits, hits[1:]))


def test_snippet_contains_query_term(config):
    r = RetrievalService(config)
    hits = r.search("giờ hỗ trợ IT")
    assert hits[0].doc_id == "it.md"
    assert "hỗ trợ" in hits[0].snippet.lower()


def test_out_of_kb_query_has_low_top_score(config):
    r = RetrievalService(config)
    hits = r.search("chính sách nuôi mèo trong văn phòng công ty")
    # không có tài liệu nào nói về mèo -> hoặc rỗng, hoặc điểm rất thấp
    assert r.top_score(hits) < 0.15


def test_empty_kb_returns_nothing(tmp_path):
    cfg = load_config(kb_dir=tmp_path / "empty", state_dir=tmp_path / "s")
    (tmp_path / "empty").mkdir()
    r = RetrievalService(cfg)
    assert r.search("bất kỳ câu hỏi nào") == []
    assert r.top_score([]) == 0.0
