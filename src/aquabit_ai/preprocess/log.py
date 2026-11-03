"""Журнал явных операций преобразования Этапа 3 — preprocessing_log.jsonl (§4, Этап 3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


LogSeverity = Literal["info", "warning", "error"]


@dataclass
class PreprocessingLogEntry:
    """Одна запись об операции предобработки (1 строка в preprocessing_log.jsonl)."""

    stage: str
    operation: str
    file: str | None = None
    field: str | None = None
    before: Any = None
    after: Any = None
    affected_rows: int = 0
    severity: LogSeverity = "info"
    details: dict[str, Any] = dc_field(default_factory=dict)
    timestamp_utc: str = dc_field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "operation": self.operation,
            "severity": self.severity,
        }
        if self.file is not None:
            payload["file"] = self.file
        if self.field is not None:
            payload["field"] = self.field
        if self.before is not None:
            payload["before"] = self.before
        if self.after is not None:
            payload["after"] = self.after
        payload["affected_rows"] = self.affected_rows
        if self.details:
            payload.update(self.details)
        payload["timestamp_utc"] = self.timestamp_utc
        return payload


class PreprocessingLogger:
    """Накапливает записи операций Этапа 3 и сериализует их в preprocessing_log.jsonl."""

    def __init__(self) -> None:
        self.entries: list[PreprocessingLogEntry] = []

    def record(
        self,
        *,
        stage: str,
        operation: str,
        file: str | None = None,
        field: str | None = None,
        before: Any = None,
        after: Any = None,
        affected_rows: int = 0,
        severity: LogSeverity = "info",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.entries.append(
            PreprocessingLogEntry(
                stage=stage,
                operation=operation,
                file=file,
                field=field,
                before=before,
                after=after,
                affected_rows=affected_rows,
                severity=severity,
                details=details or {},
            )
        )

    def warnings(self) -> list[PreprocessingLogEntry]:
        return [e for e in self.entries if e.severity in {"warning", "error"}]

    def write_jsonl(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(e.to_json_dict(), ensure_ascii=False, separators=(",", ":"))
            for e in self.entries
        ]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path
