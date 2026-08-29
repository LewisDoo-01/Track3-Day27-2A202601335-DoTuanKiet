"""LLM service — sinh câu trả lời nháp + độ tự tin (confidence).

Hai backend, CÙNG interface `draft(query, hits) -> DraftAnswer`:

  FakeLLM       : deterministic, không cần mạng. Dùng cho TOÀN BỘ test và
                  mặc định trong run_simulation.py (report tái lập được).
  OpenRouterLLM : gọi thật qua OpenRouter (OpenAI-compatible), model
                  google/gemini-2.5-flash. Bật bằng LLM_PROVIDER=openrouter.

confidence được tính thế nào?
  - FakeLLM: từ điểm retrieval + độ phủ từ khoá -> heuristic minh bạch.
  - OpenRouter: yêu cầu model tự chấm 0..1 và trả kèm JSON; nếu parse lỗi thì
    fallback về heuristic giống FakeLLM. Điểm mấu chốt: confidence THẤP hoặc
    KHÔNG có căn cứ -> risk_policy sẽ đẩy sang người duyệt.
"""

from __future__ import annotations

import json
import re

from .config import Config
from .models import DocHit, DraftAnswer

_SYSTEM_PROMPT = (
    "Bạn là trợ lý nội bộ HR/IT. CHỈ trả lời dựa trên TÀI LIỆU được cung cấp. "
    "Nếu tài liệu không đủ thông tin, nói rõ là không chắc. "
    "Trả về JSON: {\"answer\": string, \"confidence\": number 0..1, "
    "\"used_docs\": string[]}."
)


def _heuristic_confidence(query: str, hits: list[DocHit]) -> float:
    """Confidence 'minh bạch': dựa trên retrieval score + độ phủ từ khoá."""
    if not hits:
        return 0.25
    top = hits[0].score
    q_terms = set(re.findall(r"[0-9a-zà-ỹ]+", query.lower()))
    ctx = " ".join(h.snippet.lower() for h in hits)
    covered = sum(1 for t in q_terms if len(t) > 2 and t in ctx)
    coverage = covered / max(1, len([t for t in q_terms if len(t) > 2]))
    # trộn: 60% theo retrieval score (scale lên), 40% theo coverage
    raw = 0.6 * min(1.0, top * 3.0) + 0.4 * coverage
    return round(min(0.98, max(0.05, raw)), 3)


class FakeLLM:
    """Trả lời bằng cách ghép snippet của doc tốt nhất — đủ để demo pipeline."""

    name = "fake"

    def __init__(self, config: Config):
        self.config = config

    def draft(self, query: str, hits: list[DocHit]) -> DraftAnswer:
        conf = _heuristic_confidence(query, hits)
        if not hits:
            return DraftAnswer(
                text=(
                    "Mình chưa tìm thấy tài liệu nội bộ nào khớp với câu hỏi này "
                    "nên không dám khẳng định. Bạn có thể hỏi rõ hơn không?"
                ),
                confidence=conf,
                citations=[],
                grounded=False,
                model=self.name,
            )
        best = hits[0]
        text = (
            f"Theo tài liệu **{best.doc_id}**: {best.snippet} "
            f"\n\n(Trả lời tự động dựa trên KB — độ tự tin {conf:.0%}.)"
        )
        return DraftAnswer(
            text=text,
            confidence=conf,
            citations=[h.doc_id for h in hits],
            grounded=True,
            model=self.name,
        )


class OpenRouterLLM:
    """Gọi model thật qua OpenRouter. Interface giống hệt FakeLLM."""

    def __init__(self, config: Config):
        self.config = config
        self.name = config.openrouter_model
        if not config.openrouter_api_key:
            raise RuntimeError(
                "LLM_PROVIDER=openrouter nhưng thiếu OPENROUTER_API_KEY trong .env"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - phụ thuộc tuỳ chọn
            raise RuntimeError("Cần `pip install openai` để dùng OpenRouter") from exc
        self._client = OpenAI(
            base_url=config.openrouter_base_url,
            api_key=config.openrouter_api_key,
        )

    def draft(self, query: str, hits: list[DocHit]) -> DraftAnswer:
        context = "\n\n".join(f"[{h.doc_id}]\n{h.snippet}" for h in hits) or "(không có)"
        resp = self._client.chat.completions.create(
            model=self.config.openrouter_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"TÀI LIỆU:\n{context}\n\nCÂU HỎI: {query}"},
            ],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or ""
        answer, confidence, used = self._parse(raw, query, hits)
        return DraftAnswer(
            text=answer,
            confidence=confidence,
            citations=used or [h.doc_id for h in hits],
            grounded=bool(hits),
            model=self.config.openrouter_model,
        )

    @staticmethod
    def _parse(raw: str, query: str, hits: list[DocHit]):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return (
                    str(data.get("answer", raw)).strip(),
                    float(data.get("confidence", _heuristic_confidence(query, hits))),
                    list(data.get("used_docs", [])),
                )
            except (ValueError, TypeError):
                pass
        return raw.strip(), _heuristic_confidence(query, hits), []


def build_llm(config: Config):
    """Factory: chọn backend theo config.llm_provider.

    Nếu chọn openrouter nhưng thiếu API key -> cảnh báo và tự lùi về FakeLLM,
    để `app.py` / `reviewer_cli.py` / test vẫn chạy được khi chưa cấu hình key.
    """
    if config.llm_provider == "openrouter":
        if not config.openrouter_api_key:
            import sys

            print(
                "[llm_service] LLM_PROVIDER=openrouter nhưng chưa có OPENROUTER_API_KEY "
                "-> tạm dùng FakeLLM. Điền key vào .env để gọi model thật.",
                file=sys.stderr,
            )
            return FakeLLM(config)
        return OpenRouterLLM(config)
    return FakeLLM(config)
