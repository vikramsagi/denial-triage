"""Expected value routing. Picks the action with the highest expected dollar value, using what the
system believes (its classification and the probability table), never the answer key.

A human review band sends a denial to a person when the amount is large or the classifier is unsure.
"""

from __future__ import annotations

from triage import config
from triage.schema import Classification, RouteDecision

ORDER = ["write_off", "fix_and_resubmit", "appeal"]  # ties resolve toward the cheaper action


def expected_values(c: Classification, allowed: float, p: float) -> dict[str, float]:
    return config.action_values(c.root_cause, allowed, p, c.correctable)


def dollars_at_risk(ev: dict[str, float]) -> float:
    """Value of the best action minus the next best: what a wrong pick could cost."""
    top = sorted(ev.values(), reverse=True)
    return round(top[0] - top[1], 2)


def expected_loss(ev: dict[str, float], confidence: float) -> float:
    return round((1.0 - confidence) * dollars_at_risk(ev), 2)


def route(c: Classification, allowed: float, p: float, *, review_threshold: float | None = config.HUMAN_REVIEW_AMOUNT_THRESHOLD,
          confidence_cutoff: float | None = config.HUMAN_REVIEW_CONFIDENCE_CUTOFF, force_review: str | None = None) -> RouteDecision:
    ev = expected_values(c, allowed, p)
    best = max(ORDER, key=lambda a: (ev[a], -ORDER.index(a)))
    risk = dollars_at_risk(ev)
    rationale = (f"Root cause {c.root_cause} ({c.source}, confidence {c.confidence:.2f}): {c.reason} "
                 f"Win odds {p:.2f}. Expected values: appeal {ev['appeal']:,.2f}, fix {ev['fix_and_resubmit']:,.2f}, "
                 f"write off 0.00 USD. Best is {best}; a wrong pick could cost up to {risk:,.2f} USD.")
    common = dict(overturn_probability=p, expected_values=ev, recommended_action=best, rationale=rationale)

    if force_review:
        return RouteDecision(action="human_review", trigger=force_review, **common)
    if review_threshold is not None and allowed >= review_threshold:
        return RouteDecision(action="human_review", trigger=f"high-risk: allowed {allowed:,.2f} USD is at or above {review_threshold:,.0f} USD", **common)
    if confidence_cutoff is not None and c.confidence < confidence_cutoff:
        return RouteDecision(action="human_review", trigger=f"unsure: confidence {c.confidence:.2f} is below {confidence_cutoff:.2f}", **common)
    return RouteDecision(action=best, trigger=f"highest expected value: {best} at {ev[best]:,.2f} USD", **common)
