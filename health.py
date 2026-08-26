"""Privacy-safe health and metrics snapshots for WebMonitor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional

from web_monitor import MonitorError


@dataclass(frozen=True)
class HealthRecord:
    """One target outcome without target URLs, selectors, or scraped content."""

    name: str
    status: str
    matched_elements: Optional[int] = None
    error: Optional[str] = None


class HealthReporter:
    """Atomically write the latest process health snapshot."""

    VERSION = 1

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def write(self, records: list[HealthRecord]) -> None:
        status_counts = {
            "baseline": 0,
            "unchanged": 0,
            "changed": 0,
            "error": 0,
        }
        targets = []
        for record in records:
            status_counts.setdefault(record.status, 0)
            status_counts[record.status] += 1
            item = {
                "name": record.name,
                "status": record.status,
            }
            if record.matched_elements is not None:
                item["matched_elements"] = record.matched_elements
            if record.error:
                item["error"] = record.error
            targets.append(item)

        failed = status_counts.get("error", 0)
        payload = {
            "version": self.VERSION,
            "generated_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "healthy": failed == 0 and bool(records),
            "targets_total": len(records),
            "checks_succeeded": len(records) - failed,
            "checks_failed": failed,
            "status_counts": status_counts,
            "targets": targets,
        }

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_name(f"{self.path.name}.tmp")
            temporary_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except OSError as exc:
            raise MonitorError("Unable to write health output") from exc
