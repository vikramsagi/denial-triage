"""Monitoring and the feedback loop, on small hand-built inputs."""

from triage import feedback, monitor


def test_psi_is_zero_for_identical_and_large_for_a_shift():
    assert monitor.psi([0.5, 0.5], [0.5, 0.5]) == 0
    assert monitor.psi([0.9, 0.1], [0.3, 0.7]) > monitor.PSI_ALERT


def test_compare_flags_a_review_queue_jump():
    base = {"route_mix": {r: 0.25 for r in monitor.ROUTES}, "cause_mix": {"coding_error": 1.0}, "confidence_hist": [0, 0, 0, 1, 0, 0],
            "rules_share": 0.3, "disagree_rate": 0.03, "review_share": 0.075, "injection_flag_rate": 0.05,
            "mean_appeal_win_odds": 0.5, "cost_per_denial_usd": 0.01}
    cur = dict(base, review_share=0.20)
    levels = {c["signal"]: c["level"] for c in monitor.compare(base, cur).checks}
    assert levels["review_share"] == "alert" and levels["rules_share"] == "ok"


def test_correction_is_shrunk_toward_one():
    # 10 appeals expected to win 6, only 1 won: the factor drops, but not all the way to 1/6
    f = feedback.correction(wins=1, n=10, expected=6.0)
    assert 1 / 6 < f < 0.6
    assert feedback.correction(wins=6, n=10, expected=6.0) == 1.0


def test_small_cells_are_not_corrected():
    recs = [{"denial_id": f"d{i}", "payer": "P", "pred_cause": "prior_authorization", "p": 0.6, "route": "appeal"} for i in range(3)]
    out = feedback.recalibrate(recs, [{"denial_id": f"d{i}", "won": False} for i in range(3)])
    assert out["factors"] == {}
