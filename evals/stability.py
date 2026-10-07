"""Run-to-run stability and the two-read agreement check, from saved full dev runs. No model calls.

For each saved run, the model's answers are re-routed under rules first with the current table.
Stability is the share of denials that get the same route in every run. The two-read check is
simulated on each pair of runs: where the pair disagrees, a person decides (best value minus 15 USD);
where it agrees, the first run's decision stands.

    uv run python -m evals.stability --runs <run_id> <run_id> [<run_id> ...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
from pathlib import Path

from evals import replay
from triage import config

ROOT = Path(__file__).resolve().parent.parent
BASE_CONFIG = "m_rules_small_think"


def main(run_ids: list[str], save: bool = True) -> dict:
    recs = {}
    for rid in run_ids:
        r = replay.replay(rid, None, "stability", config_override=BASE_CONFIG)
        recs[rid] = {x["denial_id"]: x for x in r["records"]}
    ids = sorted(next(iter(recs.values())))
    oracle = sum(recs[run_ids[0]][i]["oracle"] for i in ids)
    same_all = sum(len({recs[r][i]["route"] for r in run_ids}) == 1 for i in ids)
    single = []
    for rid in run_ids:
        v = sum(recs[rid][i]["value"] for i in ids)
        single.append({"run": rid, "value_captured": v / oracle, "dollars_lost": oracle - v,
                       "human_review": sum(recs[rid][i]["route"] == "human_review" for i in ids)})
    pairs = []
    for a, b in itertools.combinations(run_ids, 2):
        dis = [i for i in ids if recs[a][i]["route"] != recs[b][i]["route"]]
        v = sum((recs[a][i]["oracle"] - config.HUMAN_REVIEW_COST) if i in dis else recs[a][i]["value"] for i in ids)
        pairs.append({"runs": [a, b], "routes_agree": len(ids) - len(dis), "disagree": dis,
                      "value_captured_with_check": v / oracle, "dollars_lost_with_check": oracle - v,
                      "dollars_lost_first_run_alone": oracle - sum(recs[a][i]["value"] for i in ids),
                      "human_review_with_check": sum(recs[a][i]["route"] == "human_review" or i in dis for i in ids)})
    out = {"runs": run_ids, "denials": len(ids), "same_route_in_all_runs": same_all,
           "stability": same_all / len(ids), "target": 0.95, "single_runs": single, "pairs": pairs}
    if save:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (ROOT / "evals" / "runs" / f"{stamp}-dev-stability.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    o = main(a.runs, save=not a.no_save)
    print(f"same route in all {len(a.runs)} runs: {o['same_route_in_all_runs']} of {o['denials']} ({o['stability']:.1%}), target 95%")
    for s in o["single_runs"]:
        print(f"  {s['run']}: value {s['value_captured']:.2%}, lost {s['dollars_lost']:,.0f} USD, reviews {s['human_review']}")
    for p in o["pairs"]:
        print(f"  pair: agree {p['routes_agree']}, with check value {p['value_captured_with_check']:.2%}, lost {p['dollars_lost_with_check']:,.0f} "
              f"(first run alone {p['dollars_lost_first_run_alone']:,.0f}), reviews {p['human_review_with_check']}")
