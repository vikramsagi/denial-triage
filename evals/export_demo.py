"""Export the saved final dev runs into one file for the web demo. Dev records only, no model calls.

    uv run python -m evals.export_demo
"""

from __future__ import annotations

import json
from pathlib import Path

from triage import citations, render
from triage.load import load_split

ROOT = Path(__file__).resolve().parent.parent
READ_1 = "20261007T224224Z-m_rules_small_think-1f2421"
READ_2 = "20261007T231302Z-m_rules_small_think-2699a0"
FINAL = "evals/runs/20261007T233811Z-dev-two-read-check.json"
LETTERS = "results/drafts_dev_large_draft_v5.jsonl"
GRADES = "results/judge_dev_judge_v1_on_drafts_dev_large_draft_v5.jsonl"
BASELINES = {"Appeal every claim above 500 USD": "evals/runs/20261007T162438Z-dev-b0_appeal_above_500.json",
             "Reason-code lookup": "evals/runs/20261007T162439Z-dev-b1_reason_code.json",
             "Rules and expected value, no model": "evals/runs/20261007T162440Z-dev-b2_rules_ev.json"}
TOUR = [("DN-56758", "A strong appeal, from start to finish"), ("DN-14039", "Records were never sent: fix, do not appeal"), ("DN-79796", "The two reads disagreed, so a person decides"),
        ("DN-20874", "An injected instruction is flagged and ignored"),
        ("DN-19623", "Changed procedure during surgery: appeal"), ("DN-98795", "A weak appeal: the letter goes to a person first"),
        ("DN-28780", "A high-value claim always goes to a person")]


def events(run_id: str) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for line in (ROOT / "runs" / run_id / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        out.setdefault(e["denial_id"], {})[e["stage"]] = e
    return out


def jl(path: str) -> dict[str, dict]:
    return {json.loads(l)["denial_id"]: json.loads(l) for l in (ROOT / path).read_text().splitlines() if l.strip()}


def main() -> dict:
    denials = {d.denial_id: d for d in load_split("dev")}
    labels = {json.loads(l)["denial_id"]: json.loads(l)["labels"] for l in (ROOT / "data/dev.jsonl").read_text().splitlines()}
    e1, e2 = events(READ_1), events(READ_2)
    final = json.loads((ROOT / FINAL).read_text())
    frec = {r["denial_id"]: r for r in final["records"]}
    letters, grades = jl(LETTERS), {k: v for k, v in jl(GRADES).items() if not v.get("planted")}
    rows = []
    for did, d in denials.items():
        lab, a, b, f = labels[did], e1[did], e2[did], frec[did]
        read = lambda ev: (None if not ev["classify"].get("model_called") else
                           {k: ev["classify"]["output"].get(k) for k in ["root_cause", "correctable", "evidence_supports_appeal", "evidence_lines",
                                                                          "suspicious_lines", "confidence", "reason"]}
                           | {"cost_usd": ev["classify"]["cost_usd"], "action": ev["route"]["output"]["recommended_action"]})
        r1, r2 = read(a), read(b)
        route = a["route"]["output"]
        letter = None
        if did in letters:
            L, G = letters[did], grades.get(did, {}).get("grade")
            letter = {"case_strength": L["case_strength"], "checked": L["letter"], "sent": render.render(L["letter"], d),
                      "passed_checker": L["passed"], "attempts": L["attempts"], "cost_usd": round(L["cost_usd"], 5),
                      "grade": G and {k: G[k] for k in ["faithfulness", "persuasiveness", "tone", "completeness", "ship", "fix_note", "unsupported_sentences", "reasoning"]},
                      "grade_cost_usd": round(grades.get(did, {}).get("cost_usd", 0), 5)}
        rows.append({
            "id": did, "payer": d.payer.name, "payer_type": d.payer.type, "carc": d.denial.carc, "carc_text": d.denial.carc_text,
            "denial_date": d.denial.denial_date, "claim": d.claim.model_dump(), "allowed": d.claim.expected_allowed_amount,
            "docs": [x.model_dump() for x in d.documentation],
            "rules": {"resolved": a["rules"]["output"]["resolved"], "rule": a["rules"]["output"]["rule"], "summary": a["rules"]["summary"]},
            "rule_reason": route["rationale"] if a["rules"]["output"]["resolved"] else None,
            "read1": r1, "read2": r2, "reads_disagree": bool(f.get("two_reads_disagree")),
            "p": a["probability"]["output"]["p"], "p_row": a["probability"]["inputs"]["row"], "ev": a["expected_value"]["output"],
            "route": f["route"], "trigger": ("The two reads lead to different actions, so a person decides." if f.get("two_reads_disagree") else route["trigger"]),
            "recommended": route["recommended_action"], "rationale": route["rationale"], "flags": a["route"].get("flags", []),
            "letter": letter,
            "truth": {"best_action": lab["best_action"], "root_cause": lab["root_cause"], "correctable": lab["correctable"],
                      "evidence_supports_appeal": lab["evidence_supports_appeal"], "evidence_lines": lab["evidence_lines"],
                      "overturn_p": lab["true_overturn_probability"], "action_values": lab["action_values"],
                      "injected_line": (lab.get("injection") or {}).get("line_id"), "difficulty": lab["difficulty"], "scenario": lab["scenario"]},
            "value": round(f["value"], 2), "oracle": round(f["oracle"], 2),
        })
    base = {}
    for name, path in BASELINES.items():
        r = json.loads((ROOT / path).read_text())
        base[name] = {"value_captured": r["metrics"]["value_captured"], "dollars_lost": r["metrics"]["dollars_lost_usd"], "ci": r["intervals_95"]["value_captured"]}
    m = final["metrics"]
    out = {"generated_from": {"read_1": READ_1, "read_2": READ_2, "final": FINAL, "letters": LETTERS, "grades": GRADES},
           "summary": {"metrics": m, "intervals": final["intervals_95"], "human_review": final["human_review"], "reads_disagree": final["reads_disagree"],
                       "cost_per_denial": {"two_reads": 0.0104, "letters": 0.0033, "grading": 0.0047, "total": 0.0185}},
           "baselines": base, "tour": [{"id": i, "why": w} for i, w in TOUR], "denials": rows}
    data = json.dumps(out, separators=(",", ":")).replace("</", "<\\/")
    body = (ROOT / "docs" / "demo" / "template.html").read_text().replace("__DATA__", data)
    (ROOT / "docs" / "demo" / "fragment.html").write_text(body)   # page content for hosts that add their own skeleton
    full = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n'
            + body + "\n</body>\n</html>\n")
    (ROOT / "docs" / "demo" / "index.html").write_text(full)
    return out


if __name__ == "__main__":
    o = main()
    print(len(o["denials"]), "denials,", sum(1 for r in o["denials"] if r["letter"]), "letters")
