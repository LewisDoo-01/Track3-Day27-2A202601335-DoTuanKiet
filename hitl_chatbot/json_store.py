"""Kho lưu trữ đơn giản bằng file JSON.

Vì sao dùng file JSON (không phải DB)?
  - Bài lab ưu tiên "đơn giản, đọc hiểu nhanh". Toàn bộ state nằm trong
    data/state/*.json, mở ra xem được bằng mắt thường.

Giới hạn cần biết (production sẽ khác):
  - Ghi atomic bằng "ghi file tạm rồi os.replace" -> không bao giờ để lại
    file JSON hỏng dở, nhưng KHÔNG chống được 2 tiến trình ghi song song.
  - Với nhiều instance / tải cao: thay lớp này bằng Postgres/SQLite + hàng đợi.
Interface (list of dict) được giữ tối giản để có thể thay backend dễ dàng.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable

# Khoá trong tiến trình — đủ cho FastAPI single-worker + CLI + test.
_LOCK = threading.RLock()


class JsonCollection:
    """Một 'bảng' = một file JSON chứa list các dict."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_raw([])

    # --- đọc / ghi thô ---------------------------------------------------- #
    def _write_raw(self, rows: list[dict]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)  # atomic trên cùng ổ đĩa

    def all(self) -> list[dict]:
        """Trả về toàn bộ bản ghi (bản sao, sửa thoải mái không ảnh hưởng file)."""
        with _LOCK:
            if not self.path.exists():
                return []
            text = self.path.read_text(encoding="utf-8").strip()
            return json.loads(text) if text else []

    # --- thao tác cấp cao ---------------------------------------------- #
    def append(self, row: dict) -> None:
        with _LOCK:
            rows = self.all()
            rows.append(row)
            self._write_raw(rows)

    def update(self, match: Callable[[dict], bool], mutate: Callable[[dict], dict]) -> int:
        """Sửa tại chỗ mọi bản ghi thoả `match` bằng hàm `mutate`. Trả số bản ghi đã sửa."""
        with _LOCK:
            rows = self.all()
            n = 0
            for i, r in enumerate(rows):
                if match(r):
                    rows[i] = mutate(dict(r))
                    n += 1
            if n:
                self._write_raw(rows)
            return n

    def find(self, match: Callable[[dict], bool]) -> list[dict]:
        return [r for r in self.all() if match(r)]

    def get(self, match: Callable[[dict], bool]) -> dict | None:
        for r in self.all():
            if match(r):
                return r
        return None

    def replace_all(self, rows: list[dict]) -> None:
        with _LOCK:
            self._write_raw(rows)

    def clear(self) -> None:
        self.replace_all([])
