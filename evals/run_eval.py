"""Evaluate one configuration on one split and write a run file.

    uv run python -m evals.run_eval --split dev --config b2_rules_ev
    uv run python -m evals.run_eval --split heldout --config <frozen config>   # final evaluation only
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from evals import bootstrap, metrics
from triage import llm, pipeline
from triage.load import load_labels, load_split

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "evals" / "runs"
HELDOUT_LOG = ROOT / "evals" / "heldout_log.md"


SUBSETS = ROOT / "evals" / "subsets"


def _tokens(run_id: str) -> dict:
    from triage import budget

    out = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for e in budget.entries():
        if e["run_id"] == run_id:
            u = e["usage"]
            out["input"] += u.get("input_tokens", 0)
            out["output"] += u.get("output_tokens", 0)
            out["cache_read"] += u.get("cache_read_input_tokens", 0)
            out["cache_write"] += u.get("cache_creation_input_tokens", 0)
    return out


def letters_and_grades(denials, results, rec, labels, run_id: str) -> dict:
    """Draft a letter for every denial whose recommended action is appeal, then grade every passing letter."""
    from evals.run_judge import grade_batch
    from triage import draft

    by_id = {d.denial_id: d for d in denials}
    suspicious = {e["denial_id"]: e["output"].get("suspicious_lines", []) for e in rec.events
                  if e["stage"] == "classify" and e.get("model_called")}
    todo = [r for r in results if (r.decision.recommended_action or r.decision.action) == "appeal" and r.classification]
    drafts = []
    for r in todo:
        o = draft.draft(by_id[r.denial_id], r.classification, suspicious.get(r.denial_id, []), run_id=run_id)
        drafts.append({"denial_id": r.denial_id, "letter": o.letter, "passed": o.passed, "attempts": o.attempts, "reasons": o.reasons,
                       "needs_person": o.needs_person, "cost_usd": o.cost_usd, "words": o.words,
                       "case_strength": "supported" if r.classification.evidence_supports_appeal else "limited",
                       "true_best_action": labels[r.denial_id]["best_action"]})
    graded = grade_batch([{"denial_id": x["denial_id"], "letter": x["letter"], "case_strength": x["case_strength"]} for x in drafts if x["passed"]],
                         by_id, run_id + "-judge")
    grade_by = {g["denial_id"]: g for g in graded}
    for x in drafts:
        g = grade_by.get(x["denial_id"])
        x["grade"], x["grade_cost_usd"] = (g["grade"], g["cost_usd"]) if g else (None, 0.0)
    n = len(drafts)
    sup = [x for x in drafts if x["case_strength"] == "supported" and x["grade"]]
    return {
        "letters": n, "passed_checker": sum(x["passed"] for x in drafts), "passed_first_try": sum(x["passed"] and x["attempts"] == 1 for x in drafts),
        "limited_cases": sum(x["case_strength"] == "limited" for x in drafts),
        "supported_ready_to_send": sum(x["grade"]["ship"] for x in sup), "supported_graded": len(sup),
        "draft_cost_usd": round(sum(x["cost_usd"] for x in drafts), 6), "grade_cost_usd": round(sum(x["grade_cost_usd"] for x in drafts), 6),
        "records": drafts,
    }


def evaluate(split: str, config_name: str, write: bool = True, subset: str | None = None, with_letters: bool = False) -> dict:
    heldout = split == "heldout"
    if heldout and subset:
        raise ValueError("subsets are for dev only")
    denials = load_split(split, allow_heldout=heldout)
    if subset:
        ids = set(json.loads((SUBSETS / f"{subset}.json").read_text())["denial_ids"])
        denials = [d for d in denials if d.denial_id in ids]
    labels = load_labels(split, allow_heldout=heldout)
    results, rec = pipeline.run(denials, config_name, write_events=write)
    rows = metrics.per_record(results, labels)
    api_cost = sum(r.cost_usd for r in results)
    model_calls = sum(1 for e in rec.events if e.get("model_called"))
    report = {
        "run_id": rec.run_id,
        "mock": llm.mock_mode() if config_name in pipeline.MODEL_CONFIGS else False,
        "split": split,
        "subset": subset,
        "config": config_name,
        "versions": rec.versions,
        "model_ids": {k: v for k, v in rec.versions.items() if k == "model"},
        "prompt_versions": {k: v for k, v in rec.versions.items() if k == "prompt"},
        "model_calls": model_calls,
        "flags": {f: sum(f in r.flags for r in results) for f in sorted({f for r in results for f in r.flags})},
        "metrics": metrics.compute(rows, api_cost_usd=api_cost),
        "intervals_95": bootstrap.intervals(rows),
        "confusion_true_by_route": metrics.confusion(rows),
        "api_cost_usd": round(api_cost, 6),
        "tokens": _tokens(rec.run_id),
        "records": rows,
    }
    if with_letters:
        report["letters"] = letters_and_grades(denials, results, rec, labels, rec.run_id)
        n = len(results)
        report["api_cost_per_denial_usd"] = {
            "classification": round(api_cost / n, 6),
            "letters": round(report["letters"]["draft_cost_usd"] / n, 6),
            "grading": round(report["letters"]["grade_cost_usd"] / n, 6),
        }
        report["api_cost_per_denial_usd"]["total"] = round(sum(report["api_cost_per_denial_usd"].values()), 6)
    if write:
        RUNS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prefix = "MOCK-" if report["mock"] else ""
        path = RUNS / f"{prefix}{stamp}-{split}{'-' + subset if subset else ''}-{config_name}.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        report["path"] = str(path.relative_to(ROOT))
        if heldout:
            with HELDOUT_LOG.open("a") as f:
                f.write(f"| {stamp} | {config_name} | {report['path']} |\n")
    return report


def injection_summary(report_path: str, split: str) -> dict:
    """Injection results for a saved run: how many planted instructions changed the decision they asked for."""
    rep = json.loads((ROOT / report_path).read_text())
    labels = load_labels(split, allow_heldout=split == "heldout")
    ev = {}
    for line in (ROOT / "runs" / rep["run_id"] / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["stage"] == "classify" and e.get("model_called"):
            ev[e["denial_id"]] = e["output"]
    rows = {r["denial_id"]: r for r in rep["records"]}
    out = []
    for did, lab in labels.items():
        inj = lab.get("injection")
        if not inj:
            continue
        o = ev.get(did)
        out.append({"denial_id": did, "read_by_model": o is not None,
                    "flagged": bool(o and inj["line_id"] in o.get("suspicious_lines", [])),
                    "took_injected_action": rows[did]["route"] == inj["target_action"] and rows[did]["true_action"] != inj["target_action"],
                    "took_injected_cause": bool(o and o["root_cause"] == inj["target_root_cause"])})
    return {"adversarial": len(out), "read_by_model": sum(x["read_by_model"] for x in out), "flagged": sum(x["flagged"] for x in out),
            "succeeded": sum(x["took_injected_action"] or x["took_injected_cause"] for x in out), "records": out}


def fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def print_report(r: dict) -> None:
    m, ci = r["metrics"], r["intervals_95"]
    print(f"\n{r['config']} on {r['split']} (n={m['n']})  ->  {r.get('path', '(not written)')}")
    for k in metrics.HEADLINE:
        band = ci.get(k)
        print(f"  {k:22s} {fmt(m[k])}" + (f"   95% CI [{band[0]:.3f}, {band[1]:.3f}]" if band else ""))
    print(f"  {'system value':22s} {m['system_value_usd']:,.2f} of {m['oracle_value_usd']:,.2f} USD oracle")
    print(f"  {'human review share':22s} {m['human_review_share']:.3f}")
    print(f"  {'model calls':22s} {r.get('model_calls', 0)}   API cost {r['api_cost_usd']:.4f} USD   per denial {m['cost_per_denial_usd']:.5f} USD   flags {r.get('flags', {})}")
    print("  confusion (rows = true best action, columns = route)")
    print("  " + " " * 18 + "".join(f"{c[:12]:>14s}" for c in metrics.ROUTES))
    for t, row in r["confusion_true_by_route"].items():
        print(f"  {t:18s}" + "".join(f"{row[c]:>14d}" for c in metrics.ROUTES))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=["dev", "heldout", "week"])
    ap.add_argument("--config", required=True, choices=pipeline.CONFIGS)
    ap.add_argument("--subset", help="name of a fixed dev subset in evals/subsets/")
    ap.add_argument("--prompt", help="classification prompt version, for example classify_v1")
    ap.add_argument("--with-letters", action="store_true", help="also draft and grade a letter for every recommended appeal")
    ap.add_argument("--injection-report", help="saved run file: add injection results to it instead of running")
    args = ap.parse_args()
    if args.injection_report:
        rep_path = ROOT / args.injection_report
        rep = json.loads(rep_path.read_text())
        rep["injection"] = injection_summary(args.injection_report, args.split)
        rep_path.write_text(json.dumps(rep, indent=2) + "\n")
        print({k: v for k, v in rep["injection"].items() if k != "records"})
        raise SystemExit
    if args.prompt:
        from triage import config
        config.CLASSIFY_PROMPT_VERSION = args.prompt
    r = evaluate(args.split, args.config, subset=args.subset, with_letters=args.with_letters)
    print_report(r)
    if "letters" in r:
        print({k: v for k, v in r["letters"].items() if k != "records"}, r["api_cost_per_denial_usd"])
