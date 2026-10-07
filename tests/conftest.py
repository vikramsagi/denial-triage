"""Every test runs in mock mode with a throwaway spend ledger, so tests never call the API or spend money."""

import os
import tempfile

import pytest

# Set at import time as well, so module-scoped fixtures, which run before the per-test fixture below,
# can never reach the live API.
os.environ["TRIAGE_MOCK"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["TRIAGE_LEDGER"] = os.path.join(tempfile.mkdtemp(prefix="triage-test-"), "ledger.jsonl")


@pytest.fixture(autouse=True)
def _mock_and_private_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_MOCK", "1")
    monkeypatch.setenv("TRIAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield
