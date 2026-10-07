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


def evaluate(split: str, config_name: str, write: bool = True, subset: str | None = None) -> dict:
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
    ap.add_argument("--split", required=True, choices=["dev", "heldout"])
    ap.add_argument("--config", required=True, choices=pipeline.CONFIGS)
    ap.add_argument("--subset", help="name of a fixed dev subset in evals/subsets/")
    ap.add_argument("--prompt", help="classification prompt version, for example classify_v1")
    args = ap.parse_args()
    if args.prompt:
        from triage import config
        config.CLASSIFY_PROMPT_VERSION = args.prompt
    print_report(evaluate(args.split, args.config, subset=args.subset))
