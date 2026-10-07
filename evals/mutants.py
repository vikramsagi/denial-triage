"""Deliberately broken systems. A metric may appear in a report only after every mutant scores worse
than the real system on it, which proves the metric can detect failure.

    uv run python -m evals.mutants --against b2_rules_ev
"""

from __future__ import annotations

import argparse
import copy
import random

from evals import metrics
from triage import config, pipeline
from triage.load import load_labels, load_split
from triage.schema import RouteDecision

SEED = 11


def _with_route(result, action: str):
    r = copy.copy(result)
    r.decision = RouteDecision(action=action, overturn_probability=0.0, expected_values={}, trigger="mutant")
    return r


def _with_cause(result, cause: str):
    r = copy.copy(result)
    r.classification = result.classification.model_copy(update={"root_cause": cause})
    return r


def build(results) -> dict[str, list]:
    rng = random.Random(SEED)
    swap = {"appeal": "write_off", "write_off": "appeal"}
    causes = [r.classification.root_cause for r in results]
    shuffled = causes[:]
    rng.shuffle(shuffled)
    return {
        "random_router": [_with_route(r, rng.choice(metrics.ROUTES[:3])) for r in results],
        "always_appeal": [_with_route(r, "appeal") for r in results],
        "always_write_off": [_with_route(r, "write_off") for r in results],
        "swap_appeal_and_write_off": [_with_route(r, swap.get(r.decision.action, r.decision.action)) for r in results],
        "shuffled_root_causes": [_with_cause(r, c) for r, c in zip(results, shuffled)],
        "random_root_causes": [_with_cause(r, rng.choice(config.ROOT_CAUSES)) for r in results],
    }


def check(against: str) -> dict[str, dict[str, bool]]:
    denials, labels = load_split("dev"), load_labels("dev")
    real, _ = pipeline.run(denials, against, write_events=False)
    real_m = metrics.compute(metrics.per_record(real, labels))
    out = {}
    for name, res in build(real).items():
        m = metrics.compute(metrics.per_record(res, labels))
        out[name] = {k: (m[k] is not None and real_m[k] is not None and m[k] < real_m[k]) for k in ["value_captured", "root_cause_accuracy"]}
        out[name]["_value_captured"] = round(m["value_captured"], 4)
        out[name]["_root_cause_accuracy"] = round(m["root_cause_accuracy"], 4)
    out["_real"] = {"value_captured": round(real_m["value_captured"], 4), "root_cause_accuracy": round(real_m["root_cause_accuracy"], 4)}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", default="b2_rules_ev")
    res = check(ap.parse_args().against)
    real = res.pop("_real")
    print(f"real system: value captured {real['value_captured']:.3f}, root-cause accuracy {real['root_cause_accuracy']:.3f}")
    for name, r in res.items():
        print(f"  {name:28s} value {r['_value_captured']:.3f} ({'worse' if r['value_captured'] else 'NOT WORSE'})"
              f"   accuracy {r['_root_cause_accuracy']:.3f} ({'worse' if r['root_cause_accuracy'] else 'not worse'})")
