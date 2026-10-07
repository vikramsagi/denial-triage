"""Grade every dev letter with the judge through the batch API, plus five planted bad letters that pass
the citation checker but misstate their sources or weaken the case. The judge must fail all five.

    uv run python -m evals.run_judge --letters results/drafts_dev_large_draft_v4.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from triage import citations, judge, llm
from triage.load import load_split

ROOT = Path(__file__).resolve().parent.parent

# Planted letters are built from a fixed set of earlier letters, so every judge run grades the same five.
PLANT_SOURCE = "results/drafts_dev_large_draft_v4.jsonl"
# (denial, what is wrong, original text, planted text). Each planted letter still passes the citation checker.
PLANTS = [
    ("DN-39870", "contradicts its source", "records 10 weeks of failed conservative management", "records 10 weeks of successful conservative management"),
    ("DN-20644", "states a fact its source does not say", "The service date on the claim is 2026-04-10 [claim.service_date].",
     "The service date on the claim is 2026-04-10 [claim.service_date]. The payer confirmed by phone that the claim was timely [D4]."),
    ("DN-98795", "claims criteria are met on a limited case", "The claim lists prior authorization number PA-1362696 [claim.prior_auth_number].",
     "The claim lists prior authorization number PA-1362696 [claim.prior_auth_number]. The documentation meets every criterion in the payer's policy [D2][D3]."),
    ("DN-40385", "admits fault and weakens the case", "The plan rider document lists the therapeutic exercise session as a covered benefit [D5].",
     "The plan rider document lists the therapeutic exercise session as a covered benefit [D5]. We acknowledge our staff may have misread the rider [D5]."),
    ("DN-17973", "leaves out the key evidence", "The patient provided proof that Granite State Benefit Plan coverage ended on 2025-04-17 [D4]. ", ""),
]


def planted(letters: dict[str, dict], denials: dict) -> list[dict]:
    out = []
    for did, what, old, new in PLANTS:
        text = letters[did]["letter"]
        assert old in text, f"plant text not found in {did}"
        bad = text.replace(old, new)
        assert citations.check(bad, denials[did]).passed, f"planted letter for {did} must pass the citation checker"
        out.append({"denial_id": did, "letter": bad, "case_strength": letters[did]["case_strength"], "planted": what})
    return out


def main(letters_path: str) -> dict:
    denials = {d.denial_id: d for d in load_split("dev")}
    letters = {json.loads(l)["denial_id"]: json.loads(l) for l in (ROOT / letters_path).read_text().splitlines()}
    items = [{"denial_id": k, "letter": v["letter"], "case_strength": v["case_strength"], "planted": None} for k, v in letters.items() if v["passed"]]
    plant_from = {json.loads(l)["denial_id"]: json.loads(l) for l in (ROOT / PLANT_SOURCE).read_text().splitlines()}
    items += planted(plant_from, denials)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-judge"
    reqs = [(f"{i:03d}-{x['denial_id']}", judge.user_message(denials[x["denial_id"]], x["letter"], x["case_strength"])) for i, x in enumerate(items)]
    batch_id = llm.submit_batch(tier=judge.JUDGE_TIER, system=judge.system_prompt(), items=reqs, tool=judge.TOOL, max_tokens=judge.JUDGE_MAX_TOKENS)
    print("batch submitted:", batch_id, len(reqs), "letters")
    got = llm.collect_batch(batch_id, tier=judge.JUDGE_TIER, purpose="judge", run_id=run_id, poll_s=20)
    rows = []
    for (cid, _), x in zip(reqs, items):
        g = got.get(cid, {"error": "missing"})
        out = g.get("output", {})
        try:
            judge.validate(out)
            out["ship"] = judge.ship_rule(out)
            err = None
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        rows.append(x | {"grade": out if not err else None, "error": err or g.get("error"), "cost_usd": g.get("cost_usd", 0),
                         "words": len(x["letter"].split())})
    (ROOT / "results" / f"judge_dev_{judge.JUDGE_PROMPT_VERSION}_on_{Path(letters_path).stem}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    real = [r for r in rows if not r["planted"] and r["grade"]]
    plants = [r for r in rows if r["planted"]]
    summary = {
        "run_id": run_id, "batch_id": batch_id, "split": "dev", "letters_from": letters_path, "judge_model": llm.config.MODELS[judge.JUDGE_TIER]["id"],
        "prompt_version": judge.JUDGE_PROMPT_VERSION, "graded": len(real), "errors": sum(1 for r in rows if not r["grade"]),
        "ship": sum(r["grade"]["ship"] for r in real),
        "mean_scores": {c: round(sum(r["grade"][c] for r in real) / len(real), 2) for c in judge.CRITERIA} if real else {},
        "planted_failed": sum(1 for r in plants if r["grade"] and not r["grade"]["ship"]), "planted": len(plants),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "records": rows,
    }
    (ROOT / "evals" / "runs" / f"{stamp}-dev-judge.json").write_text(json.dumps(summary, indent=2) + "\n")
    print({k: v for k, v in summary.items() if k != "records"})
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--letters", default="results/drafts_dev_large_draft_v4.jsonl")
    a = ap.parse_args()
    main(a.letters)
