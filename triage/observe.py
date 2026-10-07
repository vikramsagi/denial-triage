"""Decision events: one structured event per stage per denial, written for monitoring and replay.

Every stage calls `Recorder.emit`. Events go to runs/<run_id>/events.jsonl and also become the
denial's trace for the replay view.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triage import config
from triage.schema import TraceStep

RUNS = Path(__file__).resolve().parent.parent / "runs"


def config_hash() -> str:
    values = {k: v for k, v in vars(config).items() if k.isupper()}
    blob = json.dumps(values, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


class Recorder:
    def __init__(self, run_name: str, versions: dict[str, str] | None = None, write: bool = True):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}-{run_name}-{uuid.uuid4().hex[:6]}"
        self.versions = {"config": config_hash(), **(versions or {})}
        self.traces: dict[str, list[TraceStep]] = {}
        self.events: list[dict[str, Any]] = []
        self._path = RUNS / self.run_id / "events.jsonl" if write else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, denial_id: str, step: TraceStep, *, started: float, confidence: float | None = None, flags: list[str] | None = None) -> TraceStep:
        event = {
            "run_id": self.run_id,
            "denial_id": denial_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "versions": self.versions,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "confidence": confidence,
            "flags": flags or [],
            **step.model_dump(),
        }
        self.events.append(event)
        self.traces.setdefault(denial_id, []).append(step)
        if self._path:
            with self._path.open("a") as f:
                f.write(json.dumps(event, default=str) + "\n")
        return step
