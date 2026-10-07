"""Data contracts shared by every stage. Model-facing types never carry labels."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RootCause = Literal[
    "registration_eligibility",
    "coding_error",
    "prior_authorization",
    "medical_necessity",
    "coordination_of_benefits",
    "timely_filing",
    "duplicate_claim",
    "non_covered_service",
]
Action = Literal["appeal", "fix_and_resubmit", "write_off", "human_review"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Payer(Strict):
    name: str
    type: str
    filing_limit_days: int


class Denial(Strict):
    carc: str
    carc_text: str
    denial_date: str


class ClaimLine(Strict):
    cpt: str
    modifiers: list[str]
    units: int


class Claim(Strict):
    member_id: str
    service_date: str
    submitted_date: str
    place_of_service: str
    provider_specialty: str
    lines: list[ClaimLine]
    icd10: list[str]
    prior_auth_number: str | None
    billed_amount: float
    expected_allowed_amount: float


class DocLine(Strict):
    id: str
    source: str
    text: str


class DenialInput(Strict):
    """Everything the system may see. `extra="forbid"` rejects a record that still carries labels."""

    denial_id: str
    payer: Payer
    denial: Denial
    claim: Claim
    documentation: list[DocLine]


class Classification(Strict):
    root_cause: RootCause
    correctable: bool
    evidence_supports_appeal: bool
    evidence_lines: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    source: Literal["rules", "reason_code", "model"]


class RouteDecision(Strict):
    action: Action
    overturn_probability: float
    expected_values: dict[str, float]
    trigger: str
    # The system's own choice and why. Always filled, including when the action is human_review,
    # so a reviewer sees what the system would have done and its reasoning.
    recommended_action: Action | None = None
    rationale: str = ""


class TraceStep(Strict):
    stage: str
    summary: str
    inputs: dict[str, Any]
    output: dict[str, Any]
    model_called: bool = False
    cost_usd: float = 0.0
