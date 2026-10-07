"""Regression suite: 20 golden dev denials must keep their route and expected values.

Model answers are saved in tests/golden_routes.json, so this runs in mock mode with no model calls. It
fails when a change to rules, the win odds table, or the router moves a route or a value. If a change is
intended, regenerate the golden file and say why in the commit message.
"""

import json
from pathlib import Path

import pytest

from triage import classify, llm, pipeline, probability
from triage.load import load_split
from triage.observe import Recorder

GOLDEN = json.loads((Path(__file__).parent / "golden_routes.json").read_text())


@pytest.fixture(scope="module")
def results():
    denials = {d.denial_id: d for d in load_split("dev")}
    answers = {classify.user_message(denials[g["denial_id"]]): g["model_answer"] for g in GOLDEN["records"] if g["model_answer"]}
    llm.register_mock(classify.TOOL["name"], lambda user: answers[user])
    try:
        rec, table = Recorder("m_rules_small_think", versions={}, write=False), probability.load_table()
        return {g["denial_id"]: pipeline.run_one(denials[g["denial_id"]], "m_rules_small_think", rec, table) for g in GOLDEN["records"]}
    finally:
        llm.register_mock(classify.TOOL["name"], classify._mock)


@pytest.mark.parametrize("g", GOLDEN["records"], ids=[g["denial_id"] for g in GOLDEN["records"]])
def test_route_and_values_unchanged(results, g):
    r = results[g["denial_id"]]
    assert r.decision.action == g["route"], g["why_chosen"]
    assert r.decision.recommended_action == g["recommended_action"]
    for action, value in g["expected_values"].items():
        assert r.decision.expected_values[action] == pytest.approx(value, abs=0.01)
