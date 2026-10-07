"""Drafting flow in mock mode: retry with checker reasons, then a person."""

import pytest

from triage import draft, llm
from triage.load import load_split
from triage.schema import Classification


@pytest.fixture(scope="module")
def rec():
    return next(d for d in load_split("dev") if d.denial_id == "DN-39870")


def _cls(supports=True):
    return Classification(root_cause="medical_necessity", correctable=False, evidence_supports_appeal=supports,
                          evidence_lines=["D2", "D5"], confidence=0.9, reason="test", source="model")


GOOD = "The record documents 10 weeks of failed conservative management [D5]."
BAD = "The record documents 12 weeks of failed conservative management [D5]."


def _script(letters):
    seen = []

    def fake(user):
        seen.append(user)
        return {"letter": letters[len(seen) - 1]}
    llm.register_mock(draft.TOOL["name"], fake)
    return seen


@pytest.fixture(autouse=True)
def restore_mock():
    yield
    llm.register_mock(draft.TOOL["name"], draft._mock)


def test_pass_first_try(rec):
    _script([GOOD])
    o = draft.draft(rec, _cls(), [])
    assert o.passed and o.attempts == 1 and not o.needs_person


def test_retry_carries_reasons_then_passes(rec):
    seen = _script([BAD, GOOD])
    o = draft.draft(rec, _cls(), [])
    assert o.passed and o.attempts == 2 and "needed_retry" in o.flags
    assert "12 does not appear" in seen[1]


def test_two_failures_go_to_a_person(rec):
    _script([BAD, BAD])
    o = draft.draft(rec, _cls(), [])
    assert not o.passed and o.needs_person and o.reasons


def test_limited_case_goes_to_a_person_even_when_it_passes(rec):
    _script([GOOD])
    o = draft.draft(rec, _cls(supports=False), [])
    assert o.passed and o.needs_person


def test_citing_a_flagged_line_fails(rec):
    _script(["The record documents 10 weeks of failed conservative management [D5].",
             "The record documents 10 weeks of failed conservative management [D5]."])
    o = draft.draft(rec, _cls(), ["D5"])
    assert not o.passed and "flagged" in o.reasons[0]


def test_prompt_has_no_labels(rec):
    msg = draft.user_message(rec, _cls(), [])
    for word in ["best_action", "true_overturn", "labels", "is_adversarial"]:
        assert word not in msg
