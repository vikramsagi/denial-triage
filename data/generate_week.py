"""A simulated first week after launch, with one deliberate change in the world. Never used for tuning.

What changes: Northwind Health Plan tightens prior authorization.
- More of its denials are prior-authorization denials.
- Its authorization denial notes use new wording the system has never seen.
- Appeals against its prior-authorization denials now win about a fifth as often as before.

The week has 7 days of denials. Days 1 to 3 are the learning window: their appeal outcomes come back and feed
the recalibration. Days 4 to 7 are scored before and after recalibration, so the gain is measured on denials
the feedback did not see.

    uv run python data/generate_week.py
"""

from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

import generate as G  # noqa: E402
import templates as T  # noqa: E402

SEED = 20261012
WEEK_SIZE = 150
DAYS = 7
LEARN_DAYS = {1, 2, 3}
DRIFT_PAYER = "Northwind Health Plan"
DRIFT_PAYER_SHARE = 0.75        # share of the week's prior-authorization denials that come from the drifting payer
AUTH_SHARE_WEEK = 0.30          # prior authorization share of all denials this week (0.13 in dev and held-out)
P_MULTIPLIER = 0.2              # the drifting payer now rarely overturns its prior-authorization denials on appeal
NEW_WORDING = {
    "auth_on_file_not_on_claim": "Northwind utilization management portal shows approval {auth_no} for {cpt}, window {auth_start} to {auth_end}.",
    "auth_emergency_exempt": "Northwind UM review flagged the {cpt_desc} as lacking prior review; ED record {dos} documents arrival by ambulance.",
    "auth_cpt_mismatch": "Northwind UM portal lists {auth_no} for {auth_cpt}; operative report {dos} records a change to {cpt} during the procedure.",
    "auth_never_obtained": "Northwind UM portal returned no request on file for {cpt} before {dos}.",
}


def week_scenarios() -> list[dict]:
    """Copies of the prior-authorization scenarios with the new wording added as the only variant of the first evidence line."""
    out = []
    for s in T.SCENARIOS:
        if s["id"] in NEW_WORDING:
            w = copy.deepcopy(s)
            source, _ = w["evidence"][0]
            w["evidence"][0] = (source, [NEW_WORDING[s["id"]], NEW_WORDING[s["id"]]])
            w["p"] = (s["p"][0] * P_MULTIPLIER, s["p"][1] * P_MULTIPLIER)
            out.append(w)
    return out


def main() -> dict:
    rng = random.Random(SEED)
    used: set[str] = set()
    for split in ("dev", "heldout"):  # never reuse a denial ID
        used |= {json.loads(l)["denial_id"] for l in (ROOT / "data" / f"{split}.jsonl").read_text().splitlines()}
    shares = dict(G.CLASS_SHARES)
    rest = 1 - AUTH_SHARE_WEEK
    other = {k: v / (1 - shares["prior_authorization"]) * rest for k, v in shares.items() if k != "prior_authorization"}
    counts = G.largest_remainder(WEEK_SIZE, {**other, "prior_authorization": AUTH_SHARE_WEEK})
    drift_scen = {s["id"]: s for s in week_scenarios()}
    payers = {p["name"]: p for p in T.PAYERS}
    records = []
    for cause, n in counts.items():
        scenarios = [s for s in T.SCENARIOS if s["cause"] == cause]
        per = G.largest_remainder(n, {s["id"]: s["weight"] for s in scenarios})
        for sid, k in per.items():
            for _ in range(k):
                base = next(s for s in scenarios if s["id"] == sid)
                difficulty = rng.choices(list(G.DIFFICULTY_SHARES), weights=list(G.DIFFICULTY_SHARES.values()))[0]
                drifting = cause == "prior_authorization" and rng.random() < DRIFT_PAYER_SHARE
                scen = drift_scen[sid] if drifting else base
                if drifting:  # draw the payer as the drifting payer, so every line that names the payer agrees
                    saved = G.PAYERS, G.PAYER_TYPE_WEIGHTS
                    G.PAYERS, G.PAYER_TYPE_WEIGHTS = [payers[DRIFT_PAYER]], {payers[DRIFT_PAYER]["type"]: 1.0}
                    try:
                        r = G.make_record(rng, scen, difficulty, "dev", False, used)
                    finally:
                        G.PAYERS, G.PAYER_TYPE_WEIGHTS = saved
                else:
                    r = G.make_record(rng, scen, difficulty, "dev", False, used)
                r["labels"]["week_drift"] = drifting
                records.append(r)
    rng.shuffle(records)
    for i, r in enumerate(records):
        r["labels"]["day"] = 1 + i * DAYS // len(records)
    out = ROOT / "data" / "week.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in records))
    summary = {
        "seed": SEED, "records": len(records), "drift_payer": DRIFT_PAYER, "auth_share": AUTH_SHARE_WEEK,
        "drifting_records": sum(r["labels"]["week_drift"] for r in records), "learn_days": sorted(LEARN_DAYS),
        "sha256": G.sha256(out),
    }
    (ROOT / "data" / "week_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    print(main())
