from triage import router
from triage.schema import Classification


def _c(cause="medical_necessity", correctable=False, supports=True, confidence=0.9):
    return Classification(root_cause=cause, correctable=correctable, evidence_supports_appeal=supports,
                          evidence_lines=[], confidence=confidence, reason="", source="model")


def test_appeal_when_expected_recovery_beats_cost():
    d = router.route(_c(), allowed=1000, p=0.5, review_threshold=None)
    assert d.action == "appeal" and d.expected_values["appeal"] == 0.5 * 1000 - 108


def test_write_off_when_appeal_is_negative():
    assert router.route(_c(), allowed=300, p=0.2, review_threshold=None).action == "write_off"


def test_fix_beats_appeal_when_correctable():
    assert router.route(_c(correctable=True), allowed=1000, p=0.5, review_threshold=None).action == "fix_and_resubmit"


def test_high_risk_claim_goes_to_human_with_recommendation_and_reasoning():
    d = router.route(_c(), allowed=5000, p=0.5)
    assert d.action == "human_review"
    assert d.recommended_action == "appeal"
    assert "Win odds 0.50" in d.rationale and "appeal" in d.rationale
    assert router.route(_c(), allowed=4999.99, p=0.5).action == "appeal"


def test_every_decision_carries_a_recommendation():
    for allowed in [100, 1000, 6000]:
        d = router.route(_c(), allowed=allowed, p=0.3)
        assert d.recommended_action in {"appeal", "fix_and_resubmit", "write_off"} and d.rationale


def test_dollars_at_risk_and_expected_loss():
    ev = {"appeal": 7512.0, "fix_and_resubmit": -25.0, "write_off": 0.0}
    assert router.dollars_at_risk(ev) == 7512.0
    assert router.expected_loss(ev, 0.72) == round(0.28 * 7512.0, 2)


def test_confidence_cutoff_sends_to_human():
    d = router.route(_c(confidence=0.4), allowed=1000, p=0.5, review_threshold=None, confidence_cutoff=0.6)
    assert d.action == "human_review"


def test_small_cell_with_no_wins_stays_near_zero():
    """A small cell where no appeal ever won must not borrow win odds from strong appeals of the same cause."""
    from triage import probability

    labs = {f"a{i}": {"root_cause": "timely_filing", "evidence_supports_appeal": False, "correctable": False,
                      "true_overturn_probability": 0.0} for i in range(5)}
    labs |= {f"b{i}": {"root_cause": "timely_filing", "evidence_supports_appeal": True, "correctable": False,
                       "true_overturn_probability": 0.85} for i in range(5)}
    labs |= {f"c{i}": {"root_cause": "coding_error", "evidence_supports_appeal": False, "correctable": False,
                       "true_overturn_probability": 0.0} for i in range(10)}
    t = probability.fit(labs)
    assert t["cells"]["timely_filing|supports=False|correctable=False"]["p"] == 0.0
