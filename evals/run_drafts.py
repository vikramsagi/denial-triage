"""Draft appeal letters for every dev denial whose recommended action is appeal, and score them with the checker.

Classifications come from a saved full dev run, so drafting can be compared across models without
reclassifying. Routing is recomputed with the current rules, win odds table, and router.

    uv run python -m evals.run_drafts --from-run <run_id> --tier small
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from dataclasses import asdict
from pathlib import Path

from evals import replay
from triage import classify, config, draft, llm, pipeline
from triage.load import load_labels, load_split

ROOT = Path(__file__).resolve().parent.parent


def decisions_from_saved_run(run_id: str):
    """Re-run routing on saved classifications without model calls. Returns denials, results, suspicious lines."""
    config_name, answers = replay.saved_answers(run_id)
    denials = load_split("dev")
    by_text = {classify.user_message(d): answers[d.denial_id] for d in denials if d.denial_id in answers}
    llm.register_mock(classify.TOOL["name"], lambda user: by_text[user])
    prev_mock, prev_ledger = os.environ.get("TRIAGE_MOCK"), os.environ.get("TRIAGE_LEDGER")
    os.environ["TRIAGE_MOCK"] = "1"
    os.environ["TRIAGE_LEDGER"] = str(ROOT / "runs" / "replay-ledger.jsonl")
    try:
        results, _ = pipeline.run(denials, config_name, write_events=False)
    finally:
        for k, v in (("TRIAGE_MOCK", prev_mock), ("TRIAGE_LEDGER", prev_ledger)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    suspicious = {k: v.get("suspicious_lines", []) for k, v in answers.items()}
    return denials, results, suspicious


def main(from_run: str, tier: str, limit: int | None = None) -> dict:
    denials, results, suspicious = decisions_from_saved_run(from_run)
    labels = load_labels("dev")
    by_id = {d.denial_id: d for d in denials}
    todo = [r for r in results if (r.decision.recommended_action or r.decision.action) == "appeal" and r.classification]
    if limit:
        todo = todo[:limit]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-drafts-{tier}"
    rows = []
    for r in todo:
        o = draft.draft(by_id[r.denial_id], r.classification, suspicious.get(r.denial_id, []), tier=tier, run_id=run_id)
        lab = labels[r.denial_id]
        rows.append(asdict(o) | {"route": r.decision.action, "case_strength": "supported" if r.classification.evidence_supports_appeal else "limited",
                                 "true_best_action": lab["best_action"], "true_evidence_lines": lab["evidence_lines"]})
        print(f"{r.denial_id} {'pass' if o.passed else 'FAIL'} attempt {o.attempts} {o.cost_usd:.4f} USD")
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"drafts_dev_{tier}_{draft.DRAFT_PROMPT_VERSION}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    n = len(rows)
    summary = {
        "run_id": run_id, "mock": llm.mock_mode(), "split": "dev", "classifications_from": from_run,
        "model": config.MODELS[tier]["id"], "prompt_version": draft.DRAFT_PROMPT_VERSION, "letters": n,
        "passed_first_try": sum(x["passed"] and x["attempts"] == 1 for x in rows),
        "passed_after_retry": sum(x["passed"] and x["attempts"] == 2 for x in rows),
        "failed_twice": sum(not x["passed"] for x in rows),
        "sent_to_person": sum(x["needs_person"] for x in rows),
        "limited_cases": sum(x["case_strength"] == "limited" for x in rows),
        "median_words": sorted(x["words"] for x in rows)[n // 2] if n else 0,
        "cost_usd": round(sum(x["cost_usd"] for x in rows), 6),
        "cost_per_letter_usd": round(sum(x["cost_usd"] for x in rows) / n, 6) if n else 0,
        "records": rows,
    }
    name = f"{'MOCK-' if summary['mock'] else ''}{stamp}-dev-drafts-{tier}.json"
    (ROOT / "evals" / "runs" / name).write_text(json.dumps(summary, indent=2) + "\n")
    print({k: v for k, v in summary.items() if k != "records"})
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-run", required=True)
    ap.add_argument("--tier", default=config.DRAFT_TIER, choices=list(config.MODELS))
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    main(a.from_run, a.tier, a.limit)
