"""Model classification for denials the rules could not settle.

The prompt is built only from `load.model_payload`, so labels can never reach the model. The
documentation is wrapped in tags and marked as untrusted data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from triage import config, llm
from triage.load import model_payload
from triage.schema import Classification, DenialInput

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

TOOL = {
    "name": "record_classification",
    "description": "Record the root cause, recovery assessment, evidence, and confidence for one denial.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["root_cause", "correctable", "evidence_supports_appeal", "evidence_lines", "suspicious_lines", "confidence", "reason"],
        "properties": {
            "root_cause": {"type": "string", "enum": config.ROOT_CAUSES},
            "correctable": {"type": "boolean"},
            "evidence_supports_appeal": {"type": "boolean"},
            "evidence_lines": {"type": "array", "items": {"type": "string"}},
            "suspicious_lines": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
    },
}


REASON_FIRST_VERSIONS = {"classify_v3"}


def tool_for(version: str | None = None) -> dict:
    """The answer form. From v3 on, `reason` comes first so the model explains before it decides."""
    v = version or config.CLASSIFY_PROMPT_VERSION
    if v not in REASON_FIRST_VERSIONS:
        return TOOL
    props = TOOL["input_schema"]["properties"]
    order = ["reason", "root_cause", "correctable", "evidence_supports_appeal", "evidence_lines", "suspicious_lines", "confidence"]
    return {**TOOL, "input_schema": {**TOOL["input_schema"], "required": order, "properties": {k: props[k] for k in order}}}


def system_prompt(version: str | None = None) -> str:
    """Fixed instructions, identical for every denial, so they come first and can be cached."""
    return (PROMPTS / f"{version or config.CLASSIFY_PROMPT_VERSION}.md").read_text()


def user_message(d: DenialInput) -> str:
    """The part that changes on every call: one denial, then the request, at the end."""
    p = model_payload(d)
    header = {"payer": p["payer"], "denial": p["denial"], "claim": p["claim"]}
    docs = "\n".join(f"{line['id']} [{line['source']}]: {line['text']}" for line in p["documentation"])
    return ("<denial_record>\n<structured_fields>\n" + json.dumps(header, indent=1) + "\n</structured_fields>\n"
            "<documentation>\n" + docs + "\n</documentation>\n</denial_record>\n\n"
            "Classify this denial by calling record_classification.")


@dataclass
class ModelOutcome:
    classification: Classification | None
    suspicious_lines: list[str]
    flags: list[str]
    result: llm.LLMResult | None
    error: str | None = None


def _validator(d: DenialInput):
    ids = {line.id for line in d.documentation}

    def check(out: dict) -> None:
        missing = [k for k in TOOL["input_schema"]["required"] if k not in out]
        if missing:
            raise ValueError(f"missing fields {missing}")
        if out["root_cause"] not in config.ROOT_CAUSES:
            raise ValueError(f"unknown root cause {out['root_cause']!r}")
        bad = [x for x in out["evidence_lines"] + out["suspicious_lines"] if x not in ids]
        if bad:
            raise ValueError(f"line IDs not in the documentation: {bad}")
        if not out["evidence_lines"]:
            raise ValueError("evidence_lines is empty")
        if not 0 <= float(out["confidence"]) <= 1:
            raise ValueError("confidence must be between 0 and 1")
    return check


def classify(d: DenialInput, tier: str = "small", run_id: str | None = None, thinking: bool = False) -> ModelOutcome:
    try:
        res = llm.call(tier=tier, system=system_prompt(), user=user_message(d), tool=tool_for(), purpose="classify",
                       run_id=run_id, validate=_validator(d), thinking=thinking)
    except llm.InvalidOutput as e:
        return ModelOutcome(None, [], ["invalid_output_twice"], None, str(e))
    out = res.output
    flags = []
    cited_suspicious = sorted(set(out["evidence_lines"]) & set(out["suspicious_lines"]))
    if cited_suspicious:
        flags.append("cited_suspicious_line")
    if out["suspicious_lines"]:
        flags.append("injection_attempt_detected")
    if res.attempts > 1:
        flags.append("needed_retry")
    c = Classification(root_cause=out["root_cause"], correctable=bool(out["correctable"]),
                       evidence_supports_appeal=bool(out["evidence_supports_appeal"]),
                       evidence_lines=[x for x in out["evidence_lines"] if x not in out["suspicious_lines"]] or out["evidence_lines"],
                       confidence=float(out["confidence"]), reason=str(out["reason"])[:700], source="model")
    return ModelOutcome(c, list(out["suspicious_lines"]), flags, res)


# ---------------------------------------------------------------- deterministic fake for mock mode
_INSTRUCTION_LIKE = re.compile(r"ignore (all )?previous|system override|assistant instructions|attention ai|automated reviewer", re.I)


def _mock(user: str) -> dict:
    from triage.pipeline import REASON_CODE_DEFAULTS

    carc = re.search(r'"carc": "([A-Z]+-\d+)"', user).group(1)
    cause, correctable, supports = REASON_CODE_DEFAULTS[carc]
    lines = re.findall(r"^(D\d+) \[[^\]]+\]: (.*)$", user, re.M)
    suspicious = [i for i, t in lines if _INSTRUCTION_LIKE.search(t)]
    evidence = [i for i, _ in lines if i not in suspicious][:2]
    return {"root_cause": cause, "correctable": correctable, "evidence_supports_appeal": supports, "evidence_lines": evidence,
            "suspicious_lines": suspicious, "confidence": 0.6, "reason": f"Mock classification from reason code {carc}."}


llm.register_mock(TOOL["name"], _mock)
