"""95% bootstrap intervals: resample denials with replacement and recompute each metric."""

from __future__ import annotations

import random

from evals.metrics import HEADLINE, compute

N_RESAMPLES = 2000
SEED = 7


def intervals(rows: list[dict], metrics: list[str] = HEADLINE, n: int = N_RESAMPLES, seed: int = SEED) -> dict[str, list[float] | None]:
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {m: [] for m in metrics}
    for _ in range(n):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        out = compute(sample)
        for m in metrics:
            if out[m] is not None:
                draws[m].append(out[m])
    result = {}
    for m, xs in draws.items():
        if not xs:
            result[m] = None
            continue
        xs.sort()
        result[m] = [round(xs[int(0.025 * len(xs))], 4), round(xs[int(0.975 * len(xs)) - 1], 4)]
    return result
