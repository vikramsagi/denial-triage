"""Two independent reads: disagreement sends the denial to a person with both readings attached."""

from triage import classify, llm, pipeline
from triage.load import load_split
from triage.observe import Recorder
from triage import probability


def _run_with_reads(first, second, denial_id="DN-14039"):
    d = next(x for x in load_split("dev") if x.denial_id == denial_id)
    calls = []

    def fake(user):
        calls.append(1)
        base = classify._mock(user)
        return base | (first if len(calls) % 2 == 1 else second)
    llm.register_mock(classify.TOOL["name"], fake)
    try:
        rec = Recorder("m_rules_small_think_x2", versions={}, write=False)
        return pipeline.run_one(d, "m_rules_small_think_x2", rec, probability.load_table()), len(calls)
    finally:
        llm.register_mock(classify.TOOL["name"], classify._mock)


def test_reads_agree_routes_normally():
    same = {"root_cause": "medical_necessity", "correctable": True, "evidence_supports_appeal": False}
    r, n = _run_with_reads(same, same)
    assert n == 2 and r.decision.action == "fix_and_resubmit" and "reads_disagree" not in r.flags


def test_reads_disagree_go_to_a_person_with_both_readings():
    fix = {"root_cause": "medical_necessity", "correctable": True, "evidence_supports_appeal": False}
    no_fix = {"root_cause": "medical_necessity", "correctable": False, "evidence_supports_appeal": False}
    r, n = _run_with_reads(fix, no_fix)
    assert r.decision.action == "human_review" and "reads_disagree" in r.flags
    assert "Read 1" in r.decision.trigger and "Read 2" in r.decision.trigger
    assert r.decision.recommended_action and r.decision.rationale


def test_rule_settled_denials_skip_both_reads():
    d = next(x for x in load_split("dev") if pipeline.rules.check(x).resolved)
    rec = Recorder("m_rules_small_think_x2", versions={}, write=False)
    r = pipeline.run_one(d, "m_rules_small_think_x2", rec, probability.load_table())
    assert r.cost_usd == 0.0
