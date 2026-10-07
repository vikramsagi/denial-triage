import pytest

from triage import budget, llm


def test_mock_mode_is_on_in_tests():
    assert llm.mock_mode()


def test_invalid_answer_is_retried_once_then_raises():
    calls = []
    llm.register_mock("t", lambda u: calls.append(u) or {"x": 1})

    def reject(out):
        raise ValueError("bad")

    with pytest.raises(llm.InvalidOutput) as e:
        llm.call(tier="small", system="s", user="u", tool={"name": "t"}, purpose="test", validate=reject)
    assert len(calls) == 2 and "rejected" in calls[1] and len(e.value.errors) == 2


def test_every_call_is_written_to_the_ledger():
    llm.register_mock("t", lambda u: {"x": 1})
    llm.call(tier="small", system="s", user="u", tool={"name": "t"}, purpose="test", run_id="abc")
    assert [e["run_id"] for e in budget.entries()] == ["abc"] and budget.entries()[0]["mock"] is True


def test_module_scope_is_mock_too():
    """Guards the import-time setting in conftest: module fixtures run before per-test fixtures."""
    import os
    assert os.environ["TRIAGE_MOCK"] == "1" and "ANTHROPIC_API_KEY" not in os.environ
