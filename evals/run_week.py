"""Simulated first week after launch: run the final system, monitor it, learn from outcomes, measure the gain.

1. Run the final system (rules first, two reads) on the 150 denials of data/week.jsonl.
2. Monitoring: compare the week's decision events with the dev baseline. The monitor never sees right answers.
3. Feedback: appeal outcomes and reviewer decisions from days 1 to 3 recalibrate the win odds per payer and cause.
4. Score days 4 to 7 before and after the correction, with 95% intervals. Days 4 to 7 never fed the correction.

    uv run python -m evals.run_week                 # live: runs the system on the week (about 1.60 USD)
    uv run python -m evals.run_week --from-run <id> # reuse a saved week run, no model calls
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from evals import bootstrap, metrics, run_eval
from evals.run_eval import ROOT
from triage import config, feedback, monitor, router
from triage.load import load_labels, load_split

DEV_READ_1 = "20261007T224224Z-m_rules_small_think-1f2421"
DEV_FINAL = "evals/runs/20261007T233811Z-dev-two-read-check.json"
CONFIG = "m_rules_small_think_x2"


def dev_baseline() -> dict:
    ev = monitor.load_events(DEV_READ_1)
    final = json.loads((ROOT / DEV_FINAL).read_text())
    review = {r["denial_id"] for r in final["records"] if r["route"] == "human_review"}
    return monitor.with_two_read_check(monitor.summarize(ev), final["reads_disagree"], ev, review)


def week_records(run_id: str) -> list[dict]:
    """One row per denial from the week's decision events, with what the feedback loop needs."""
    labels = load_labels("week")
    week = {d.denial_id: d for d in load_split("week")}
    rows = []
    for did, e in monitor.load_events(run_id).items():
        out = e["route"]["output"]
        cls = e["classify"]["output"] if e["classify"].get("model_called") else None
        rows.append({"denial_id": did, "day": labels[did]["day"], "payer": week[did].payer.name, "allowed": week[did].claim.expected_allowed_amount, "route": out["action"],
                     "recommended": out["recommended_action"], "p": out["overturn_probability"], "ev": out["expected_values"],
                     "pred_cause": e["probability"]["inputs"]["row"].split("|")[0], "classification": cls,
                     "rules_settled": e["rules"]["output"]["resolved"]})
    return rows


def _best(r: dict, p: float) -> str:
    """Best action after a win-odds correction: only the appeal value changes."""
    ev = dict(r["ev"])
    ev["appeal"] = round(p * r["allowed"] - config.appeal_cost(r["pred_cause"]), 2)
    return max(router.ORDER, key=lambda a: (ev[a], -router.ORDER.index(a)))


def score(rows: list[dict], actions: dict[str, str], labels: dict) -> dict:
    scored = []
    for r in rows:
        lab, a = labels[r["denial_id"]], actions[r["denial_id"]]
        scored.append({"denial_id": r["denial_id"], "route": a, "effective_action": lab["best_action"] if a == "human_review" else a,
                       "true_action": lab["best_action"], "pred_cause": r["pred_cause"], "true_cause": lab["root_cause"],
                       "value": metrics.realized_value(a, lab), "oracle": metrics.oracle_value(lab)})
    return {"metrics": metrics.compute(scored), "intervals_95": bootstrap.intervals(scored), "records": scored}


def main(from_run: str | None) -> dict:
    if from_run:
        run_id, run_file = from_run, None
    else:
        rep = run_eval.evaluate("week", CONFIG)
        run_id, run_file = rep["run_id"], rep.get("path")
    labels = load_labels("week")
    rows = week_records(run_id)

    mon = monitor.compare(dev_baseline(), monitor.summarize(monitor.load_events(run_id)))
    learn = [r for r in rows if r["day"] in {1, 2, 3}]
    later = [r for r in rows if r["day"] not in {1, 2, 3}]
    outcomes = feedback.simulate_outcomes(learn, labels)
    reviews = feedback.reviewer_decisions(learn, labels)
    cal = feedback.recalibrate(learn, outcomes)
    before = score(later, {r["denial_id"]: r["route"] for r in later}, labels)
    after = score(later, {r["denial_id"]: (r["route"] if r["route"] == "human_review" or (r["payer"], r["pred_cause"]) not in cal["factors"]
                                           else _best(r, min(1.0, r["p"] * cal["factors"][(r["payer"], r["pred_cause"])]))) for r in later}, labels)
    drift_ids = {d for d, lab in labels.items() if lab.get("week_drift")}
    out = {
        "week_run": run_id, "week_run_file": run_file, "config": CONFIG, "denials": len(rows),
        "monitoring": {"alerts": mon.alerts, "warnings": mon.warnings, "checks": mon.checks},
        "feedback": {"learn_days": [1, 2, 3], "appeal_outcomes": len(outcomes), "appeals_won": sum(o["won"] for o in outcomes),
                     "reviewer_decisions": len(reviews), "reviewer_overrides": sum(x["overrode"] for x in reviews),
                     "corrections": [{"payer": k[0], "root_cause": k[1], "factor": v} for k, v in cal["factors"].items()], "cells": cal["cells"]},
        "days_4_to_7": {
            "denials": len(later), "drifting_denials": sum(r["denial_id"] in drift_ids for r in later),
            "before": {k: before["metrics"][k] for k in ["value_captured", "dollars_lost_usd", "appeal_precision", "appeal_recall"]} | {"ci": before["intervals_95"]["value_captured"]},
            "after": {k: after["metrics"][k] for k in ["value_captured", "dollars_lost_usd", "appeal_precision", "appeal_recall"]} | {"ci": after["intervals_95"]["value_captured"]},
            "changed_decisions": [x["denial_id"] for x, y in zip(before["records"], after["records"]) if x["route"] != y["route"]],
        },
    }
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (ROOT / "evals" / "runs" / f"{stamp}-week-feedback.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-run")
    a = ap.parse_args()
    o = main(a.from_run)
    print("monitoring:", [(c["signal"], c["level"], c["current"]) for c in o["monitoring"]["checks"] if c["level"] != "ok"] or "no alerts")
    print("feedback:", {k: v for k, v in o["feedback"].items() if k != "cells"})
    print("days 4-7:", json.dumps(o["days_4_to_7"], indent=1))
