"""Every headline metric, defined once. System value is always computed from the answer key."""

from __future__ import annotations

from collections import Counter

from triage import config

TRUE_ACTIONS = ["appeal", "fix_and_resubmit", "write_off"]
ROUTES = ["appeal", "fix_and_resubmit", "write_off", "human_review"]


def oracle_value(lab: dict) -> float:
    return max(lab["action_values"].values())


def realized_value(action: str, lab: dict) -> float:
    """Dollar value of an action under the true labels."""
    if action == "human_review":
        return oracle_value(lab) - config.HUMAN_REVIEW_COST
    return lab["action_values"][action]


def per_record(results, labels: dict[str, dict]) -> list[dict]:
    rows = []
    for r in results:
        lab = labels[r.denial_id]
        rows.append({
            "denial_id": r.denial_id,
            "route": r.decision.action,
            # A reviewer is assumed to choose the best action (see docs/assumptions.md).
            "effective_action": lab["best_action"] if r.decision.action == "human_review" else r.decision.action,
            "true_action": lab["best_action"],
            "pred_cause": r.classification.root_cause if r.classification else None,
            "true_cause": lab["root_cause"],
            "value": realized_value(r.decision.action, lab),
            "system_alone_value": realized_value(r.decision.recommended_action or r.decision.action, lab),
            "oracle": oracle_value(lab),
        })
    return rows


def compute(rows: list[dict], api_cost_usd: float = 0.0) -> dict:
    n = len(rows)
    with_cause = [r for r in rows if r["pred_cause"] is not None]
    true_appeal = [r for r in rows if r["true_action"] == "appeal"]
    routed_appeal = [r for r in rows if r.get("effective_action", r["route"]) == "appeal"]
    oracle = sum(r["oracle"] for r in rows)
    value = sum(r["value"] for r in rows)
    return {
        "n": n,
        "root_cause_accuracy": (sum(r["pred_cause"] == r["true_cause"] for r in with_cause) / len(with_cause)) if with_cause else None,
        "appeal_recall": (sum(r.get("effective_action", r["route"]) == "appeal" for r in true_appeal) / len(true_appeal)) if true_appeal else None,
        "appeal_precision": (sum(r["true_action"] == "appeal" for r in routed_appeal) / len(routed_appeal)) if routed_appeal else None,
        "value_captured": value / oracle if oracle else None,
        "value_captured_system_alone": (sum(r.get("system_alone_value", r["value"]) for r in rows) / oracle) if oracle else None,
        "system_value_usd": round(value, 2),
        "oracle_value_usd": round(oracle, 2),
        "dollars_lost_usd": round(oracle - value, 2),
        "human_review_share": sum(r["route"] == "human_review" for r in rows) / n,
        "cost_per_denial_usd": api_cost_usd / n if n else 0.0,
    }


def confusion(rows: list[dict]) -> dict[str, dict[str, int]]:
    c = Counter((r["true_action"], r["route"]) for r in rows)
    return {t: {p: c[(t, p)] for p in ROUTES} for t in TRUE_ACTIONS}


HEADLINE = ["root_cause_accuracy", "appeal_recall", "appeal_precision", "value_captured", "value_captured_system_alone"]
