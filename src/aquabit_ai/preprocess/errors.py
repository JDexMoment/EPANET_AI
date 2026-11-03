"""Исключения и коды фатальных ошибок Этапа 3 — Preprocessing."""

from __future__ import annotations

from typing import Any


class PreprocessingFatalError(Exception):
    """Фатальная ошибка предобработки данных (останавливает пайплайн без неявных исправлений)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        file: str | None = None,
        field: str | None = None,
        examples: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.file = file
        self.field = field
        self.examples = examples or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "field": self.field,
            "examples": self.examples,
        }
