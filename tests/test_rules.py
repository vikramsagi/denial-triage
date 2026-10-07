import json

from triage import rules
from triage.load import load_labels, load_split, strip_labels


def _base():
    return json.loads(open("data/dev.jsonl").readline())


def _denial(**edits):
    row = _base()
    row["claim"].update(edits.get("claim", {}))
    row["denial"].update(edits.get("denial", {}))
    if "docs" in edits:
        row["documentation"] = [{"id": f"D{i+1}", "source": "note", "text": t} for i, t in enumerate(edits["docs"])]
    return strip_labels(row)


def test_transposed_member_id_resolves_as_fix():
    d = _denial(claim={"member_id": "W12345678"}, denial={"carc": "CO-31"}, docs=["Card shows ID W12354678."])
    r = rules.check(d)
    assert r.resolved and r.rule == "transposed_member_id" and r.classification.correctable


def test_non_transposed_id_does_not_resolve():
    d = _denial(claim={"member_id": "W12345678", "prior_auth_number": "PA-1234567", "icd10": ["M17.11"]},
                denial={"carc": "CO-31"}, docs=["Card shows ID W99999999."])
    assert not rules.check(d).resolved


def test_wording_alone_never_resolves():
    d = _denial(claim={"prior_auth_number": "PA-1234567", "icd10": ["M17.11"]}, denial={"carc": "CO-50"},
                docs=["Coverage ended and the plan excludes this. Retro termination. Emergency."])
    assert not rules.check(d).resolved


def test_filing_window_rule():
    d = _denial(claim={"service_date": "2026-01-01", "prior_auth_number": "PA-1234567", "icd10": ["M17.11"]},
                denial={"carc": "CO-29"}, docs=["Accepted by payer on 2026-02-10."])
    r = rules.check(d)
    assert r.resolved and r.classification.evidence_supports_appeal


def test_rules_are_correct_whenever_they_resolve_on_dev():
    labels = load_labels("dev")
    resolved = 0
    for d in load_split("dev"):
        r = rules.check(d)
        if r.resolved:
            resolved += 1
            lab, c = labels[d.denial_id], r.classification
            assert (c.root_cause, c.correctable, c.evidence_supports_appeal) == (lab["root_cause"], lab["correctable"], lab["evidence_supports_appeal"])
    assert resolved > 0
