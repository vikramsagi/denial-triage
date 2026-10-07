"""No answer-key field or value may reach a model payload."""

import json

import pytest

from triage.load import HeldoutLocked, load_labels, load_split, model_payload, strip_labels
from triage.schema import DenialInput

LABEL_KEYS = {"labels", "root_cause", "scenario", "correctable", "evidence_supports_appeal", "true_overturn_probability",
              "action_values", "best_action", "evidence_lines", "difficulty", "amount_band", "is_adversarial",
              "injection", "line_provenance"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_payload_has_no_label_keys():
    for d in load_split("dev"):
        assert not set(_keys(model_payload(d))) & LABEL_KEYS


def test_payload_has_no_label_only_values():
    labels = load_labels("dev")
    for d in load_split("dev"):
        blob = json.dumps(model_payload(d))
        lab = labels[d.denial_id]
        assert lab["scenario"] not in blob
        assert "line_provenance" not in blob and "true_overturn_probability" not in blob


def test_record_with_labels_is_rejected_by_schema():
    row = json.loads(open("data/dev.jsonl").readline())
    with pytest.raises(Exception):
        DenialInput.model_validate(row)
    assert strip_labels(row).denial_id == row["denial_id"]


def test_heldout_is_locked():
    with pytest.raises(HeldoutLocked):
        load_split("heldout")
    with pytest.raises(HeldoutLocked):
        load_labels("heldout")
