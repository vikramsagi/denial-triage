"""Five deliberately bad letters. The citation checker must fail every one."""

import pytest

from triage.citations import check
from triage.load import load_split

GOOD = "The record documents 10 weeks of failed conservative management [D5]."


@pytest.fixture(scope="module")
def recs():
    ds = {d.denial_id: d for d in load_split("dev")}
    return ds["DN-39870"], ds["DN-98795"]


PLANTED = {
    "missing citation": "The record documents 10 weeks of failed conservative management.",
    "wrong line": "The record documents 10 weeks of failed conservative management [D3].",
    "invented date": "The study was performed on 2025-08-09 [claim.service_date].",
    "invented amount": "The allowed amount is 1,964.90 USD [claim.allowed_amount].",
}


def test_good_letter_passes(recs):
    assert check(GOOD, recs[0]).passed


@pytest.mark.parametrize("kind", PLANTED)
def test_planted_bad_letter_fails(recs, kind):
    assert not check(PLANTED[kind], recs[0]).passed, kind


def test_letter_for_another_claim_fails(recs):
    """A correct letter for DN-39870 checked against DN-98795 must fail."""
    letter = "Claim ID: DN-39870 [claim.denial_id]\n" + GOOD
    assert check(letter, recs[0]).passed
    assert not check(letter, recs[1]).passed
