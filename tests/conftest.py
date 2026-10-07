"""Every test runs in mock mode with a throwaway spend ledger, so tests never call the API or spend money."""

import os

import pytest


@pytest.fixture(autouse=True)
def _mock_and_private_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_MOCK", "1")
    monkeypatch.setenv("TRIAGE_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield
