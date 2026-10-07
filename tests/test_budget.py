import pytest

from triage import budget, llm


def test_records_and_totals():
    budget.record(model="m", purpose="classify", usage={}, cost_usd=0.25, run_id="r", mock=False)
    budget.record(model="m", purpose="classify", usage={}, cost_usd=0.50, run_id="r", mock=False)
    assert budget.total_usd() == 0.75


def test_refuses_call_that_would_pass_cap():
    budget.record(model="m", purpose="classify", usage={}, cost_usd=39.99, run_id="r", mock=False)
    with pytest.raises(budget.BudgetExceeded):
        budget.check(0.02)
    budget.check(0.005)


def test_llm_call_is_refused_once_cap_is_reached():
    budget.record(model="m", purpose="classify", usage={}, cost_usd=40.0, run_id="r", mock=False)
    llm.register_mock("t", lambda u: {"ok": True})
    with pytest.raises(budget.BudgetExceeded):
        llm.call(tier="small", system="s", user="u", tool={"name": "t"}, purpose="test")


def test_cost_from_usage_matches_price_table():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}
    assert llm.cost_of("small", usage) == pytest.approx(1.00 + 5.00 + 0.10)
    assert llm.cost_of("small", usage, batch=True) == pytest.approx((1.00 + 5.00 + 0.10) / 2)
