"""Turn a checked letter into the version a billing specialist sends.

The checked letter carries citation markers such as [D3] so the checker and judge can verify it. The
sent letter replaces them with numbered enclosures: each cited documentation line becomes an attached
source document the payer reviewer can check. Claim-field citations are dropped, since those values
are the payer's own claim data.
"""

from __future__ import annotations

import re
from datetime import date

from triage.citations import CITE
from triage.schema import DenialInput

SOURCE_NAMES = {
    "clinical_note": "Clinical note", "billing_note": "Billing note", "payer_policy": "Payer policy excerpt",
    "eligibility": "Eligibility record", "authorization": "Authorization record", "credentialing": "Credentialing record",
    "correspondence": "Payer correspondence", "remittance": "Remittance record", "scheduling": "Scheduling record",
}


def render(letter: str, d: DenialInput, sent_on: date | None = None) -> str:
    lines = {x.id: x for x in d.documentation}
    order: list[str] = []
    for cid in CITE.findall(letter):
        if cid in lines and cid not in order:
            order.append(cid)
    number = {cid: i + 1 for i, cid in enumerate(order)}

    def swap(m: re.Match) -> str:
        cid = m.group(1)
        return f" (Enclosure {number[cid]})" if cid in number else ""

    body = letter.split("\n\n", 1)[1] if letter.startswith("Claim ID:") else letter
    body = re.sub(r"\s*\[([^\]]+)\]", lambda m: swap(re.match(r"(.*)", m.group(1))), body)
    body = re.sub(r"\(Enclosure (\d+)\)(\s*\(Enclosure (\d+)\))+", lambda m: "(Enclosures " + ", ".join(re.findall(r"\d+", m.group(0))) + ")", body)
    body = re.sub(r" +([.,;])", r"\1", body)
    c = d.claim
    head = (f"{(sent_on or date.today()).isoformat()}\n\n{d.payer.name}\nAppeals Department\n\n"
            f"Re: Request for reconsideration\nClaim ID: {d.denial_id}\nMember ID: {c.member_id}\n"
            f"Date of service: {c.service_date}\nProcedure code: {' '.join(x.cpt for x in c.lines)}\n"
            f"Denial reason code: {d.denial.carc}\n\nTo the appeals reviewer:\n\n")
    enc = "\n".join(f"{number[cid]}. {SOURCE_NAMES.get(lines[cid].source, lines[cid].source.replace('_', ' ').capitalize())}: "
                    f"{lines[cid].text}" for cid in order)
    return head + body.strip() + "\n\nSincerely,\n\n[Billing specialist name]\n[Provider name and contact]\n\n" + (f"Enclosures\n{enc}\n" if enc else "")
