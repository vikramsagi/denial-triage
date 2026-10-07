"""Runs denials through the stages and records a decision event for every stage.

Configurations:
  b0_appeal_above_500   baseline: appeal every claim above 500 USD, write off the rest
  b1_reason_code        baseline: a fixed reason-code lookup decides cause and action
  b2_rules_ev           no model: structural rules, reason-code fallback, probability table, EV routing
  m_rules_<tier>[_think] structural rules, then the model on denials the rules cannot settle
  m_all_small           the model on every denial, no rules (for the rules-first comparison)
  m_rules_small_think_x2 rules first, then two independent model reads; if they lead to different
                        actions, a person decides with both readings attached
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from triage import classify, config, probability, router, rules
from triage.observe import Recorder
from triage.schema import Classification, DenialInput, RouteDecision, TraceStep

# A reason-code lookup: the action a biller would take from the code alone.
# (root cause, correctable, evidence supports appeal)
REASON_CODE_DEFAULTS: dict[str, tuple[str, bool, bool]] = {
    "CO-4": ("coding_error", True, False),
    "CO-11": ("coding_error", True, False),
    "CO-15": ("prior_authorization", True, False),
    "CO-16": ("registration_eligibility", True, False),
    "CO-18": ("duplicate_claim", False, False),
    "CO-22": ("coordination_of_benefits", True, False),
    "CO-27": ("registration_eligibility", False, False),
    "CO-29": ("timely_filing", False, False),
    "CO-31": ("registration_eligibility", True, False),
    "CO-50": ("medical_necessity", False, True),
    "CO-96": ("non_covered_service", False, False),
    "CO-197": ("prior_authorization", False, True),
    "CO-204": ("non_covered_service", False, False),
    "CO-252": ("medical_necessity", True, False),
}
FALLBACK_CONFIDENCE = 0.5

# name: (model tier, thinking, rules first, independent reads)
MODEL_CONFIGS = {
    "m_rules_small": ("small", False, True, 1),
    "m_rules_small_think": ("small", True, True, 1),
    "m_rules_small_think_x2": ("small", True, True, 2),
    "m_rules_large": ("large", False, True, 1),
    "m_rules_large_think": ("large", True, True, 1),
    "m_all_small": ("small", False, False, 1),
    "m_all_small_think": ("small", True, False, 1),
}
DEFAULT_CONFIG = "m_rules_small_think_x2"  # rules first, two reads (ADR-001, ADR-002, ADR-004)
CONFIGS = ["b0_appeal_above_500", "b1_reason_code", "b2_rules_ev", *MODEL_CONFIGS]


@dataclass
class Result:
    denial_id: str
    classification: Classification | None
    decision: RouteDecision
    cost_usd: float = 0.0
    flags: list[str] = field(default_factory=list)


def reason_code_classification(d: DenialInput) -> Classification:
    cause, correctable, supports = REASON_CODE_DEFAULTS[d.denial.carc]
    return Classification(root_cause=cause, correctable=correctable, evidence_supports_appeal=supports, evidence_lines=[],
                          confidence=FALLBACK_CONFIDENCE, reason=f"No structural rule fired; reason-code default for {d.denial.carc}.", source="reason_code")


def _best_action(c: Classification, allowed: float, table: dict) -> str:
    p, _ = probability.lookup(c, table)
    ev = router.expected_values(c, allowed, p)
    return max(router.ORDER, key=lambda a: (ev[a], -router.ORDER.index(a)))


def _disagreement(c1: Classification, mo2: classify.ModelOutcome, allowed: float, table: dict) -> str | None:
    """Return a review trigger when a second independent read leads to a different action, else None."""
    c2 = mo2.classification
    if c2 is None:
        return "second AI read failed validation; a person decides"
    a1, a2 = _best_action(c1, allowed, table), _best_action(c2, allowed, table)
    if a1 == a2:
        return None
    return (f"two AI reads disagree. Read 1: {c1.root_cause}, fixable {c1.correctable}, evidence supports appeal "
            f"{c1.evidence_supports_appeal}, so {a1}. Read 2: {c2.root_cause}, fixable {c2.correctable}, evidence supports "
            f"appeal {c2.evidence_supports_appeal}, so {a2}. Read 2 reason: {c2.reason}")


def _default_action(c: Classification) -> str:
    return "fix_and_resubmit" if c.correctable else "appeal" if c.evidence_supports_appeal else "write_off"


def run_one(d: DenialInput, config_name: str, rec: Recorder, table: dict) -> Result:
    did, allowed = d.denial_id, d.claim.expected_allowed_amount

    t = time.perf_counter()
    rec.emit(did, TraceStep(stage="load", summary=f"{d.denial.carc} denial from {d.payer.name}, {allowed:,.2f} USD allowed, {len(d.documentation)} documentation lines",
                            inputs={}, output={"carc": d.denial.carc, "payer_type": d.payer.type, "allowed": allowed, "doc_lines": len(d.documentation)}), started=t)

    if config_name == "b0_appeal_above_500":
        t = time.perf_counter()
        action = "appeal" if allowed > 500 else "write_off"
        decision = RouteDecision(action=action, overturn_probability=0.0, expected_values={}, trigger="baseline: appeal when allowed is above 500 USD")
        rec.emit(did, TraceStep(stage="route", summary=f"{action} ({decision.trigger})", inputs={"allowed": allowed}, output=decision.model_dump()), started=t)
        return Result(did, None, decision)

    t = time.perf_counter()
    model_cfg = MODEL_CONFIGS.get(config_name)
    use_rules = config_name.startswith("b2") or (model_cfg is not None and model_cfg[2])
    rr = rules.check(d) if use_rules else rules.RuleResult(False, None, rules.CARC_CANDIDATES.get(d.denial.carc, []))
    rec.emit(did, TraceStep(stage="rules", summary=f"resolved by {rr.rule}" if rr.resolved else "not resolved by structural rules",
                            inputs={"carc": d.denial.carc}, output={"resolved": rr.resolved, "rule": rr.rule, "candidates": rr.candidates}),
             started=t, confidence=1.0 if rr.resolved else None)

    t = time.perf_counter()
    cost, flags, force = 0.0, [], None
    if rr.resolved:
        c = rr.classification
        rec.emit(did, TraceStep(stage="classify", summary="skipped: rules resolved this denial", inputs={}, output={"skipped": True}), started=t)
    elif model_cfg:
        tier, thinking, _, reads = model_cfg
        mo = classify.classify(d, tier=tier, run_id=rec.run_id, thinking=thinking)
        cost, flags = (mo.result.cost_usd if mo.result else 0.0), mo.flags
        second = None
        if reads == 2 and mo.classification is not None:
            second = classify.classify(d, tier=tier, run_id=rec.run_id, thinking=thinking)
            cost += second.result.cost_usd if second.result else 0.0
        if mo.classification is None:
            c = reason_code_classification(d)
            force = "AI output failed validation twice; showing the reason-code default as the recommendation"
        else:
            c = mo.classification
            if "cited_suspicious_line" in flags:
                force = f"AI cited a line that tries to give it instructions ({', '.join(mo.suspicious_lines)})"
            elif second is not None:
                force = _disagreement(c, second, allowed, table)
                if force:
                    flags = [*flags, "reads_disagree"]
        rec.emit(did, TraceStep(stage="classify", summary=f"{config.MODELS[tier]['id']}{' with thinking' if thinking else ''}: {c.root_cause}, confidence {c.confidence:.2f}",
                                inputs={"prompt_version": config.CLASSIFY_PROMPT_VERSION, "model": config.MODELS[tier]["id"], "thinking": thinking},
                                output={**c.model_dump(), "suspicious_lines": mo.suspicious_lines, "error": mo.error},
                                model_called=True, cost_usd=round(cost, 6)), started=t, confidence=c.confidence, flags=flags)
    else:
        c = reason_code_classification(d)
        rec.emit(did, TraceStep(stage="classify", summary=f"reason-code fallback: {c.root_cause}", inputs={"carc": d.denial.carc},
                                output=c.model_dump()), started=t, confidence=c.confidence)

    if config_name == "b1_reason_code":
        t = time.perf_counter()
        action = _default_action(c)
        decision = RouteDecision(action=action, overturn_probability=0.0, expected_values={}, trigger=f"reason-code default for {d.denial.carc}")
        rec.emit(did, TraceStep(stage="route", summary=f"{action} ({decision.trigger})", inputs={"root_cause": c.root_cause}, output=decision.model_dump()), started=t)
        return Result(did, c, decision)

    t = time.perf_counter()
    p, row = probability.lookup(c, table)
    rec.emit(did, TraceStep(stage="probability", summary=f"overturn probability {p:.3f} from table row {row}", inputs={"row": row}, output={"p": p}), started=t)

    t = time.perf_counter()
    decision = router.route(c, allowed, p, force_review=force)
    ev = decision.expected_values
    rec.emit(did, TraceStep(stage="expected_value", summary=f"appeal {ev['appeal']:,.2f}, fix {ev['fix_and_resubmit']:,.2f}, write off 0.00 USD",
                            inputs={"p": p, "allowed": allowed, "correctable": c.correctable}, output=ev), started=t)
    t = time.perf_counter()
    risk = router.dollars_at_risk(ev)
    rec.emit(did, TraceStep(stage="route", summary=f"{decision.action}: {decision.trigger}",
                            inputs={"dollars_at_risk": risk, "expected_loss": router.expected_loss(ev, c.confidence)},
                            output=decision.model_dump()), started=t, confidence=c.confidence, flags=flags)
    return Result(did, c, decision, cost, flags)


def run(denials: list[DenialInput], config_name: str, write_events: bool = True) -> tuple[list[Result], Recorder]:
    if config_name not in CONFIGS:
        raise ValueError(f"unknown config {config_name!r}; choose from {CONFIGS}")
    versions = {"rules": rules.RULES_VERSION}
    if config_name in MODEL_CONFIGS:
        tier, thinking, _, reads = MODEL_CONFIGS[config_name]
        versions |= {"model": config.MODELS[tier]["id"], "prompt": config.CLASSIFY_PROMPT_VERSION, "thinking": str(thinking), "reads": str(reads)}
    rec = Recorder(config_name, versions=versions, write=write_events)
    table = probability.load_table()
    return [run_one(d, config_name, rec, table) for d in denials], rec
