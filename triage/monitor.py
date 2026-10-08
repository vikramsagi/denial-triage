"""Monitoring report: compare a batch of decision events with a known-good baseline run and raise alerts.

It reads only the decision events every pipeline stage writes (runs/<run_id>/events.jsonl), so it works the
same on a test run and in production. It never needs the right answers.

    uv run python -m triage.monitor --baseline <run_id> --current <run_id>

Signals and why they matter:
- route mix: a shift in appeal / fix / write off / person shares means inputs or behavior changed.
- denial reason mix: a shift in why claims are denied, for example one payer tightening prior authorization.
- share settled by rules: a drop suggests claim formats changed.
- two-read disagreement rate: a rise means the model finds the inputs harder or unfamiliar.
- review share: the human queue growing is a cost and capacity problem.
- injection flag rate: a rise may be an attack or a new document source.
- confidence distribution: drift in what the model reports, even if it is not calibrated.
- win odds on appeals and cost per denial.
Distribution shifts use the population stability index (PSI); rates use fixed bands.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from triage.observe import RUNS

ROUTES = ["appeal", "fix_and_resubmit", "write_off", "human_review"]
CAUSES = ["registration_eligibility", "coding_error", "prior_authorization", "medical_necessity", "coordination_of_benefits",
          "timely_filing", "duplicate_claim", "non_covered_service"]
CONF_BINS = [0.0, 0.7, 0.8, 0.85, 0.9, 0.95, 1.01]
PSI_WARN, PSI_ALERT = 0.10, 0.25   # common rule of thumb: under 0.10 stable, 0.10 to 0.25 watch, above 0.25 shifted

# rate signals: (name, absolute change that warns, absolute change that alerts)
RATE_BANDS = {
    "rules_share": (0.05, 0.10),
    "disagree_rate": (0.03, 0.06),
    "review_share": (0.03, 0.06),
    "injection_flag_rate": (0.03, 0.06),
    "mean_appeal_win_odds": (0.05, 0.10),
}


def load_events(run_id: str, root: Path = RUNS) -> dict[str, dict[str, dict]]:
    by: dict[str, dict[str, dict]] = {}
    for line in (root / run_id / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        by.setdefault(e["denial_id"], {})[e["stage"]] = e
    return by


def summarize(events: dict[str, dict[str, dict]]) -> dict:
    n = len(events)
    routes = Counter(e["route"]["output"]["action"] for e in events.values())
    model = [e for e in events.values() if e["classify"].get("model_called")]
    conf = [e["classify"]["output"]["confidence"] for e in model if e["classify"]["output"].get("confidence") is not None]
    flags = [set(e["route"].get("flags") or []) for e in events.values()]
    appeals = [e["route"]["output"]["overturn_probability"] for e in events.values() if e["route"]["output"]["action"] == "appeal"]
    cost = sum(sum(s.get("cost_usd") or 0 for s in e.values()) for e in events.values())
    return {
        "denials": n,
        "route_mix": {r: routes.get(r, 0) / n for r in ROUTES},
        "cause_mix": {c: v / n for c, v in Counter(e["probability"]["inputs"]["row"].split("|")[0] for e in events.values()).items()},
        "rules_share": sum(1 for e in events.values() if e["rules"]["output"]["resolved"]) / n,
        "disagree_rate": sum("reads_disagree" in f for f in flags) / n,
        "review_share": routes.get("human_review", 0) / n,
        "injection_flag_rate": sum("injection_attempt_detected" in f for f in flags) / n,
        "mean_appeal_win_odds": sum(appeals) / len(appeals) if appeals else 0.0,
        "confidence_hist": histogram(conf),
        "cost_per_denial_usd": cost / n,
    }


def histogram(xs: list[float]) -> list[float]:
    counts = [0] * (len(CONF_BINS) - 1)
    for x in xs:
        for i in range(len(counts)):
            if CONF_BINS[i] <= x < CONF_BINS[i + 1]:
                counts[i] += 1
                break
    total = sum(counts) or 1
    return [c / total for c in counts]


def psi(expected: list[float], actual: list[float], floor: float = 1e-4) -> float:
    return sum((a - e) * math.log(max(a, floor) / max(e, floor)) for e, a in zip(expected, actual))


@dataclass
class Report:
    baseline: dict
    current: dict
    checks: list[dict] = field(default_factory=list)

    @property
    def alerts(self) -> list[dict]:
        return [c for c in self.checks if c["level"] == "alert"]

    @property
    def warnings(self) -> list[dict]:
        return [c for c in self.checks if c["level"] == "warn"]


def compare(baseline: dict, current: dict) -> Report:
    rep = Report(baseline, current)
    for name, a, b in [("route_mix", [baseline["route_mix"][r] for r in ROUTES], [current["route_mix"][r] for r in ROUTES]),
                       ("denial_reason_mix", [baseline["cause_mix"].get(c, 0) for c in CAUSES], [current["cause_mix"].get(c, 0) for c in CAUSES]),
                       ("confidence", baseline["confidence_hist"], current["confidence_hist"])]:
        v = psi(a, b)
        level = "alert" if v > PSI_ALERT else "warn" if v > PSI_WARN else "ok"
        rep.checks.append({"signal": f"{name} shift (PSI)", "baseline": None, "current": round(v, 3), "level": level,
                           "rule": f"warn above {PSI_WARN}, alert above {PSI_ALERT}"})
    for name, (warn, alert) in RATE_BANDS.items():
        d = current[name] - baseline[name]
        level = "alert" if abs(d) > alert else "warn" if abs(d) > warn else "ok"
        rep.checks.append({"signal": name, "baseline": round(baseline[name], 4), "current": round(current[name], 4),
                           "level": level, "rule": f"warn if it moves more than {warn}, alert above {alert}"})
    d = current["cost_per_denial_usd"] / max(baseline["cost_per_denial_usd"], 1e-9) - 1
    rep.checks.append({"signal": "cost_per_denial_usd", "baseline": round(baseline["cost_per_denial_usd"], 5),
                       "current": round(current["cost_per_denial_usd"], 5),
                       "level": "alert" if d > 0.5 else "warn" if d > 0.2 else "ok", "rule": "warn above +20%, alert above +50%"})
    return rep


def with_two_read_check(summary: dict, disagree_ids: list[str], events: dict, review_ids: set[str]) -> dict:
    """Adjust a single-read run's summary to the two-read system, using the saved disagreement list."""
    n = summary["denials"]
    s = dict(summary)
    s["disagree_rate"] = len(disagree_ids) / n
    s["review_share"] = len(review_ids | set(disagree_ids)) / n
    mix = Counter()
    for did, e in events.items():
        mix["human_review" if did in disagree_ids else e["route"]["output"]["action"]] += 1
    s["route_mix"] = {r: mix.get(r, 0) / n for r in ROUTES}
    s["cost_per_denial_usd"] = summary["cost_per_denial_usd"] * 2   # every model-read denial is read twice
    return s


def run(baseline_run: str, current_run: str) -> Report:
    return compare(summarize(load_events(baseline_run)), summarize(load_events(current_run)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", required=True)
    a = ap.parse_args()
    r = run(a.baseline, a.current)
    for c in r.checks:
        print(f"  {c['level']:5s}  {c['signal']:26s} baseline {c['baseline']}  current {c['current']}   ({c['rule']})")
    print(f"{len(r.alerts)} alerts, {len(r.warnings)} warnings")
