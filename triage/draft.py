"""Grounded appeal letters for denials whose recommended action is appeal.

The drafter sees the same label-free record as the classifier, plus the classifier's findings. Every
letter goes through the citation checker. One retry carries the checker's reasons back to the model;
a second failure sends the denial to a person with the failed letter and the reasons attached.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from triage import citations, config, llm
from triage.classify import PROMPTS
from triage.load import model_payload
from triage.schema import Classification, DenialInput

DRAFT_PROMPT_VERSION = "draft_v5"
DRAFT_MAX_TOKENS = 2500   # raised from 900: Sonnet 5.5 thinks before answering and ran out on 8 of 61 letters

TOOL = {
    "name": "write_appeal_letter",
    "description": "Record the full appeal letter text.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["letter"],
        "properties": {"letter": {"type": "string"}},
    },
}


def system_prompt(version: str = DRAFT_PROMPT_VERSION) -> str:
    return (PROMPTS / f"{version}.md").read_text()


def user_message(d: DenialInput, c: Classification, do_not_cite: list[str]) -> str:
    p = model_payload(d)
    citable = citations.citable_fields(d)
    docs = "\n".join(f"{line['id']} [{line['source']}]: {line['text']}" for line in p["documentation"])
    findings = {"root_cause": c.root_cause, "evidence_lines": c.evidence_lines, "reason": c.reason,
                "case_strength": "supported" if c.evidence_supports_appeal else "limited"}
    return ("<denial_record>\n<citable_fields>\n" + json.dumps(citable, indent=1) + "\n</citable_fields>\n"
            "<denial_reason>" + p["denial"]["carc"] + ": " + p["denial"]["carc_text"] + "</denial_reason>\n"
            "<documentation>\n" + docs + "\n</documentation>\n</denial_record>\n\n"
            "<findings>\n" + json.dumps(findings, indent=1) + "\n</findings>\n"
            "<do_not_cite>" + json.dumps(do_not_cite) + "</do_not_cite>\n\n"
            "Write the appeal letter by calling write_appeal_letter.")


@dataclass
class DraftOutcome:
    denial_id: str
    letter: str | None
    passed: bool
    attempts: int
    reasons: list[str]
    needs_person: bool
    why_person: str | None
    cost_usd: float
    model: str
    words: int = 0
    flags: list[str] = field(default_factory=list)


def _not_empty(out: dict) -> None:
    if not str(out.get("letter", "")).strip():
        raise ValueError("empty letter")


def _check(letter: str, d: DenialInput, do_not_cite: list[str]) -> citations.CheckResult:
    r = citations.check(letter, d)
    banned = sorted({x for x in citations.CITE.findall(letter) if x in do_not_cite})
    if banned:
        r.reasons.append(f"cites {', '.join(banned)}, which were flagged as attempts to give instructions")
        r.passed = False
    return r


def draft(d: DenialInput, c: Classification, suspicious: list[str], tier: str = config.DRAFT_TIER, run_id: str | None = None) -> DraftOutcome:
    model = config.MODELS[tier]["id"]
    user = user_message(d, c, suspicious)
    cost, letter, reasons = 0.0, None, []
    for attempt in (1, 2):
        msg = user if attempt == 1 else (user + "\n\nYour previous letter failed the citation check:\n- " + "\n- ".join(reasons)
                                         + "\nRewrite the whole letter so every statement passes. Remove any fact you cannot cite exactly.")
        try:
            res = llm.call(tier=tier, system=system_prompt(), user=msg, tool=TOOL, purpose="draft", run_id=run_id,
                           max_tokens=DRAFT_MAX_TOKENS, validate=_not_empty,
                           max_attempts=1)
        except llm.InvalidOutput as e:
            cost += e.cost_usd
            reasons = ["no letter returned"]
            continue
        cost += res.cost_usd
        letter = res.output["letter"].strip()
        r = _check(letter, d, suspicious)
        reasons = r.reasons
        if r.passed:
            weak = not c.evidence_supports_appeal
            return DraftOutcome(d.denial_id, letter, True, attempt, [], weak,
                                "documentation does not clearly meet the payer's criteria; a person reviews before sending" if weak else None,
                                cost, model, len(letter.split()), ["needed_retry"] if attempt == 2 else [])
    return DraftOutcome(d.denial_id, letter, False, 2, reasons, True, "letter failed the citation check twice", cost, model,
                        len(letter.split()) if letter else 0, ["failed_check_twice"])


# ---------------------------------------------------------------- deterministic fake for mock mode
def _mock(user: str) -> dict:
    fields = json.loads(re.search(r"<citable_fields>\n(.*?)\n</citable_fields>", user, re.S).group(1))
    ev = json.loads(re.search(r"<findings>\n(.*?)\n</findings>", user, re.S).group(1))["evidence_lines"]
    cite = "".join(f"[{x}]" for x in ev) or "[claim.claim_id]"
    return {"letter": (f"Re: claim {fields['claim.claim_id']} [claim.claim_id], service date {fields['claim.service_date']} [claim.service_date].\n"
                       f"We ask that you reverse this denial and pay the claim.\n"
                       f"The documentation supports payment {cite}.\n"
                       f"Please reconsider; further records are available on request.")}


llm.register_mock(TOOL["name"], _mock)
