"""The only way records enter the system. Strips the answer key and validates the schema.

The held-out split is locked: only the evaluation runner may open it, by passing allow_heldout=True.
"""

from __future__ import annotations

import json
from pathlib import Path

from triage.schema import DenialInput

DATA = Path(__file__).resolve().parent.parent / "data"
SPLITS = {"dev", "heldout"}


class HeldoutLocked(RuntimeError):
    pass


def _path(split: str, allow_heldout: bool) -> Path:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    if split == "heldout" and not allow_heldout:
        raise HeldoutLocked("data/heldout.jsonl may only be opened by evals.run_eval --split heldout")
    return DATA / f"{split}.jsonl"


def _rows(split: str, allow_heldout: bool) -> list[dict]:
    return [json.loads(line) for line in _path(split, allow_heldout).read_text().splitlines() if line]


def strip_labels(row: dict) -> DenialInput:
    clean = {k: v for k, v in row.items() if k != "labels"}
    return DenialInput.model_validate(clean)


def load_split(split: str, allow_heldout: bool = False) -> list[DenialInput]:
    return [strip_labels(r) for r in _rows(split, allow_heldout)]


def load_labels(split: str, allow_heldout: bool = False) -> dict[str, dict]:
    """Answer key by denial ID. For evaluation code only, never for any model input."""
    return {r["denial_id"]: r["labels"] for r in _rows(split, allow_heldout)}


def model_payload(denial: DenialInput) -> dict:
    """The exact fields a model may receive. Every prompt is built from this and nothing else."""
    return denial.model_dump()
