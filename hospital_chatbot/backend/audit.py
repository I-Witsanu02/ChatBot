"""Structured audit logging for chatbot and admin events."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from .versioning import now_bangkok_iso

_LOCK = Lock()


def append_audit_event(log_path: Path, event: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": now_bangkok_iso(), **event}
    with _LOCK:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def tail_audit_events(log_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return list(reversed(events))
