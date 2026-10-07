# ADR-005: A stronger model grades every letter, through the batch API

Date: 2026-10-07
Status: accepted

## Context

The citation checker ([ADR-003](ADR-003-grounded-drafting.md)) proves that every date, amount, code, and ID in a letter appears in its source. It cannot tell whether a sentence says what its source says. "Ten weeks of successful conservative management" passes the checker when the source says "failed". A second layer has to read for meaning.

## Options

- **Which model grades:** Claude Opus 5.5, Claude Sonnet 5.5 (the writer), or Claude Haiku 4.5.
- **How much it grades:** every letter, or a sample.
- **How it is calibrated:** hand grades on 10 letters, or checks against the answer key.

## Decision

- Claude Opus 5.5 grades every letter, in evaluation and in production, through the batch API at half price. Appeal deadlines of 30 to 180 days leave time for batch processing.
- The judge scores faithfulness, persuasiveness, tone, and completeness from 1 to 5. A letter is ready to send only when faithfulness is 5 and no score is below 3. The rule is applied in code, not taken from the model.
- Calibration uses the answer key and planted letters instead of hand grades.

## Evidence

**Cost at scale.** Measured cost is 0.0149 USD per letter with batch. About 30% of denials get a letter.

| Denials per month | Letters | Opus 5.5 batch, every letter | Human review at 7.5% and 15 USD |
| --- | --- | --- | --- |
| 1,000 | 305 | 5 USD | 1,125 USD |
| 5,000 | 1,525 | 23 USD | 5,625 USD |
| 25,000 | 7,625 | 114 USD | 28,125 USD |

Queue sizes are scenarios, not measurements. At every size, grading is under 0.5% of reviewer cost, and one appeal saved by catching a bad letter is worth more than a month of grading.

**Calibration** ([run file](../../evals/runs/20261007T231943Z-dev-judge.json)):

- **Planted letters.** Five bad letters that all pass the citation checker: one contradicts its source, one invents a fact, one claims criteria are met on a weak case, one admits fault, one leaves out the key evidence. The judge failed all five.
- **Answer key.** On the first grading run, the judge's completeness score agreed with whether the letter cited every answer-key evidence line on 43 of 48 well-supported letters.
- **Length bias.** Ten good letters were padded with two irrelevant cited facts each. No score went up; persuasiveness fell on 3 of 10 ([run file](../../evals/runs/20261007T225445Z-dev-judge-length-test.json)).
- **Real findings.** The first grading run found 4 real misstatements. For example, one letter cited a plan rider as saying the service was not covered when the rider says it is covered. The judge also flagged 7 letters that labeled the record ID as "Claim ID" while the field was named for the denial. That was a naming flaw in the system, not the letters; the field was renamed and the letter prompt updated.

**Results on the final letters** (64 dev letters, letter prompt version 5):

| | Well-supported cases | Limited cases |
| --- | --- | --- |
| Letters | 51 | 13 |
| Ready to send | 45 (88%) | 0 |
| Main reason for not sending | Three letters answer a generic missing-information denial without naming what was missing | The record does not clearly support the appeal, so a person decides |

## Consequences

- Easier: a person reviews only letters the judge did not clear, with a one-sentence fix note.
- Harder: grading adds about 0.0047 USD per denial on average. Total AI cost per denial is about 0.0185 USD.
- Harder: the judge is sometimes strict about wording that is not in the source, for example "rendering provider" when the source says "provider". These cost a review, not a wrong letter.
- Not yet done: comparison with a person's grades. A billing specialist grading 20 letters would test the judge against expert judgment.

## Revisit when

- Grades from a billing specialist disagree with the judge on more than 2 letters in 10.
- The share of letters ready to send falls below 80% in monitoring.
- A cheaper model fails all five planted letters and matches the answer-key checks.
