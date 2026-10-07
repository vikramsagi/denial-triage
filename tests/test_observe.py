from triage import pipeline
from triage.load import load_split

EXPECTED = {"b0_appeal_above_500": ["load", "route"],
            "b1_reason_code": ["load", "rules", "classify", "route"],
            "b2_rules_ev": ["load", "rules", "classify", "probability", "expected_value", "route"],
            "m_rules_small": ["load", "rules", "classify", "probability", "expected_value", "route"]}


def test_every_stage_emits_an_event():
    denials = load_split("dev")[:25]
    for config_name, stages in EXPECTED.items():
        _, rec = pipeline.run(denials, config_name, write_events=False)
        for d in denials:
            assert [s.stage for s in rec.traces[d.denial_id]] == stages
        assert all(e["versions"]["config"] and e["latency_ms"] >= 0 for e in rec.events)
