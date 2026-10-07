"""Letter judge: a stronger model grades each letter on faithfulness, persuasiveness, tone, and completeness.

It runs after the deterministic citation checker and covers what code cannot check. In evaluation and
in production it grades every letter through the batch API, which halves the price; appeal deadlines
leave time for that.
"""

from __future__ import annotations

import json

from triage import citations, llm
from triage.classify import PROMPTS
from triage.load import model_payload
from triage.schema import DenialInput

JUDGE_PROMPT_VERSION = "judge_v1"
JUDGE_TIER = "judge"
JUDGE_MAX_TOKENS = 4000
CRITERIA = ["faithfulness", "persuasiveness", "tone", "completeness"]

TOOL = {
    "name": "record_grade",
    "description": "Record the grade for one appeal letter.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["reasoning", *CRITERIA, "unsupported_sentences", "ship", "fix_note"],
        "properties": {
            "reasoning": {"type": "string"},
            **{c: {"type": "integer", "minimum": 1, "maximum": 5} for c in CRITERIA},
            "unsupported_sentences": {"type": "array", "items": {"type": "string"}},
            "ship": {"type": "boolean"},
            "fix_note": {"type": "string"},
        },
    },
}


def system_prompt(version: str = JUDGE_PROMPT_VERSION) -> str:
    return (PROMPTS / f"{version}.md").read_text()


def user_message(d: DenialInput, letter: str, case_strength: str) -> str:
    p = model_payload(d)
    fields = citations.citable_fields(d)
    docs = "\n".join(f"{line['id']} [{line['source']}]: {line['text']}" for line in p["documentation"])
    return ("<denial_record>\n<claim_fields>\n" + json.dumps(fields, indent=1) + "\n</claim_fields>\n"
            "<denial_reason>" + p["denial"]["carc"] + ": " + p["denial"]["carc_text"] + "</denial_reason>\n"
            "<documentation>\n" + docs + "\n</documentation>\n</denial_record>\n\n"
            f"<case_strength>{case_strength}</case_strength>\n\n<letter>\n{letter}\n</letter>\n\n"
            "Grade this letter by calling record_grade.")


def validate(out: dict) -> None:
    missing = [k for k in TOOL["input_schema"]["required"] if k not in out]
    if missing:
        raise ValueError(f"missing fields {missing}")
    for c in CRITERIA:
        if not 1 <= int(out[c]) <= 5:
            raise ValueError(f"{c} must be 1 to 5")


def ship_rule(out: dict) -> bool:
    """The verdict follows the rubric, whatever the model wrote in `ship`."""
    return out["faithfulness"] == 5 and all(out[c] >= 3 for c in CRITERIA)


def grade(d: DenialInput, letter: str, case_strength: str, run_id: str | None = None) -> dict:
    res = llm.call(tier=JUDGE_TIER, system=system_prompt(), user=user_message(d, letter, case_strength), tool=TOOL,
                   purpose="judge", run_id=run_id, max_tokens=JUDGE_MAX_TOKENS, validate=validate)
    out = dict(res.output)
    out["ship"] = ship_rule(out)
    return out | {"cost_usd": res.cost_usd}


def _mock(user: str) -> dict:
    return {"reasoning": "mock", "faithfulness": 5, "persuasiveness": 4, "tone": 5, "completeness": 4,
            "unsupported_sentences": [], "ship": True, "fix_note": ""}


llm.register_mock(TOOL["name"], _mock)
