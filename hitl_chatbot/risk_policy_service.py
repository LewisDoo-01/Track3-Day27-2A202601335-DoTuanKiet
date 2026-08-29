"""Risk policy service — TRÁI TIM của HITL.

Trả lời câu hỏi: "Request này bot được tự xử lý, hay BẮT BUỘC người xem?"

Nguyên tắc thiết kế (giống các hệ thống HITL production):
  1. Có "chốt chặn cứng": một số chủ đề (lương, kỷ luật, dữ liệu cá nhân, pháp lý)
     LUÔN qua người — dù model có tự tin 99%. An toàn > tự động hoá.
  2. Ngoài ra, chuyển người khi có tín hiệu bot "không đáng tin":
     - confidence thấp
     - không tìm được căn cứ trong KB (weak grounding)
     - câu trả lời đề xuất 1 hành động có tác dụng phụ (reset mật khẩu, cấp quyền...)
  3. Quyết định phải KÈM LÝ DO (reasons[]) để audit và để tinh chỉnh policy.

risk_score chỉ để xếp hạng ưu tiên trong hàng đợi, không phải để tự động hoá.
"""

from __future__ import annotations

import re
import unicodedata

from .config import Config
from .models import DocHit, DraftAnswer, Route, RouteDecision


def _norm(text: str) -> str:
    """Bỏ dấu + hạ chữ thường để match từ khoá không phụ thuộc cách gõ."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


class RiskPolicyService:
    def __init__(self, config: Config):
        self.config = config
        self._sensitive_norm = [_norm(k) for k in config.sensitive_keywords]
        self._action_norm = [_norm(k) for k in config.action_phrases]

    def decide(
        self, query: str, draft: DraftAnswer, hits: list[DocHit]
    ) -> RouteDecision:
        reasons: list[str] = []
        q_norm = _norm(query)
        top = hits[0].score if hits else 0.0

        # --- Rule 1: chủ đề nhạy cảm -> chốt chặn cứng ------------------ #
        hit_kw = [
            kw
            for kw, kwn in zip(self.config.sensitive_keywords, self._sensitive_norm)
            if kwn in q_norm
        ]
        if hit_kw:
            reasons.append(f"sensitive_topic:{','.join(sorted(set(hit_kw)))}")

        # --- Rule 2: confidence thấp --------------------------------- #
        if draft.confidence < self.config.confidence_threshold:
            reasons.append(
                f"low_confidence:{draft.confidence:.2f}<{self.config.confidence_threshold:.2f}"
            )

        # --- Rule 3: thiếu căn cứ trong KB -------------------------- #
        if not draft.grounded or top < self.config.retrieval_threshold:
            reasons.append(
                f"weak_grounding:top_score={top:.3f}<{self.config.retrieval_threshold:.3f}"
            )

        # --- Rule 4: câu trả lời đề xuất hành động có side-effect ---- #
        answer_norm = _norm(draft.text)
        hit_act = [
            ph
            for ph, phn in zip(self.config.action_phrases, self._action_norm)
            if phn in answer_norm or phn in q_norm
        ]
        if hit_act:
            reasons.append(f"action_required:{','.join(sorted(set(hit_act)))}")

        route = Route.ESCALATE if reasons else Route.AUTO
        risk_score = self._score(reasons, draft.confidence, top)
        return RouteDecision(route=route, risk_score=risk_score, reasons=reasons)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _score(reasons: list[str], confidence: float, top: float) -> float:
        """Gộp các tín hiệu thành 1 số [0,1] để xếp ưu tiên hàng đợi."""
        if not reasons:
            return 0.0
        weight = {
            "sensitive_topic": 0.5,
            "action_required": 0.3,
            "low_confidence": 0.2,
            "weak_grounding": 0.2,
        }
        s = sum(weight.get(r.split(":", 1)[0], 0.1) for r in reasons)
        # câu càng ít tự tin / càng ít căn cứ thì đẩy điểm lên
        s += 0.15 * (1.0 - confidence) + 0.1 * (1.0 - min(1.0, top * 3))
        return round(min(1.0, s), 3)
