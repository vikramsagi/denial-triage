# ADR-006: Monitoring from decision events, and a feedback loop from appeal outcomes

Date: 2026-10-08
Status: accepted

## Context

After launch, the world changes in ways the dev set never showed: a payer tightens its rules, claim formats change, a new document source appears. The system has no right answers in production, so it needs two things: signals that something has moved, computed only from what the system itself records, and a way to learn from the outcomes that come back weeks later.

## Options

- **A. Accuracy dashboards only.** Needs right answers, which production does not have.
- **B. Monitoring from decision events.** Every pipeline stage already writes an event (route, rule result, both reads, win odds, cost). Compare a new batch with a known-good baseline and alert on shifts.
- **C. B plus an outcome feedback loop.** Appeal outcomes and reviewer decisions come back and correct the win odds per payer and denial reason.

## Decision

Option C.

**Signals, with thresholds set before the test week:**

| Signal | Why it matters | Warn | Alert |
| --- | --- | --- | --- |
| Route mix (PSI) | Inputs or behavior changed | 0.10 | 0.25 |
| Denial reason mix (PSI) | A payer changed what it denies | 0.10 | 0.25 |
| Model confidence (PSI) | The model sees unfamiliar inputs | 0.10 | 0.25 |
| Share settled by rules | Claim formats changed | 5 points | 10 points |
| Two-read disagreement rate | Inputs got harder | 3 points | 6 points |
| Share sent to a person | Review queue cost and capacity | 3 points | 6 points |
| Injection flag rate | An attack or a new document source | 3 points | 6 points |
| Mean win odds on appeals | The appeal mix moved | 5 points | 10 points |
| Cost per denial | Spend | +20% | +50% |

PSI is the population stability index, a standard measure of how far a distribution has moved.

**Feedback.** For each payer and denial reason with at least 4 appeal outcomes, compare wins with the wins the system expected. The correction is a multiplier on the win odds, pulled toward 1.0 by 4 pseudo-appeals so that a few outcomes cannot swing it far ([code](../../triage/feedback.py)).

## Evidence

**The test week** ([generator](../../data/generate_week.py), [results](../../evals/runs/20261008T140348Z-week-feedback.json)): 150 new synthetic denials. Northwind Health Plan tightens prior authorization: prior-authorization denials rise from 13% to 30% of the queue, its denial notes use wording the system has never seen, and its appeals win about a fifth as often as before. The week was never used to tune anything. Days 1 to 3 feed the feedback loop; days 4 to 7 measure it.

**Monitoring:**

- On a rerun of dev it stays quiet: 0 alerts, 0 warnings.
- On the week it warns that the denial reason mix shifted (PSI 0.226, just under the 0.25 alert line).
- Injection flags dropped from 5% to 0%, because the week contains no planted attacks. The monitor warns in both directions.
- Route mix, confidence, rules share, disagreement, and cost stayed inside their bands. The system kept working normally on the new wording, so only the change in what was denied was visible from inside.
- The thresholds were not adjusted after seeing the week, so the result is a warning, not an alert.

**Feedback loop:**

- Days 1 to 3 returned 19 appeal outcomes.
- For Northwind prior authorization, 7 appeals were filed. The system expected 3.82 wins and got 1. The correction cut those win odds to 0.53 times their old value; the raw ratio would have been 0.26.
- No other payer and reason had enough outcomes to be corrected.
- Days 4 to 7 (85 denials, 21 affected by the drift):

| Days 4 to 7 | Value captured | Dollars lost | Appeal precision |
| --- | --- | --- | --- |
| Before correction | 99.81% (99.64 to 99.92) | 211.31 USD | 90.6% |
| After correction | 99.87% (99.78 to 99.94) | 147.32 USD | 93.5% |

The correction changed one decision: an appeal that was no longer worth filing at the lower odds was written off.

**What this shows, and what it does not.**

- Monitoring caught the shift without any right answers.
- The feedback loop learned the right direction from a handful of outcomes and was conservative by design.
- The dollar gain is small. Most of Northwind's affected claims were still worth appealing even at the lower odds, and the claims at risk were mid-sized.
- A larger drift, or larger claims, would make the same correction worth more. The intervals overlap, so this test shows the mechanism works, not that it pays off.

## Consequences

- Easier: every signal comes from events the pipeline already writes, so monitoring adds no model calls.
- Easier: corrections are per payer and reason, so one payer's change does not distort the others.
- Harder: outcomes arrive weeks after an appeal is filed, so corrections lag the change. A shorter loop would use reviewer overrides as an early signal; 2 of 6 reviewer decisions in days 1 to 3 differed from the recommendation.
- Harder: thresholds were set by rule of thumb. Production data would be needed to tune them.

## Revisit when

- A real outcome feed exists, to replace the simulated outcomes.
- Alerts fire often enough to need ranking, or never fire on real changes.
- Payer policy retrieval is added, since it would also catch rule changes directly.
