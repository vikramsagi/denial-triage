"""Citation checker for appeal letters. Deterministic, no model call.

Rules:
1. Citations look like [D5] for a documentation line or [claim.service_date] for a record field.
2. Every cited ID must exist in the record.
3. Every sentence carries at least one citation, except the request and closing sentences, which
   start with a fixed phrase such as "We request" or "Please". A sentence that also contains a fact
   token (a date, an amount or other number, a code, or an ID) always needs a citation.
4. Every fact token in a sentence must appear in the text of at least one source that sentence cites.

What this does not check: whether a cited sentence without numbers says what its source says. That is
the judge's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from triage.schema import DenialInput

CITE = re.compile(r"\[((?:D\d+)|(?:claim|denial|payer)\.[a-z_]+)\]")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TOKEN = re.compile(
    rf"(?P<date>\d{{4}}-\d{{2}}-\d{{2}}|(?:{MONTHS}) \d{{1,2}}, \d{{4}})"
    r"|(?P<id>\b[A-Z]{1,4}-?\d{3,}[A-Z0-9-]*\b|\b[A-Z]\d{2}\.?[0-9A-Z]{0,4}\b)"
    r"|(?P<num>\b\d[\d,]*(?:\.\d+)?\b)"
)


def sources(d: DenialInput) -> dict[str, str]:
    """Every citable ID and its text."""
    out = {line.id: line.text for line in d.documentation}
    c = d.claim
    out.update({
        "claim.service_date": str(c.service_date),
        "claim.submitted_date": str(c.submitted_date),
        "claim.member_id": c.member_id,
        "claim.billed_amount": f"{c.billed_amount:.2f}",
        "claim.allowed_amount": f"{c.expected_allowed_amount:.2f}",
        "claim.procedure_codes": " ".join(line.cpt for line in c.lines),
        "claim.diagnosis_codes": " ".join(c.icd10),
        "claim.prior_auth_number": c.prior_auth_number or "",
        "claim.claim_id": d.denial_id,
        "claim.denial_id": d.denial_id,   # older name for the same value, kept so earlier letters still check
        "denial.reason_code": d.denial.carc,
        "denial.denial_date": str(d.denial.denial_date),
        "payer.name": d.payer.name,
        "payer.filing_limit_days": str(d.payer.filing_limit_days),
    })
    return out


LEGACY_FIELDS = {"claim.denial_id"}


def citable_fields(d: DenialInput) -> dict[str, str]:
    """Claim fields shown to the drafter and the judge, without the legacy names."""
    return {k: v for k, v in sources(d).items() if "." in k and v and k not in LEGACY_FIELDS}


def _norm(kind: str, tok: str) -> str:
    if kind == "date" and not tok[0].isdigit():
        return datetime.strptime(tok, "%B %d, %Y").strftime("%Y-%m-%d")
    if kind == "num":
        v = float(tok.replace(",", ""))
        return f"{v:.2f}" if v != int(v) or "." in tok else str(int(v))
    return tok


def _tokens(text: str) -> list[tuple[str, str, str]]:
    """(kind, raw, normalized) for every fact token, ignoring citation markers."""
    text = CITE.sub(" ", text)
    out = []
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        out.append((kind, m.group(), _norm(kind, m.group())))
    return out


def _present(norm: str, kind: str, source_text: str) -> bool:
    found = {n for _, _, n in _tokens(source_text)}
    if norm in found:
        return True
    if kind == "num":  # 964.9 in a field and 964.90 in a letter are the same amount
        try:
            v = float(norm)
            return any(abs(float(n) - v) < 0.005 for n in found if re.fullmatch(r"[\d.]+", n))
        except ValueError:
            return False
    return False


REQUEST = re.compile(r"^(we (respectfully )?(request|ask|appeal)|please|we are (available|prepared|happy)|we welcome|we remain|"
                     r"thank you|we would (welcome|appreciate)|additional (records|documentation) (are|is|can be))", re.I)


def _strip_markup(s: str) -> str:
    return re.sub(r"[*#>`]+", "", s).strip()


def sentences(letter: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])|\n+", letter)
    return [_strip_markup(p) for p in parts if _strip_markup(p)]


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    sentences_checked: int = 0
    citations: int = 0


def check(letter: str, d: DenialInput) -> CheckResult:
    src = sources(d)
    reasons: list[str] = []
    n_cites = 0
    sents = sentences(letter)
    for s in sents:
        cited = CITE.findall(s)
        n_cites += len(cited)
        unknown = [c for c in cited if c not in src]
        for c in unknown:
            reasons.append(f'cites [{c}], which does not exist in this record: "{s[:120]}"')
        toks = _tokens(s)
        if toks and not cited:
            reasons.append(f'states {", ".join(t[1] for t in toks)} with no citation: "{s[:120]}"')
            continue
        if not cited and not REQUEST.match(s):
            reasons.append(f'makes a statement with no citation; cite it or remove it: "{s[:120]}"')
            continue
        known = [src[c] for c in cited if c in src]
        if not known:
            continue
        for kind, raw, norm in toks:
            if not any(_present(norm, kind, t) for t in known):
                reasons.append(f'{raw} does not appear in {", ".join("[" + c + "]" for c in cited)}: "{s[:120]}"')
    return CheckResult(not reasons, reasons, len(sents), n_cites)
