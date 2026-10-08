"""Overturn probability table: the chance an appeal succeeds, by what the system believes about a denial.

The table stands in for a provider's history of appeal outcomes. It is fitted once on dev labels and
saved to triage/prob_table.json. Cells with few records shrink toward the average of all denials with the
same evidence profile (evidence supports an appeal, correctable), across root causes. Shrinking toward the
root-cause average was rejected: strong appeals inflate that average, which gave denials with no basis to
appeal win odds of 13% to 15% and turned write-offs into appeals.

    uv run python -m triage.probability     # refit and save
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from triage.schema import Classification

TABLE_PATH = Path(__file__).resolve().parent / "prob_table.json"
SHRINK_K = 3          # pseudo-records pulled toward the evidence-profile mean
SHRINK_BELOW_N = 10   # only small cells are shrunk; cells with this many records or more use their own mean


def cell_key(root_cause: str, supports: bool, correctable: bool) -> str:
    return f"{root_cause}|supports={supports}|correctable={correctable}"


def profile_key(supports: bool, correctable: bool) -> str:
    return f"supports={supports}|correctable={correctable}"


def fit(labels: dict[str, dict]) -> dict:
    by_cell: dict[str, list[float]] = defaultdict(list)
    by_cause: dict[str, list[float]] = defaultdict(list)
    by_profile: dict[str, list[float]] = defaultdict(list)
    for lab in labels.values():
        p = lab["true_overturn_probability"]
        by_cell[cell_key(lab["root_cause"], lab["evidence_supports_appeal"], lab["correctable"])].append(p)
        by_cause[lab["root_cause"]].append(p)
        by_profile[profile_key(lab["evidence_supports_appeal"], lab["correctable"])].append(p)
    all_p = [p for v in by_cause.values() for p in v]
    cause_mean = {c: sum(v) / len(v) for c, v in by_cause.items()}
    profile_mean = {k: sum(v) / len(v) for k, v in by_profile.items()}
    cells = {}
    for key, ps in sorted(by_cell.items()):
        prior = profile_mean[key.split("|", 1)[1]]
        if len(ps) >= SHRINK_BELOW_N:
            p = sum(ps) / len(ps)
        else:
            p = (sum(ps) + SHRINK_K * prior) / (len(ps) + SHRINK_K)
        cells[key] = {"p": round(p, 4), "n": len(ps), "shrunk": len(ps) < SHRINK_BELOW_N}
    return {
        "fitted_on": "dev",
        "shrink_k": SHRINK_K,
        "shrink_below_n": SHRINK_BELOW_N,
        "cells": cells,
        "shrink_toward": "evidence_profile_mean",
        "profile_mean": {k: round(m, 4) for k, m in sorted(profile_mean.items())},
        "cause_mean": {c: round(m, 4) for c, m in sorted(cause_mean.items())},
        "global_mean": round(sum(all_p) / len(all_p), 4),
    }


# Payer-specific corrections learned from real appeal outcomes after launch, as multipliers on the
# table's win odds: {(payer name, root cause): factor}. Empty until the feedback loop sets them.
ADJUSTMENTS: dict[tuple[str, str], float] = {}


def adjusted(p: float, payer: str, root_cause: str) -> tuple[float, float]:
    """Apply any learned payer correction. Returns the adjusted odds and the factor used."""
    f = ADJUSTMENTS.get((payer, root_cause), 1.0)
    return min(1.0, round(p * f, 4)), f


def load_table() -> dict:
    return json.loads(TABLE_PATH.read_text())


def lookup(c: Classification, table: dict) -> tuple[float, str]:
    """Return the probability and the table row used, falling back to the root-cause and global means."""
    key = cell_key(c.root_cause, c.evidence_supports_appeal, c.correctable)
    if key in table["cells"]:
        return table["cells"][key]["p"], key
    if c.root_cause in table["cause_mean"]:
        return table["cause_mean"][c.root_cause], f"{c.root_cause}|cause_mean"
    return table["global_mean"], "global_mean"


if __name__ == "__main__":
    from triage.load import load_labels

    table = fit(load_labels("dev"))
    TABLE_PATH.write_text(json.dumps(table, indent=2) + "\n")
    for k, v in table["cells"].items():
        print(f"{k:70s} p={v['p']:.3f}  n={v['n']}")
