"""Synthetic denial generator. Deterministic from SEED.

Writes data/dev.jsonl (200), data/heldout.jsonl (100), and data/summary.json.
Do not rerun: the splits are frozen and summary.json records their SHA-256 hashes.

Design choices are explained in docs/data-card.md.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from templates import CARC, DECOYS, DISTRACTORS, INJECTIONS, OTHER_PAYERS, PAYER_TYPE_WEIGHTS, PAYERS, SCENARIOS, SERVICES  # noqa: E402

from triage import config  # noqa: E402

SEED = 20261005
GENERATOR_VERSION = "1.1.0"

# Class shares follow the Optum 2024 Denials Index where it reports a category, with the
# remainder spread over causes it does not break out. See docs/data-card.md.
CLASS_SHARES = {
    "registration_eligibility": 0.24,
    "coding_error": 0.16,
    "prior_authorization": 0.13,
    "medical_necessity": 0.15,
    "coordination_of_benefits": 0.08,
    "timely_filing": 0.07,
    "duplicate_claim": 0.07,
    "non_covered_service": 0.10,
}
SPLIT_SIZES = {"dev": 200, "heldout": 100}
DIFFICULTY_SHARES = {"easy": 0.50, "medium": 0.35, "hard": 0.15}
ADVERSARIAL_COUNTS = {"dev": 12, "heldout": 6}
N_DISTRACTORS = {"easy": 2, "medium": 4, "hard": 5}
# Target mix of claim amounts (USD). Most denials sit between 1,000 and 5,000 USD, with a small
# high-value tail. A scenario whose services cannot reach a band keeps its natural price range.
AMOUNT_TARGETS = [((100, 1000), 0.20), ((1000, 5000), 0.72), ((5000, 20000), 0.08)]
DOS_START, DOS_END = date(2025, 6, 1), date(2026, 5, 31)


# ---------------------------------------------------------------- helpers
def largest_remainder(total: int, shares: dict[str, float]) -> dict[str, int]:
    raw = {k: total * v / sum(shares.values()) for k, v in shares.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out.values())]:
        out[k] += 1
    return out


def pick_variant(rng: random.Random, variants: list[str], split: str) -> int:
    """Held-out uses only the last variant. Dev uses any of the others."""
    return len(variants) - 1 if split == "heldout" else rng.randrange(len(variants) - 1)


def amount_band(allowed: float) -> str:
    if allowed < 1000:
        return "under_1000"
    if allowed < 2500:
        return "1000_to_2499"
    if allowed < 5000:
        return "2500_to_4999"
    return "5000_plus"


def pick_service_and_amount(rng: random.Random, scenario: dict) -> tuple[str, float]:
    (band_lo, band_hi) = rng.choices([b for b, _ in AMOUNT_TARGETS], weights=[w for _, w in AMOUNT_TARGETS])[0]
    fits = [k for k in scenario["services"] if SERVICES[k]["allowed"][0] < band_hi and SERVICES[k]["allowed"][1] > band_lo]
    if fits:
        key = rng.choice(fits)
        lo, hi = SERVICES[key]["allowed"]
        return key, round(rng.uniform(max(lo, band_lo), min(hi, band_hi)), 2)
    key = rng.choice(scenario["services"])
    lo, hi = SERVICES[key]["allowed"]
    return key, round(rng.uniform(lo, hi), 2)


def rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def transpose(member_id: str, rng: random.Random) -> str:
    digits = list(member_id)
    candidates = [i for i in range(1, len(digits) - 1) if digits[i] != digits[i + 1]]
    i = rng.choice(candidates)
    digits[i], digits[i + 1] = digits[i + 1], digits[i]
    return "".join(digits)


# ---------------------------------------------------------------- one record
def build_context(rng: random.Random, scenario: dict, payer: dict, service_key: str) -> dict:
    svc = SERVICES[service_key]
    dos = rand_date(rng, DOS_START, DOS_END)
    limit = payer["filing_limit_days"]
    member_id = "W" + "".join(str(rng.randint(0, 9)) for _ in range(8))

    sub_date = dos + timedelta(days=rng.randint(5, 40))
    first_sub = sub_date
    if scenario["id"] == "tf_proof_of_timely":
        first_sub = dos + timedelta(days=rng.randint(15, max(16, limit - 10)))
        sub_date = dos + timedelta(days=limit + rng.randint(5, 60))
    elif scenario["id"] == "tf_truly_late":
        first_sub = dos + timedelta(days=limit + rng.randint(5, 60))
        sub_date = first_sub

    ctx = {
        "payer": payer["name"],
        "member_id": member_id,
        "member_id_bad": transpose(member_id, rng),
        "dob": rand_date(rng, date(1940, 1, 1), date(2005, 12, 31)).isoformat(),
        "dos": dos.isoformat(),
        "sub_date": sub_date.isoformat(),
        "first_sub": first_sub.isoformat(),
        "denial_date": (sub_date + timedelta(days=rng.randint(14, 35))).isoformat(),
        "limit_days": limit,
        "cpt": svc["cpt"][-1][0],
        "cpt_desc": svc["desc"],
        "icd": svc["icd"],
        "auth_cpt": svc.get("auth_cpt", svc["cpt"][-1][0]),
        "auth_no": f"PA-{rng.randint(1000000, 9999999)}",
        "auth_date": (dos - timedelta(days=rng.randint(7, 30))).isoformat(),
        "auth_start": (dos - timedelta(days=rng.randint(1, 5))).isoformat(),
        "auth_end": (dos + timedelta(days=rng.randint(30, 90))).isoformat(),
        "sched_date": (dos - timedelta(days=rng.randint(7, 40))).isoformat(),
        "term_date": (dos - timedelta(days=rng.randint(5, 60))).isoformat(),
        "letter_date": (dos + timedelta(days=rng.randint(20, 70))).isoformat(),
        "audit_date": (sub_date + timedelta(days=rng.randint(3, 20))).isoformat(),
        "req_date": (sub_date + timedelta(days=rng.randint(10, 25))).isoformat(),
        "ref_no": f"REF-{rng.randint(100000, 999999)}",
        "batch_no": f"B{rng.randint(10000, 99999)}",
        "prior_claim_id": f"CLM-{rng.randint(100000, 999999)}",
        "paid_date": (sub_date - timedelta(days=rng.randint(3, 20))).isoformat(),
        "other_payer": rng.choice(OTHER_PAYERS),
        "other_start": (dos - timedelta(days=rng.randint(200, 900))).isoformat(),
        "other_end": (dos - timedelta(days=rng.randint(10, 120))).isoformat(),
        "weeks": rng.randint(6, 12) if scenario["id"] == "mn_strong_documentation" else rng.randint(1, 2),
        "time1": f"{rng.randint(8, 11):02d}:{rng.choice(['05', '20', '35', '50'])}",
        "time2": f"{rng.randint(14, 17):02d}:{rng.choice(['10', '25', '40', '55'])}",
        "npi": "1" + "".join(str(rng.randint(0, 9)) for _ in range(9)),
        "copay": rng.choice([20, 25, 30, 40, 50]),
    }
    # The payer's retro-termination date must fall before the date of service.
    if scenario["id"] == "reg_retro_termination":
        ctx["term_date"] = (dos - timedelta(days=rng.randint(3, 25))).isoformat()
    return ctx


def build_claim(rng: random.Random, scenario: dict, service_key: str, ctx: dict, allowed: float) -> dict:
    svc = SERVICES[service_key]
    billed = round(allowed * rng.uniform(1.4, 2.6), 2)

    lines = [{"cpt": c, "modifiers": [m] if m else [], "units": svc.get("units", 1)} for c, m in svc["cpt"]]
    if service_key == "ov_injection" and scenario["claim"] != "drop_modifier":
        lines[0]["modifiers"] = ["25"]
    if scenario["id"] == "dup_distinct_service":
        lines.append(dict(lines[-1]))

    needs_auth = service_key in {"mri_lumbar", "knee_arthroscopy", "cardiac_cath", "sleep_study", "infusion", "spinal_fusion", "colonoscopy"}
    auth = ctx["auth_no"] if needs_auth else None
    if scenario["claim"] == "drop_auth":
        auth = None

    return {
        "member_id": ctx["member_id_bad"] if scenario["claim"] == "bad_member_id" else ctx["member_id"],
        "service_date": ctx["dos"],
        "submitted_date": ctx["sub_date"],
        "place_of_service": svc["pos"],
        "provider_specialty": svc["specialty"],
        "lines": lines,
        "icd10": ["Z00.00"] if scenario["claim"] == "wrong_icd" else [svc["icd"]],
        "prior_auth_number": auth,
        "billed_amount": billed,
        "expected_allowed_amount": allowed,
    }


def make_record(rng: random.Random, scenario: dict, difficulty: str, split: str, adversarial: bool, used_ids: set) -> dict:
    payer_type = rng.choices(list(PAYER_TYPE_WEIGHTS), weights=list(PAYER_TYPE_WEIGHTS.values()))[0]
    payer = rng.choice([p for p in PAYERS if p["type"] == payer_type])
    service_key, allowed_amount = pick_service_and_amount(rng, scenario)
    ctx = build_context(rng, scenario, payer, service_key)
    claim = build_claim(rng, scenario, service_key, ctx, allowed_amount)

    if difficulty == "easy":
        carc = rng.choice(scenario["carc_easy"])
    elif difficulty == "medium":
        carc = rng.choice(scenario["carc_easy"] if rng.random() < 0.5 else scenario["carc_hard"])
    else:
        carc = rng.choice(scenario["carc_hard"])

    # Assemble lines: (source, text, role, template_key)
    lines = []
    for i, (source, variants) in enumerate(scenario["evidence"]):
        v = pick_variant(rng, variants, split)
        lines.append((source, variants[v].format(**ctx), "evidence", f"{scenario['id']}/e{i}/v{v}"))
    for j in rng.sample(range(len(DISTRACTORS)), N_DISTRACTORS[difficulty]):
        source, variants = DISTRACTORS[j]
        v = pick_variant(rng, variants, split)
        lines.append((source, variants[v].format(**ctx), "distractor", f"distractor{j}/v{v}"))
    if difficulty == "hard":
        decoy_cause = rng.choice([c for c in DECOYS if c != scenario["cause"]])
        source, variants = DECOYS[decoy_cause]
        v = pick_variant(rng, variants, split)
        lines.append((source, variants[v].format(**ctx), "decoy", f"decoy:{decoy_cause}/v{v}"))

    p = round(rng.uniform(*scenario["p"]), 3)
    allowed = claim["expected_allowed_amount"]
    values = config.action_values(scenario["cause"], allowed, p, scenario["correctable"])
    best = config.best_action(scenario["cause"], allowed, p, scenario["correctable"])

    injection = None
    if adversarial:
        target_cause = rng.choice([c for c in config.ROOT_CAUSES if c != scenario["cause"]])
        target_action = "write_off" if best == "appeal" else "appeal"
        source, variants = INJECTIONS[0]
        v = pick_variant(rng, variants, split)
        text = variants[v].format(target_cause=target_cause, target_action=target_action)
        lines.append((source, text, "injection", f"injection/v{v}"))
        injection = {"target_root_cause": target_cause, "target_action": target_action}

    rng.shuffle(lines)
    documentation, evidence_ids, provenance = [], [], {}
    for n, (source, text, role, key) in enumerate(lines, start=1):
        line_id = f"D{n}"
        documentation.append({"id": line_id, "source": source, "text": text})
        provenance[line_id] = {"role": role, "template": key}
        if role == "evidence":
            evidence_ids.append(line_id)
        if role == "injection":
            injection["line_id"] = line_id

    while True:
        denial_id = f"DN-{rng.randint(10000, 99999)}"
        if denial_id not in used_ids:
            used_ids.add(denial_id)
            break

    return {
        "denial_id": denial_id,
        "payer": {"name": payer["name"], "type": payer["type"], "filing_limit_days": payer["filing_limit_days"]},
        "denial": {"carc": carc, "carc_text": CARC[carc], "denial_date": ctx["denial_date"]},
        "claim": claim,
        "documentation": documentation,
        "labels": {
            "root_cause": scenario["cause"],
            "scenario": scenario["id"],
            "correctable": scenario["correctable"],
            "evidence_supports_appeal": scenario["appeal_supported"],
            "true_overturn_probability": p,
            "action_values": values,
            "best_action": best,
            "evidence_lines": sorted(evidence_ids, key=lambda s: int(s[1:])),
            "difficulty": difficulty,
            "amount_band": amount_band(allowed),
            "is_adversarial": adversarial,
            "injection": injection,
            "line_provenance": provenance,
        },
    }


# ---------------------------------------------------------------- splits
def plan_split(rng: random.Random, split: str) -> list[tuple[dict, str, bool]]:
    """Stratified plan: exact counts per root cause, difficulty, and scenario (largest remainder)."""
    plan = []
    for cause, n_cause in largest_remainder(SPLIT_SIZES[split], CLASS_SHARES).items():
        scenarios = [s for s in SCENARIOS if s["cause"] == cause]
        scen_counts = largest_remainder(n_cause, {s["id"]: s["weight"] for s in scenarios})
        diff_counts = largest_remainder(n_cause, DIFFICULTY_SHARES)
        scen_list = [s for s in scenarios for _ in range(scen_counts[s["id"]])]
        diff_list = [d for d, k in diff_counts.items() for _ in range(k)]
        rng.shuffle(scen_list)
        rng.shuffle(diff_list)
        plan += [(s, d, False) for s, d in zip(scen_list, diff_list)]
    rng.shuffle(plan)
    # Spread adversarial records across root causes.
    by_cause: dict[str, list[int]] = {}
    for i, (s, _, _) in enumerate(plan):
        by_cause.setdefault(s["cause"], []).append(i)
    order = [idx for group in zip(*[rng.sample(v, len(v)) for v in by_cause.values()]) for idx in group]
    for i in order[: ADVERSARIAL_COUNTS[split]]:
        s, d, _ = plan[i]
        plan[i] = (s, d, True)
    return plan


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(records: list[dict]) -> dict:
    lab = [r["labels"] for r in records]
    return {
        "n": len(records),
        "root_cause": dict(Counter(x["root_cause"] for x in lab).most_common()),
        "best_action": dict(Counter(x["best_action"] for x in lab).most_common()),
        "difficulty": dict(Counter(x["difficulty"] for x in lab).most_common()),
        "amount_band": dict(Counter(x["amount_band"] for x in lab).most_common()),
        "payer_type": dict(Counter(r["payer"]["type"] for r in records).most_common()),
        "carc": dict(Counter(r["denial"]["carc"] for r in records).most_common()),
        "adversarial": sum(x["is_adversarial"] for x in lab),
        "total_allowed_usd": round(sum(r["claim"]["expected_allowed_amount"] for r in records), 2),
        "oracle_value_usd": round(sum(max(x["action_values"].values()) for x in lab), 2),
    }


def main(out_dir: Path | None = None, quiet: bool = False) -> dict:
    out_dir = out_dir or ROOT / "data"
    rng = random.Random(SEED)
    used_ids: set[str] = set()
    out = {}
    for split in ["dev", "heldout"]:
        records = [make_record(rng, s, d, split, adv, used_ids) for s, d, adv in plan_split(rng, split)]
        path = out_dir / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
        out[split] = records

    templates = {s: {p["template"] for r in out[s] for p in r["labels"]["line_provenance"].values()} for s in out}
    summary = {
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "frozen": True,
        "sha256": {s: sha256(out_dir / f"{s}.jsonl") for s in out},
        "template_variants_shared_across_splits": len(templates["dev"] & templates["heldout"]),
        "dev": summarize(out["dev"]),
        "heldout_counts_only": {"n": len(out["heldout"])},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if not quiet:
        print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
