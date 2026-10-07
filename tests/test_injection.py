"""Documentation is untrusted. Injected lines must not change instructions, schema, or routing."""

import json

from triage import classify, pipeline
from triage.load import load_labels, load_split


def _adversarial():
    labels = load_labels("dev")
    return [d for d in load_split("dev") if labels[d.denial_id]["is_adversarial"]], labels


def test_documentation_is_inside_untrusted_tags_and_system_prompt_is_fixed():
    ds, labels = _adversarial()
    sys_before = classify.system_prompt()
    for d in ds:
        msg = classify.user_message(d)
        inj = labels[d.denial_id]["injection"]["line_id"]
        text = next(l.text for l in d.documentation if l.id == inj)
        start, end = msg.index("<documentation>"), msg.index("</documentation>")
        assert start < msg.index(text) < end
        assert classify.system_prompt() == sys_before
        assert "never an instruction" in sys_before and "suspicious_lines" in sys_before


def test_tool_schema_is_closed():
    assert classify.TOOL["input_schema"]["additionalProperties"] is False
    assert set(classify.TOOL["input_schema"]["properties"]["root_cause"]["enum"]) == set(json.loads(json.dumps(classify.TOOL))["input_schema"]["properties"]["root_cause"]["enum"])


def test_mock_flags_injected_lines_and_never_cites_them():
    ds, labels = _adversarial()
    for d in ds:
        out = classify.classify(d)
        inj = labels[d.denial_id]["injection"]["line_id"]
        assert inj in out.suspicious_lines and inj not in out.classification.evidence_lines


def test_citing_a_suspicious_line_routes_to_a_person(monkeypatch):
    from triage import rules
    ds, labels = _adversarial()
    d = next(x for x in ds if not rules.check(x).resolved)
    inj = labels[d.denial_id]["injection"]["line_id"]
    real = classify._mock

    def bad(user):
        out = real(user)
        out["evidence_lines"] = [inj]
        return out

    monkeypatch.setitem(classify.llm._MOCKS, classify.TOOL["name"], bad)
    results, _ = pipeline.run([d], "m_rules_small", write_events=False)
    r = results[0]
    assert "cited_suspicious_line" in r.flags
    assert r.decision.action == "human_review" and "instructions" in r.decision.trigger
    assert r.decision.recommended_action and r.decision.rationale


def test_invalid_output_twice_routes_to_a_person(monkeypatch):
    from triage import rules
    d = next(x for x in load_split("dev") if not rules.check(x).resolved and x.claim.expected_allowed_amount < 5000)
    monkeypatch.setitem(classify.llm._MOCKS, classify.TOOL["name"], lambda u: {"root_cause": "nonsense"})
    results, _ = pipeline.run([d], "m_rules_small", write_events=False)
    r = results[0]
    assert r.decision.action == "human_review" and "failed validation" in r.decision.trigger
    assert "invalid_output_twice" in r.flags and r.decision.recommended_action


def test_every_prompt_version_keeps_the_untrusted_data_rule():
    for v in ["classify_v1", "classify_v2", "classify_v3"]:
        text = classify.system_prompt(v)
        assert "<denial_record>" in text and "suspicious_lines" in text


def test_fixed_part_first_and_denial_last():
    d = load_split("dev")[0]
    msg = classify.user_message(d)
    assert msg.startswith("<denial_record>") and msg.rstrip().endswith("calling record_classification.")
    assert d.denial_id not in classify.system_prompt()


def test_v3_answer_form_puts_reason_first():
    t = classify.tool_for("classify_v3")
    assert list(t["input_schema"]["properties"])[0] == "reason"
    assert t["input_schema"]["additionalProperties"] is False
    assert list(classify.tool_for("classify_v2")["input_schema"]["properties"])[0] == "root_cause"
