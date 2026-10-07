"""Citation checker cases on dev record DN-39870 (sleep study, medical necessity denial)."""

import pytest

from triage.citations import check
from triage.load import load_split


@pytest.fixture(scope="module")
def rec():
    return next(d for d in load_split("dev") if d.denial_id == "DN-39870")


GOOD = (
    "Re: claim DN-39870 [claim.denial_id] for procedure 95810 [claim.procedure_codes], service date 2025-08-05 [claim.service_date].\n"
    "Your policy requires at least 6 weeks of conservative therapy for 95810 [D2]. "
    "The record documents 10 weeks of failed conservative management before the study [D5]. "
    "Objective findings support the diagnosis, with worsening function documented [D4]. "
    "We ask that you reverse the denial and pay the claim."
)


def test_clean_letter_passes(rec):
    r = check(GOOD, rec)
    assert r.passed, r.reasons


def test_missing_citation_fails(rec):
    r = check("The study was performed on 2025-08-05.", rec)
    assert not r.passed and "no citation" in r.reasons[0]


def test_wrong_line_fails(rec):
    r = check("The record documents 10 weeks of failed conservative management [D2].", rec)
    assert not r.passed and "10 does not appear" in r.reasons[0]


def test_invented_number_fails(rec):
    r = check("The patient completed 12 weeks of conservative therapy [D5].", rec)
    assert not r.passed and "12" in r.reasons[0]


def test_invented_date_fails(rec):
    r = check("Service was provided on 2025-08-06 [claim.service_date].", rec)
    assert not r.passed


def test_invented_amount_fails(rec):
    r = check("The allowed amount is 1,250.00 USD [claim.allowed_amount].", rec)
    assert not r.passed


def test_amount_formats_match(rec):
    r = check("The allowed amount is 964.90 USD [claim.allowed_amount].", rec)
    assert r.passed, r.reasons


def test_long_date_matches_iso(rec):
    r = check("Service was provided on August 5, 2025 [claim.service_date].", rec)
    assert r.passed, r.reasons


def test_unknown_citation_fails(rec):
    r = check("The record documents 10 weeks of therapy [D9].", rec)
    assert not r.passed and "does not exist" in r.reasons[0]


def test_uncited_statement_without_numbers_fails(rec):
    r = check("The procedure was clinically appropriate for the member's condition.", rec)
    assert not r.passed and "no citation" in r.reasons[0]


def test_request_sentence_needs_no_citation(rec):
    r = check("We respectfully request that you reverse the denial. Please contact us for further records.", rec)
    assert r.passed, r.reasons
