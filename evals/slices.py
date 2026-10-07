"""Slices and error analysis in dollars for one saved run, re-scored with the current table. No model calls.

    uv run python -m evals.slices --run-id <run_id>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from evals import bootstrap, metrics, replay
from triage.load import load_labels, load_split

ROOT = Path(__file__).resolve().parent.parent
SLICE_KEYS = ["root_cause", "difficulty", "amount_band", "payer_type", "adversarial"]


def error_category(r: dict, lab: dict) -> str:
    """Name what went wrong, from the predicted and true action and cause."""
    if r["route"] == "human_review":
        return "sent to a person (review cost only)"
    pred, true = r["route"], r["true_action"]
    if r["pred_cause"] != r["true_cause"]:
        return f"wrong root cause ({r['pred_cause']} instead of {r['true_cause']})"
    return {("appeal", "fix_and_resubmit"): "appealed a fixable denial",
            ("write_off", "appeal"): "wrote off a winnable appeal",
            ("write_off", "fix_and_resubmit"): "wrote off a fixable denial",
            ("fix_and_resubmit", "write_off"): "resubmitted a denial that cannot be fixed",
            ("appeal", "write_off"): "appealed a denial with no basis",
            ("fix_and_resubmit", "appeal"): "resubmitted instead of appealing"}.get((pred, true), f"{pred} instead of {true}")


def main(run_id: str, config_override: str | None = None, save: bool = True) -> dict:
    rep = replay.replay(run_id, None, "slices", config_override=config_override)
    rows = rep["records"]
    labels = load_labels("dev")
    payer = {d.denial_id: d.payer.type for d in load_split("dev")}
    for r in rows:
        lab = labels[r["denial_id"]]
        r |= {"root_cause": lab["root_cause"], "difficulty": lab["difficulty"], "amount_band": lab["amount_band"],
              "payer_type": payer[r["denial_id"]], "adversarial": "injected" if lab["is_adversarial"] else "clean"}
    slices = {}
    for key in SLICE_KEYS:
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        slices[key] = {}
        for g, rs in sorted(groups.items()):
            m = metrics.compute(rs)
            iv = bootstrap.intervals(rs, ["value_captured"], n=1000)
            slices[key][g] = {"n": len(rs), "value_captured": m["value_captured"], "value_captured_95": iv["value_captured"],
                              "root_cause_accuracy": m["root_cause_accuracy"], "dollars_lost": round(sum(x["oracle"] - x["value"] for x in rs), 2)}
    errors = defaultdict(lambda: {"count": 0, "dollars_lost": 0.0, "denials": []})
    for r in rows:
        lost = r["oracle"] - r["value"]
        if lost > 0.005:
            e = errors[error_category(r, labels[r["denial_id"]])]
            e["count"] += 1
            e["dollars_lost"] = round(e["dollars_lost"] + lost, 2)
            e["denials"].append(r["denial_id"])
    ranked = dict(sorted(errors.items(), key=lambda kv: -kv[1]["dollars_lost"]))
    out = {"run": run_id, "config": rep["config"], "slices": slices, "errors_by_dollars": ranked}
    if save:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (ROOT / "evals" / "runs" / f"{stamp}-dev-slices-{rep['config']}.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--config")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    o = main(a.run_id, a.config, save=not a.no_save)
    for key, groups in o["slices"].items():
        print(key)
        for g, v in groups.items():
            iv = v["value_captured_95"]
            print(f"  {g:28s} n={v['n']:3d} value {v['value_captured']:.1%} ({iv[0]:.1%} to {iv[1]:.1%})  lost {v['dollars_lost']:>8,.0f}")
    print("errors by dollars lost")
    for k, v in o["errors_by_dollars"].items():
        print(f"  {v['dollars_lost']:>8,.0f} USD  {v['count']:2d}  {k}")
