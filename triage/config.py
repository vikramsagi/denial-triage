"""Single source of truth for economics, thresholds, budget, and model IDs and prices.

Every cost figure here is an assumption for synthetic data. Sources are listed in docs/data-card.md.
"""

# ---------------------------------------------------------------- economics (USD)
# Appeal cost depends on the kind of appeal. Clinical appeals need a clinician-reviewed letter
# and records; administrative appeals need proof documents only.
APPEAL_COST_ADMINISTRATIVE = 57.0   # Premier (2023 data, pub. 2025): 57.23 USD average cost to adjudicate a claim
APPEAL_COST_CLINICAL = 108.0        # 57.23 + 51.20 USD added clinical labor per inpatient surgery claim (AMA via Premier, 2024)
FIX_AND_RESUBMIT_COST = 25.0        # Change Healthcare 2020 Denials Index: 25.20 USD to rework a claim
FIX_SUCCESS_RATE = 0.95             # Assumption: a truly correctable denial pays 95% of allowed
HUMAN_REVIEW_COST = 15.0            # BLS 2025: 24.59 USD/hr x 1.43 benefits load x 25 min (CAQH 2024 manual transaction time)

CLINICAL_ROOT_CAUSES = {"medical_necessity", "prior_authorization"}

# ---------------------------------------------------------------- routing
# High-risk review: every claim at or above this amount goes to a person, with the system's
# recommendation and reasoning attached. See docs/assumptions.md.
HUMAN_REVIEW_AMOUNT_THRESHOLD = 5000.0
# Not used: model confidence did not predict errors on dev. Two independent reads decide instead
# (docs/adr/ADR-004-two-read-agreement-check.md).
HUMAN_REVIEW_CONFIDENCE_CUTOFF = None
HUMAN_QUEUE_CAPACITY = None

# ---------------------------------------------------------------- models (prices in USD per million tokens)
# Verified 2026-10-07 against https://platform.claude.com/docs/en/about-claude/pricing
MODELS = {
    "small": {"id": "claude-haiku-4-5-20251001", "input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    "large": {"id": "claude-sonnet-5-5", "input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20,
              "forced_tool": False,  # this model rejects tool_choice "tool"; the tool is offered with "auto"
              "thinking": "adaptive"},  # this model takes adaptive thinking with an effort level, not a token budget
    "judge": {"id": "claude-opus-5-5", "input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.40,
              "forced_tool": False, "thinking": "adaptive"},  # grades letters; a different, stronger model than the writer
}
THINKING_EFFORT = "medium"  # for models with adaptive thinking
BATCH_DISCOUNT = 0.50
CLASSIFY_MAX_TOKENS = 1000   # raised from 600: longer reason-first answers were cut off
THINKING_BUDGET_TOKENS = 1500   # reasoning tokens allowed before the answer, for the "thinking" arms
CLASSIFY_PROMPT_VERSION = "classify_v4"
DRAFT_TIER = "large"   # appeal letters: Claude Sonnet 5.5 passed the citation checker on 61 of 61 dev letters, Haiku 4.5 on 42   # earlier versions kept unchanged in prompts/ for comparison

# ---------------------------------------------------------------- budget
BUDGET_CAP_USD = 40.0

# ---------------------------------------------------------------- taxonomy
ROOT_CAUSES = [
    "registration_eligibility",
    "coding_error",
    "prior_authorization",
    "medical_necessity",
    "coordination_of_benefits",
    "timely_filing",
    "duplicate_claim",
    "non_covered_service",
]

ACTIONS = ["appeal", "fix_and_resubmit", "write_off", "human_review"]


def appeal_cost(root_cause: str) -> float:
    return APPEAL_COST_CLINICAL if root_cause in CLINICAL_ROOT_CAUSES else APPEAL_COST_ADMINISTRATIVE


def action_values(root_cause: str, allowed: float, overturn_p: float, correctable: bool) -> dict[str, float]:
    """Value of each terminal action under the value rules in docs/data-card.md, computed from true labels."""
    return {
        "appeal": round(overturn_p * allowed - appeal_cost(root_cause), 2),
        "fix_and_resubmit": round(FIX_SUCCESS_RATE * allowed - FIX_AND_RESUBMIT_COST, 2)
        if correctable
        else -FIX_AND_RESUBMIT_COST,
        "write_off": 0.0,
    }


def best_action(root_cause: str, allowed: float, overturn_p: float, correctable: bool) -> str:
    values = action_values(root_cause, allowed, overturn_p, correctable)
    # Ties resolve toward the cheaper, simpler action: write_off, then fix, then appeal.
    order = ["write_off", "fix_and_resubmit", "appeal"]
    return max(order, key=lambda a: (values[a], -order.index(a)))
