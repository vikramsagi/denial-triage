"""Feedback loop: learn from the first days of real outcomes after launch, then correct the win odds.

Inputs that a provider would really get back:
- appeal outcomes: for each appeal filed, whether the payer reversed the denial;
- reviewer decisions: for each claim a person decided, what they chose and whether it differed from the recommendation.

Recalibration compares, for each (payer, root cause), the wins the system expected with the wins that came back.
The correction is a multiplier on the win odds, shrunk toward 1.0 with pseudo-counts so that a few outcomes cannot
swing it far:

    factor = (observed wins + K * expected wins / n) / (expected wins + K * expected wins / n)   ... see correction()

A correction is applied only when a cell has at least MIN_APPEALS outcomes. In this simulation, outcomes are drawn
from the answer key's true win odds with a fixed seed, standing in for the payer's real responses.
"""

from __future__ import annotations

import random
from collections import defaultdict

K = 4              # pseudo-appeals pulling the factor toward 1.0
MIN_APPEALS = 4    # outcomes needed before a cell is corrected
OUTCOME_SEED = 7


def simulate_outcomes(records: list[dict], labels: dict[str, dict], seed: int = OUTCOME_SEED) -> list[dict]:
    """One outcome per appeal filed: did the payer reverse it? Drawn from the true win odds."""
    rng = random.Random(seed)
    out = []
    for r in records:
        if r["route"] == "appeal":
            lab = labels[r["denial_id"]]
            out.append({"denial_id": r["denial_id"], "won": rng.random() < lab["true_overturn_probability"]})
    return out


def reviewer_decisions(records: list[dict], labels: dict[str, dict]) -> list[dict]:
    """A person decides each claim sent to review. The simulation assumes they choose the best action."""
    return [{"denial_id": r["denial_id"], "recommended": r["recommended"], "chosen": labels[r["denial_id"]]["best_action"],
             "overrode": r["recommended"] != labels[r["denial_id"]]["best_action"]}
            for r in records if r["route"] == "human_review"]


def correction(wins: int, n: int, expected: float, k: float = K) -> float:
    """Shrunk ratio of observed to expected wins. expected = sum of predicted win odds over the n appeals."""
    if n == 0 or expected <= 0:
        return 1.0
    prior_rate = expected / n
    return (wins + k * prior_rate) / (expected + k * prior_rate)


def recalibrate(records: list[dict], outcomes: list[dict]) -> dict:
    """Return {(payer, root cause): factor} plus the evidence behind each cell."""
    by_id = {r["denial_id"]: r for r in records}
    cells: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "wins": 0, "expected": 0.0})
    for o in outcomes:
        r = by_id[o["denial_id"]]
        c = cells[(r["payer"], r["pred_cause"])]
        c["n"] += 1
        c["wins"] += int(o["won"])
        c["expected"] += r["p"]
    factors, evidence = {}, []
    for key, c in sorted(cells.items()):
        f = correction(c["wins"], c["n"], c["expected"]) if c["n"] >= MIN_APPEALS else 1.0
        evidence.append({"payer": key[0], "root_cause": key[1], "appeals": c["n"], "wins": c["wins"],
                         "expected_wins": round(c["expected"], 2), "factor": round(f, 3), "applied": c["n"] >= MIN_APPEALS and abs(f - 1) > 0.05})
        if c["n"] >= MIN_APPEALS and abs(f - 1) > 0.05:
            factors[key] = round(f, 3)
    return {"factors": factors, "cells": evidence}
