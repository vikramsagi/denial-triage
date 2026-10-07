# Denial triage and appeal agent

An AI agent that works a queue of denied medical claims. It finds why each claim was denied, appeals only when the expected recovery is greater than the cost of the appeal, and drafts appeal letters in which every fact cites the source document. Quality is measured with evals on a frozen held-out set.

All data is synthetic. This project is not for clinical or billing use.

## The problem

Payers deny about 12% of hospital claims on first submission ([Optum 2024 Denials Index](https://marketplace.optum.com/content/dam/change-healthcare/marketplace-assets/outcomes-and-insights/2024-denials-index.pdf)). A provider's billing team must decide, for each denial, whether to fix and resend the claim, appeal it, or write it off. Appeals cost about 57 to 108 USD each, so appealing everything wastes money, and appealing nothing leaves recoverable revenue unpaid. See [docs/brief.md](docs/brief.md).

## How it works

```
denial -> rules check -> small model classifies twice (only if rules cannot) -> overturn probability
       -> expected value routing: appeal | fix and resubmit | write off | human review
          (reads disagree, or claim of 5,000 USD or more: a person decides)
       -> grounded appeal letter (larger model) -> citation checker -> letter judge (largest model)

every stage -> decision events -> monitoring and alerts -> outcome feedback -> recalibration
```

## Status

| Component | Status |
| --- | --- |
| Synthetic dataset with answer key, 200 dev and 100 frozen held-out records | Done |
| Rules, expected value routing, baselines, eval harness | Done. Best system without a model captures 83% of available value on dev, 78% acting alone ([evaluation report](docs/eval-report.md)) |
| High-risk review: claims of 5,000 USD or more go to a person with the system's recommendation and reasoning | Done |
| Model classification and prompt injection defense | Done on dev. Rules first, then Claude Haiku 4.5 with thinking: 98.9% of available value (95% interval 97.5 to 99.9), root cause correct 94.5%, 0 of 12 injection attempts succeeded, 0.0053 USD per denial ([evaluation report](docs/eval-report.md), [rules first](docs/adr/ADR-001-rules-first-then-model.md), [model choice](docs/adr/ADR-002-model-tiering.md)) |
| Grounded drafting and citation checker | Done on dev. Claude Sonnet 5.5 writes the letters; 61 of 61 dev letters pass a deterministic citation checker on the first try, at 0.0104 USD per letter ([decision record](docs/adr/ADR-003-grounded-drafting.md)) |
| Evaluation suite: intervals, slices, mutants, stability, letter judge, regression tests | Done on dev. Final system captures 99.9% of available value (95% interval 99.8 to 99.9) at 0.0185 USD per denial; two independent classifier reads send disagreements to a person ([evaluation report](docs/eval-report.md), [two-read check](docs/adr/ADR-004-two-read-agreement-check.md), [letter judge](docs/adr/ADR-005-letter-judge.md)) |
| Observability: decision events, drift monitoring, and an outcome feedback loop tested on a simulated post-launch week | Planned |
| Web demo with a step-by-step replay of each denial | Planned |
| Held-out results and case study | Planned |

## Documents

- [Brief](docs/brief.md): problem, user, success measures, roadmap
- [Data card](docs/data-card.md): what is in the dataset, cost assumptions with sources, known limits
- [Evaluation report](docs/eval-report.md): how decisions are scored, baselines, and checks that the metrics can fail
- [Assumptions log](docs/assumptions.md): every number the results depend on, its source, and how to test it
- Architecture decision records (`docs/adr/`): added as each decision is made, with the rejected options and the numbers that decided it

## Run it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run pytest -q
```

The dataset in `data/` is frozen. Tests check its SHA-256 hashes against `data/summary.json`.
