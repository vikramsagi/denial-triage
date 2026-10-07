# ADR-002: Model tiering for classification

Date: 2026-10-07
Status: accepted

## Context

Denials that the structural rules cannot settle go to a model that reads the claim and its documentation. The model names the root cause, decides whether the provider can fix the claim or the payer is wrong, and cites the lines that prove it. The choice of model trades cost per denial against dollars recovered. Larger models and extended thinking cost more per call; the question is whether they recover more money.

## Options

- **A. Claude Haiku 4.5**: smallest and cheapest.
- **B. Claude Haiku 4.5 with extended thinking**: the model reasons before answering.
- **C. Claude Sonnet 5.5**: larger model.
- **D. Claude Sonnet 5.5 with adaptive thinking.**

Claude Opus 5.5 was excluded before the test: with thinking it would cost about 0.038 USD per call, above the 0.02 USD target.

## Decision

Option B, Claude Haiku 4.5 with extended thinking (budget 1,500 reasoning tokens).

## Evidence

All arms ran on the same 40 dev denials that the structural rules cannot settle (16 easy, 14 medium, 10 hard), with the same prompt (`prompts/classify_v3.md`), the same win odds table, and the same router. None of these 40 denials was used to write or tune the prompt. Value captured is dollars earned under the answer key divided by the best possible; the range is a 95% bootstrap interval.

| Arm | Root cause correct | Value captured | Dollars lost | Cost per denial | Evidence |
| --- | --- | --- | --- | --- | --- |
| No model (structural rules, reason-code fallback) | 26 of 40 | 70.2% (48.6 to 90.2) | 12,794 USD | 0.0000 USD | [run file](../../evals/runs/20261007T150707Z-dev-bakeoff40-b2_rules_ev.json) |
| Claude Haiku 4.5 | 38 of 40 | 99.1% (97.7 to 99.9) | 372 USD | 0.0039 USD | [run file](../../evals/runs/20261007T150911Z-dev-bakeoff40-m_rules_small.json) |
| Claude Haiku 4.5 with thinking | 38 of 40 | 99.6% (99.0 to 99.9) | 173 USD | 0.0073 USD | [run file](../../evals/runs/20261007T151607Z-dev-bakeoff40-m_rules_small_think.json) |
| Claude Sonnet 5.5 | 40 of 40 | 87.6% (69.6 to 99.9) | 5,311 USD | 0.0060 USD | [run file](../../evals/runs/20261007T152830Z-dev-bakeoff40-m_rules_large.json) |
| Claude Sonnet 5.5 with thinking | 39 of 40 | 87.6% (69.6 to 99.9) | 5,311 USD | 0.0053 USD | [run file](../../evals/runs/20261007T152136Z-dev-bakeoff40-m_rules_large_think.json) |

Findings:

- Every model arm beats the no-model system. The Haiku arms' intervals sit entirely above the no-model interval.
- Haiku 4.5 with thinking has the best value captured. Its lead over plain Haiku (one denial, 199 USD) is inside the margin of error, but its cost of 0.0073 USD per denial is well under the 0.02 USD target, and the expected gain per denial exceeds the extra cost.
- Sonnet 5.5 named every root cause correctly and still lost the most money. 5,195 USD of its 5,311 USD loss came from two retroactive coverage terminations. Sonnet judged that an eligibility check confirming active coverage on the service date does not prove the payer wrong, and wrote the claims off. The answer key treats that confirmation as grounds to appeal. The difference is a business policy, not reading ability.
- A first Sonnet run used a 600-token answer cap, which cut off two answers. The cap was raised to 1,000 tokens and Sonnet was rerun; the table shows the rerun.
- The injected instruction in the set changed no decision in any arm.

## Consequences

- Easier: the cheapest model family suffices, which leaves budget for drafting and evaluation.
- Harder: each call takes longer with thinking. Policy questions such as appeals of retroactive terminations must be written down explicitly, because a more careful model may apply a stricter standard.

## Revisit when

- Held-out results show Haiku errors that a larger model would catch.
- Payer rule packs state appeal policies explicitly; then rerun the Sonnet arms.
- Prices or model versions change.
