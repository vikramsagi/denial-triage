"""Score the final system: rules first, two independent classifier reads, disagreement to a person.

Built from two saved full dev runs with the same configuration. Where the reads lead to different routes,
the denial goes to a person (best value minus the review cost); elsewhere the first read's decision stands.

    uv run python -m evals.two_read --runs <run_id_1> <run_id_2>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from evals import bootstrap, metrics, replay
from triage import config

ROOT = Path(__file__).resolve().parent.parent


def main(run_a: str, run_b: str, save: bool = True) -> dict:
    a = replay.replay(run_a, None, "two-read", config_override="m_rules_small_think")
    b = {x["denial_id"]: x for x in replay.replay(run_b, None, "two-read", config_override="m_rules_small_think")["records"]}
    rows = []
    for r in a["records"]:
        if r["route"] != b[r["denial_id"]]["route"]:
            r = r | {"route": "human_review", "effective_action": r["true_action"], "value": r["oracle"] - config.HUMAN_REVIEW_COST,
                     "two_reads_disagree": True}
        rows.append(r)
    out = {"runs": [run_a, run_b], "metrics": metrics.compute(rows), "intervals_95": bootstrap.intervals(rows),
           "reads_disagree": [r["denial_id"] for r in rows if r.get("two_reads_disagree")],
           "human_review": sum(r["route"] == "human_review" for r in rows),
           "api_cost_per_denial_usd": round((a.get("api_cost_usd") or 0) * 2 / len(rows), 6), "records": rows}
    if save:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (ROOT / "evals" / "runs" / f"{stamp}-dev-two-read-check.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs=2, required=True)
    a = ap.parse_args()
    o = main(*a.runs)
    for k in metrics.HEADLINE:
        iv = o["intervals_95"].get(k)
        print(f"  {k:28s} {o['metrics'][k]:.3f}  95% CI {iv}")
    print("  dollars lost", round(o["metrics"]["dollars_lost_usd"]), "human review", o["human_review"], "disagree", o["reads_disagree"])
