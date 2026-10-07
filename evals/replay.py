"""Re-score a saved model run with the current rules, win odds table, and router, without new model calls.

The model's saved answers are read from the run's decision events and fed back in place of live calls,
so a change to anything after classification can be measured for free.

    uv run python -m evals.replay --run-id <run_id> --subset first20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import run_eval
from triage import classify, llm, pipeline
from triage.observe import RUNS


def saved_answers(run_id: str) -> tuple[str, dict[str, dict]]:
    events = [json.loads(line) for line in (RUNS / run_id / "events.jsonl").read_text().splitlines()]
    config_name = next(e["run_id"] for e in events).split("-")[1]
    answers = {}
    for e in events:
        if e["stage"] == "classify" and e.get("model_called"):
            o = e["output"]
            answers[e["denial_id"]] = {k: o[k] for k in ["root_cause", "correctable", "evidence_supports_appeal", "evidence_lines", "confidence", "reason"]} | {"suspicious_lines": o.get("suspicious_lines", [])}
    return config_name, answers


def replay(run_id: str, subset: str | None, label: str) -> dict:
    config_name, answers = saved_answers(run_id)
    by_text: dict[str, dict] = {}
    from triage.load import load_split

    for d in load_split("dev"):
        if d.denial_id in answers:
            by_text[classify.user_message(d)] = answers[d.denial_id]
    llm.register_mock(classify.TOOL["name"], lambda user: by_text[user])
    import os

    os.environ["TRIAGE_MOCK"] = "1"
    os.environ["TRIAGE_LEDGER"] = str(Path(__file__).resolve().parent.parent / "runs" / "replay-ledger.jsonl")  # keep the real ledger clean
    report = run_eval.evaluate("dev", config_name, write=False, subset=subset)
    report["config"] = config_name
    report["replayed_from"] = run_id
    report["label"] = label
    report["mock"] = False
    report["note"] = "Saved model answers re-scored with the current rules, win odds table, and router. No new model calls."
    return report


def save(report: dict) -> Path:
    import datetime as dt

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(__file__).resolve().parent / "runs" / f"{stamp}-dev-{report['config']}-replay.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--subset")
    ap.add_argument("--save", action="store_true", help="write the re-scored report to evals/runs/")
    a = ap.parse_args()
    r = replay(a.run_id, a.subset, "replay")
    run_eval.print_report(r)
    if a.save:
        print("saved", save(r))
