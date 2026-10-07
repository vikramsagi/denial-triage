# ADR-004: Two independent reads decide when a call is unsafe to automate

Date: 2026-10-07
Status: accepted

## Context

The classifier sometimes gives a different answer on the same record. Across three identical full dev runs, 192 of 200 denials got the same route every time (96%). The few that flipped cost the most. In one run, a 1,585.74 USD sleep study where the payer's records request was never answered was appealed (worth 342 USD) instead of fixed by sending the records (worth 1,481 USD). The system needs a signal that tells it when not to act on its own.

## Options

- **A. Confidence cutoff.** Send a call to a person when the model's stated confidence is low.
- **B. Rank by expected loss.** Send the calls with the largest (1 minus confidence) times dollars at risk to a person.
- **C. Two reads, disagreement to a person.** Classify each denial twice in separate calls. If the two reads lead to different actions, a person decides and sees both readings.
- **D. Three reads, majority vote.** No person; a third read breaks the tie.
- **E. One read.** Accept the variance.

## Decision

Option C.

## Evidence

**Model confidence does not separate right calls from wrong ones.** Most answers report 0.85 to 0.95. The three largest dev losses reported 0.78, 0.88, and 0.88, while a typical right answer reports 0.85. Option A would catch none of the three. Option B would also catch none, because when the model misreads the evidence it also believes little money is at stake.

**Disagreement does separate them.** Two prompt-version-3 runs agreed on 137 of the 143 denials the model reads, losing 177 USD there. They disagreed on 6, which held 2,314 USD of loss, 92% of the total.

**On the final prompt** (version 4), with two fresh runs ([check](../../evals/runs/20261007T233811Z-dev-two-read-check.json), [stability](../../evals/runs/20261007T233749Z-dev-stability.json)):

| | One read | Two reads, disagreement to a person |
| --- | --- | --- |
| Value captured | 98.7% (96.0 to 100) | 99.9% (99.8 to 99.9) |
| Dollars lost on 200 denials | 3,026 USD | 257 USD |
| Appeal precision | 95.3% | 98.4% (94.9 to 100) |
| Claims sent to a person | 9 (4.5%) | 15 (7.5%) |
| Classification cost per denial | 0.0052 USD | 0.0104 USD |

The 6 extra reviews cost 90 USD and remove about 2,770 USD of loss.

**What agreement cannot catch.** Two reads that make the same mistake agree. On prompt version 3, two scenarios were misread in most runs: an authorization for a different procedure code when the operative note explains why the procedure changed, and a code the record does not support called fixable. Agreement left those losses in place (one pair of runs still lost 1,417 USD). Prompt version 4 added one rule for each. Both scenarios were then read correctly on every record (5 of 5 and 10 of 10). Agreement handles random flips; prompt changes and error analysis handle consistent mistakes.

## Consequences

- Easier: the rule is simple to explain to a billing manager and to audit. Every escalation shows both readings.
- Easier: the share of denials where the reads disagree is a monitoring signal. A rise means inputs have changed.
- Harder: classification cost doubles, to about 0.0104 USD per denial. Total AI cost per denial is about 0.0185 USD including letters and grading, close to the 0.02 USD target.
- Harder: the review queue grows from 4.5% to 7.5% of denials.

## Revisit when

- Monitoring shows the disagreement rate above 10%, which would flood the review queue.
- A model reports calibrated confidence, which would make a cutoff cheaper than a second read.
- The cost target tightens. A second read only on denials above a dollar threshold would cut the cost.
