"""Dataset checks. These tests read data/dev.jsonl only. They never open data/heldout.jsonl."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))

import generate  # noqa: E402
from triage import config  # noqa: E402

DEV = ROOT / "data" / "dev.jsonl"
SUMMARY = json.loads((ROOT / "data" / "summary.json").read_text())
NO_MERIT = {"reg_true_termination", "code_unsupported", "tf_truly_late", "dup_true_duplicate", "nc_plan_exclusion"}


@pytest.fixture(scope="module")
def dev():
    return [json.loads(line) for line in DEV.read_text().splitlines()]


def test_dev_file_is_frozen():
    assert hashlib.sha256(DEV.read_bytes()).hexdigest() == SUMMARY["sha256"]["dev"]


def test_generator_is_deterministic(tmp_path):
    summary = generate.main(out_dir=tmp_path, quiet=True)
    assert summary["sha256"] == SUMMARY["sha256"]


def test_no_template_variant_shared_across_splits():
    assert SUMMARY["template_variants_shared_across_splits"] == 0


def test_dev_counts(dev):
    assert len(dev) == 200
    assert sum(r["labels"]["is_adversarial"] for r in dev) == 12
    assert len({r["denial_id"] for r in dev}) == 200


def test_evidence_lines_exist(dev):
    for r in dev:
        ids = {d["id"] for d in r["documentation"]}
        assert r["labels"]["evidence_lines"] and set(r["labels"]["evidence_lines"]) <= ids


def test_answer_key_matches_value_rules(dev):
    for r in dev:
        lab = r["labels"]
        allowed = r["claim"]["expected_allowed_amount"]
        args = (lab["root_cause"], allowed, lab["true_overturn_probability"], lab["correctable"])
        assert lab["action_values"] == config.action_values(*args)
        assert lab["best_action"] == config.best_action(*args)


def test_no_merit_denials_are_write_offs(dev):
    """Denials with no factual basis for appeal have overturn probability 0."""
    for r in dev:
        if r["labels"]["scenario"] in NO_MERIT:
            assert r["labels"]["true_overturn_probability"] == 0.0
            assert r["labels"]["best_action"] == "write_off"


def test_injection_targets_differ_from_truth(dev):
    for r in dev:
        inj = r["labels"]["injection"]
        if inj:
            assert inj["target_root_cause"] != r["labels"]["root_cause"]
            assert inj["target_action"] != r["labels"]["best_action"]
            assert inj["line_id"] not in r["labels"]["evidence_lines"]


def test_no_unfilled_placeholders(dev):
    for r in dev:
        for d in r["documentation"]:
            assert "{" not in d["text"] and "}" not in d["text"]
