"""Deterministic rules check. Runs before any model.

Rules read only structure: reason codes, claim fields, and the formats of IDs, codes, and dates.
They never match wording, so they behave the same on phrasings they have never seen. A rule
resolves a denial only when its signal is unambiguous; everything else goes to the classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from triage.schema import Classification, DenialInput

RULES_VERSION = "1.0.0"

# Plausible root causes for each reason code, from the public CARC definitions. Used for the
# reason-code baseline and shown in the trace. A code with several candidates cannot be resolved alone.
CARC_CANDIDATES: dict[str, list[str]] = {
    "CO-4": ["coding_error", "duplicate_claim", "prior_authorization"],
    "CO-11": ["coding_error"],
    "CO-15": ["prior_authorization"],
    "CO-16": ["registration_eligibility", "coding_error", "prior_authorization", "medical_necessity", "coordination_of_benefits", "duplicate_claim"],
    "CO-18": ["duplicate_claim"],
    "CO-22": ["coordination_of_benefits"],
    "CO-27": ["registration_eligibility"],
    "CO-29": ["timely_filing"],
    "CO-31": ["registration_eligibility", "coordination_of_benefits"],
    "CO-50": ["medical_necessity", "prior_authorization", "coding_error", "non_covered_service"],
    "CO-96": ["non_covered_service", "medical_necessity"],
    "CO-197": ["prior_authorization"],
    "CO-204": ["non_covered_service", "medical_necessity"],
    "CO-252": ["medical_necessity"],
}

MEMBER_ID = re.compile(r"\bW\d{8}\b")
AUTH_NO = re.compile(r"\bPA-\d{7}\b")
CLAIM_ID = re.compile(r"\bCLM-\d{6}\b")
ICD10 = re.compile(r"\b[A-TV-Z]\d{2}\.\d{1,4}\b")
ISO_DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
NONSPECIFIC_DX = {"Z00.00"}


@dataclass
class RuleResult:
    resolved: bool
    rule: str | None
    candidates: list[str]
    classification: Classification | None = None
    checked: list[str] = field(default_factory=list)


def _is_adjacent_transposition(a: str, b: str) -> bool:
    if len(a) != len(b) or a == b:
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def _lines_matching(d: DenialInput, pattern: re.Pattern) -> list[str]:
    return [line.id for line in d.documentation if pattern.search(line.text)]


def _resolved(rule: str, candidates: list[str], cause: str, correctable: bool, supports: bool, lines: list[str], reason: str) -> RuleResult:
    c = Classification(root_cause=cause, correctable=correctable, evidence_supports_appeal=supports,
                       evidence_lines=lines, confidence=1.0, reason=reason, source="rules")
    return RuleResult(True, rule, candidates, c)


def check(d: DenialInput) -> RuleResult:
    carc = d.denial.carc
    candidates = CARC_CANDIDATES.get(carc, [])
    claim = d.claim
    checked: list[str] = []

    # R1. The claim's member ID is a two-digit swap of an ID found in the documentation.
    checked.append("transposed_member_id")
    for line in d.documentation:
        for found in MEMBER_ID.findall(line.text):
            if _is_adjacent_transposition(claim.member_id, found):
                return _resolved("transposed_member_id", candidates, "registration_eligibility", True, False, [line.id],
                                 f"Claim member ID {claim.member_id} is a digit swap of {found} on file.")

    # R2. An authorization number exists in the documentation but the claim field is empty.
    checked.append("auth_on_file_not_on_claim")
    auth_lines = _lines_matching(d, AUTH_NO)
    if claim.prior_auth_number is None and auth_lines:
        return _resolved("auth_on_file_not_on_claim", candidates, "prior_authorization", True, False, auth_lines,
                         "An authorization number is on file but missing from the claim.")

    # R3. Duplicate denial and a prior claim ID appears in the documentation.
    checked.append("prior_claim_on_file")
    claim_lines = _lines_matching(d, CLAIM_ID)
    if carc == "CO-18" and claim_lines:
        return _resolved("prior_claim_on_file", candidates, "duplicate_claim", False, False, claim_lines,
                         "Duplicate denial and a prior claim for the same service is on file.")

    # R4. The claim carries a nonspecific diagnosis while the note documents a specific one.
    checked.append("nonspecific_diagnosis")
    if set(claim.icd10) & NONSPECIFIC_DX:
        dx_lines = [line.id for line in d.documentation if set(ICD10.findall(line.text)) - NONSPECIFIC_DX]
        if dx_lines:
            return _resolved("nonspecific_diagnosis", candidates, "coding_error", True, False, dx_lines,
                             "The claim diagnosis is nonspecific and the note documents a specific diagnosis.")

    # R5. Timely filing: is there a documented submission date inside the payer's filing window?
    checked.append("filing_window")
    if carc == "CO-29":
        dos = date.fromisoformat(claim.service_date)
        window_end = dos + timedelta(days=d.payer.filing_limit_days)
        inside = [line.id for line in d.documentation
                  if any(dos < date.fromisoformat(x) <= window_end for x in ISO_DATE.findall(line.text))]
        if inside:
            return _resolved("filing_window", candidates, "timely_filing", False, True, inside,
                             f"A submission dated inside the {d.payer.filing_limit_days}-day filing window is documented.")
        return _resolved("filing_window", candidates, "timely_filing", False, False, [],
                         f"No submission inside the {d.payer.filing_limit_days}-day filing window is documented.")

    return RuleResult(False, None, candidates, None, checked)
