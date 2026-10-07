"""The only path to the model API.

Every call: checks the budget first, forces a structured answer through a tool schema, validates it,
computes cost from the returned token usage, and writes the cost to the spend ledger.

Mock mode (TRIAGE_MOCK=1, or no API key) replaces the API with a deterministic fake so tests and
dry runs cost nothing.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from triage import budget, config

ROOT = Path(__file__).resolve().parent.parent
_MOCKS: dict[str, Callable[[str], dict]] = {}


@dataclass
class LLMResult:
    output: dict
    model: str
    usage: dict
    cost_usd: float
    latency_ms: float
    mock: bool
    attempts: int = 1
    raw_errors: list[str] = field(default_factory=list)


def _api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip() or None
    return None


def mock_mode() -> bool:
    return os.environ.get("TRIAGE_MOCK") == "1" or _api_key() is None


def register_mock(tool_name: str, fn: Callable[[str], dict]) -> None:
    """Register a deterministic fake for one tool. `fn` receives the user message text."""
    _MOCKS[tool_name] = fn


def cost_of(tier: str, usage: dict, batch: bool = False) -> float:
    p = config.MODELS[tier]
    usd = (usage.get("input_tokens", 0) * p["input"]
           + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
           + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
           + usage.get("output_tokens", 0) * p["output"]) / 1_000_000
    return usd * (config.BATCH_DISCOUNT if batch else 1.0)


def estimate_max_cost(tier: str, system: str, user: str, max_tokens: int) -> float:
    p = config.MODELS[tier]
    approx_input = (len(system) + len(user)) / 3.0  # conservative: about 3 characters per token
    return (approx_input * p["cache_write"] + max_tokens * p["output"]) / 1_000_000


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=_api_key(), max_retries=3)


def call(*, tier: str, system: str, user: str, tool: dict, purpose: str, run_id: str | None = None,
         max_tokens: int = config.CLASSIFY_MAX_TOKENS, validate: Callable[[dict], Any] | None = None,
         max_attempts: int = 2, thinking: bool = False) -> LLMResult:
    """Call the model with a required tool. `validate` raises on a bad answer, which triggers one retry.

    With thinking on, the model reasons before answering. The API does not allow a forced tool together
    with thinking, so the tool is offered with tool_choice auto and the validator checks it was used.
    """
    model = config.MODELS[tier]["id"]
    if thinking:
        max_tokens = max_tokens + config.THINKING_BUDGET_TOKENS
    errors: list[str] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    total_cost = 0.0
    started = time.perf_counter()
    for attempt in range(1, max_attempts + 1):
        budget.check(estimate_max_cost(tier, system, user, max_tokens))
        if mock_mode():
            output = _MOCKS[tool["name"]](user)
            usage = {"input_tokens": len(user) // 4, "output_tokens": 150 + (config.THINKING_BUDGET_TOKENS if thinking else 0), "cache_creation_input_tokens": 0,
                     "cache_read_input_tokens": len(system) // 4}
            cost, is_mock = 0.0, True
        else:
            kwargs = {}
            if thinking and config.MODELS[tier].get("thinking") == "adaptive":
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["extra_body"] = {"output_config": {"effort": config.THINKING_EFFORT}}
                kwargs["tool_choice"] = {"type": "auto"}
            elif thinking:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": config.THINKING_BUDGET_TOKENS}
                kwargs["tool_choice"] = {"type": "auto"}
            elif config.MODELS[tier].get("forced_tool", True):
                kwargs["tool_choice"] = {"type": "tool", "name": tool["name"]}
            else:
                kwargs["tool_choice"] = {"type": "auto"}
            resp = _client().messages.create(
                model=model, max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                tools=[tool], **kwargs,
            )
            usage = {k: getattr(resp.usage, k, 0) or 0 for k in total_usage}
            blocks = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            output = blocks[0].input if blocks else {}
            cost, is_mock = cost_of(tier, usage), False
        budget.record(model=model, purpose=purpose, usage=usage, cost_usd=cost, run_id=run_id, mock=is_mock)
        for k in total_usage:
            total_usage[k] += usage[k]
        total_cost += cost
        try:
            if validate:
                validate(output)
            return LLMResult(output, model, total_usage, total_cost, (time.perf_counter() - started) * 1000, is_mock, attempt, errors)
        except Exception as e:  # noqa: BLE001 - any validation failure triggers a retry
            errors.append(f"attempt {attempt}: {type(e).__name__}: {str(e)[:300]}")
            user = user + f"\n\nYour previous answer was rejected: {str(e)[:300]}. Answer again using the tool, following the schema exactly."
    raise InvalidOutput(errors, total_usage, total_cost)


class InvalidOutput(RuntimeError):
    def __init__(self, errors: list[str], usage: dict, cost_usd: float):
        super().__init__("; ".join(errors))
        self.errors, self.usage, self.cost_usd = errors, usage, cost_usd


# ---------------------------------------------------------------- batch path for full runs (50% off)
def submit_batch(*, tier: str, system: str, items: list[tuple[str, str]], tool: dict, max_tokens: int = config.CLASSIFY_MAX_TOKENS) -> str:
    """Submit (custom_id, user message) pairs as one batch. Returns the batch ID."""
    if mock_mode():
        raise RuntimeError("batch path is live only; use call() in mock mode")
    est = sum(estimate_max_cost(tier, system, u, max_tokens) for _, u in items) * config.BATCH_DISCOUNT
    budget.check(est)
    reqs = [{"custom_id": cid, "params": {
        "model": config.MODELS[tier]["id"], "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": u}], "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]}}} for cid, u in items]
    return _client().messages.batches.create(requests=reqs).id


def collect_batch(batch_id: str, tier: str, purpose: str, run_id: str | None = None, poll_s: int = 30) -> dict[str, dict]:
    client = _client()
    while client.messages.batches.retrieve(batch_id).processing_status != "ended":
        time.sleep(poll_s)
    out = {}
    for r in client.messages.batches.results(batch_id):
        if r.result.type != "succeeded":
            out[r.custom_id] = {"error": r.result.type}
            continue
        msg = r.result.message
        usage = {k: getattr(msg.usage, k, 0) or 0 for k in ["input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"]}
        cost = cost_of(tier, usage, batch=True)
        budget.record(model=config.MODELS[tier]["id"], purpose=purpose, usage=usage, cost_usd=cost, run_id=run_id, mock=False)
        blocks = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
        out[r.custom_id] = {"output": blocks[0].input if blocks else {}, "usage": usage, "cost_usd": cost}
    return out


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, default=str)
