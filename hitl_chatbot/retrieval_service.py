"""Retrieval service — tìm tài liệu liên quan trong Knowledge Base.

Cài đặt TF-IDF + cosine similarity THUẦN PYTHON (không sklearn/numpy) để:
  - repo nhẹ, không dependency nặng
  - đọc code thấy rõ retrieval hoạt động thế nào

Trong pipeline HITL, retrieval có 2 vai trò:
  1. Cung cấp context cho LLM trả lời (grounding).
  2. `top_score` là 1 tín hiệu để risk_policy quyết định: KB không có gì khớp
     nghĩa là bot đang "đoán" -> nên chuyển người.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .config import Config
from .models import DocHit

_WORD_RE = re.compile(r"[0-9a-zà-ỹ]+", re.IGNORECASE | re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Tách từ đơn giản, hạ chữ thường, giữ tiếng Việt có dấu."""
    return _WORD_RE.findall(text.lower())


class RetrievalService:
    def __init__(self, config: Config):
        self.config = config
        self._doc_ids: list[str] = []
        self._doc_texts: list[str] = []
        self._doc_tf: list[Counter] = []          # tần suất từ trong mỗi doc
        self._idf: dict[str, float] = {}
        self._load()

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        kb_dir: Path = self.config.kb_dir
        files = sorted(kb_dir.glob("*.md")) if kb_dir.exists() else []
        for f in files:
            text = f.read_text(encoding="utf-8")
            self._doc_ids.append(f.name)
            self._doc_texts.append(text)
            self._doc_tf.append(Counter(tokenize(text)))

        # IDF = log(N / số doc chứa từ)  (smooth +1 để không chia 0)
        n_docs = len(self._doc_ids)
        df: Counter = Counter()
        for tf in self._doc_tf:
            df.update(tf.keys())
        self._idf = {
            term: math.log((n_docs + 1) / (freq + 1)) + 1.0
            for term, freq in df.items()
        }

    # ------------------------------------------------------------------ #
    def _vector(self, tokens: list[str]) -> dict[str, float]:
        """Vector TF-IDF (dict thưa) của một túi từ."""
        tf = Counter(tokens)
        total = sum(tf.values()) or 1
        return {
            term: (count / total) * self._idf.get(term, 1.0)
            for term, count in tf.items()
        }

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    # ------------------------------------------------------------------ #
    def _snippet(self, doc_idx: int, query_tokens: set[str], width: int = 240) -> str:
        """Lấy đoạn văn quanh vị trí xuất hiện đầu tiên của 1 từ khoá."""
        text = self._doc_texts[doc_idx]
        low = text.lower()
        pos = -1
        for tok in query_tokens:
            p = low.find(tok)
            if p != -1 and (pos == -1 or p < pos):
                pos = p
        if pos == -1:
            return text[:width].strip()
        start = max(0, pos - width // 3)
        return text[start : start + width].strip()

    # ------------------------------------------------------------------ #
    def search(self, query: str, k: int = 3) -> list[DocHit]:
        """Trả về tối đa k tài liệu khớp nhất, sắp theo score giảm dần."""
        if not self._doc_ids:
            return []
        q_tokens = tokenize(query)
        q_vec = self._vector(q_tokens)
        scored: list[tuple[float, int]] = []
        for idx in range(len(self._doc_ids)):
            d_vec = self._vector(list(self._doc_tf[idx].elements()))
            scored.append((self._cosine(q_vec, d_vec), idx))
        scored.sort(reverse=True)

        hits: list[DocHit] = []
        qset = set(q_tokens)
        for score, idx in scored[:k]:
            if score <= 0.0:
                continue
            hits.append(
                DocHit(
                    doc_id=self._doc_ids[idx],
                    score=round(score, 4),
                    snippet=self._snippet(idx, qset),
                )
            )
        return hits

    @staticmethod
    def top_score(hits: list[DocHit]) -> float:
        return hits[0].score if hits else 0.0
